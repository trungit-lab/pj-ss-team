import json
import math
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen


HANOI_TIME = timezone(timedelta(hours=7))


def post(url, data, headers, timeout=12):
    request = Request(url, json.dumps(data).encode(), {
        "Content-Type": "application/json", **headers
    })
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def find_stations(origin, key):
    headers = {"X-Goog-Api-Key": key}
    results = post("https://places.googleapis.com/v1/places:searchNearby", {
        "includedTypes": ["gas_station"],
        "maxResultCount": 10,
        "rankPreference": "DISTANCE",
        "languageCode": "vi",
        "locationRestriction": {"circle": {"center": origin, "radius": 2999.999}},
    }, {**headers, "X-Goog-FieldMask":
        "places.id,places.displayName,places.formattedAddress,places.location,places.businessStatus"})
    places = [place for place in results.get("places", [])
              if place.get("businessStatus") not in
              ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY")]
    if not places:
        return []
    routes = post("https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix", {
        "origins": [{"waypoint": {"location": {"latLng": origin}}}],
        "destinations": [{"waypoint": {"placeId": place["id"]}} for place in places],
        "travelMode": "TWO_WHEELER",
        "routingPreference": "TRAFFIC_AWARE",
    }, {**headers, "X-Goog-FieldMask":
        "destinationIndex,condition,status,distanceMeters,duration,staticDuration"})
    stations = []
    now = datetime.now(timezone.utc)
    try:
        observations = json.loads(os.getenv("FUEL_QUEUE_OBSERVATIONS", "{}"))
    except ValueError:
        observations = {}
    if not isinstance(routes, list):
        raise ValueError("Invalid route matrix")
    by_index = {}
    for route in routes:
        if not isinstance(route, dict) or route.get("condition") != "ROUTE_EXISTS":
            continue
        status = route.get("status", {})
        if not isinstance(status, dict) or status.get("code"):
            continue
        index = route.get("destinationIndex", 0)
        if type(index) is int and 0 <= index < len(places):
            by_index[index] = route
    for index, place in enumerate(places):
        observation = observations.get(place["id"]) if isinstance(observations, dict) else None
        stations.append(evaluate_station(place, by_index.get(index), now, observation))
    return stations


def service_at(when):
    local = when.astimezone(HANOI_TIME)
    peak = 7 <= local.hour < 9 or 16 <= local.hour < 19
    return peak, 4 if peak else 2


def project_queue(count, arrivals_per_minute, observed, arrival):
    cursor = observed.astimezone(HANOI_TIME)
    while cursor < arrival:
        boundaries = [cursor.replace(hour=hour, minute=0, second=0, microsecond=0)
                      for hour in (7, 9, 16, 19)]
        midnight = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = min(arrival, midnight, *(boundary for boundary in boundaries if boundary > cursor))
        minutes = (end - cursor).total_seconds() / 60
        count = max(0, count + (arrivals_per_minute - service_at(cursor)[1]) * minutes)
        cursor = end
    return math.ceil(count)


def duration_seconds(value):
    if not isinstance(value, str) or not value.endswith("s"):
        return None
    try:
        seconds = float(value[:-1])
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def evaluate_station(place, route, now=None, observation=None):
    route = route or {}
    seconds = duration_seconds(route.get("duration"))
    reference = duration_seconds(route.get("staticDuration"))
    distance = route.get("distanceMeters")
    if type(distance) is not int or distance < 0:
        distance = None
    now = now or datetime.now(timezone.utc)
    arrival = None
    if seconds is not None:
        try:
            arrival = (now + timedelta(seconds=seconds)).astimezone(HANOI_TIME)
        except OverflowError:
            seconds = None
    peak, service_slots = service_at(arrival) if arrival else (None, None)
    queue_count = None
    queue_source = None
    if arrival is not None and isinstance(observation, dict):
        try:
            observed = datetime.fromisoformat(observation["observedAt"])
            age = (now - observed).total_seconds() / 60
            count = observation["queueCount"]
            rate = observation.get("arrivalsPerMinute")
            if type(count) is int and count >= 0 and 0 <= age <= 15:
                if type(rate) in (int, float) and math.isfinite(rate) and rate >= 0:
                    queue_count = project_queue(count, rate, observed, arrival)
                    queue_source = "dự báo từ quan sát và tốc độ khách đến"
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
    wait = queue_count / service_slots if queue_count is not None else None
    crowd = None
    if queue_count is not None:
        crowd = "Vắng" if queue_count < 10 else "Vừa" if queue_count <= 20 else "Đông"
    return {
        "id": place["id"],
        "name": place["displayName"]["text"],
        "address": place.get("formattedAddress"),
        "lat": place["location"]["latitude"],
        "lon": place["location"]["longitude"],
        "travelMinutes": seconds / 60 if seconds is not None else None,
        "travelSource": "Google Routes" if seconds is not None else None,
        "evaluatedAt": now.isoformat(),
        "distanceMeters": distance,
        "speedKmh": round(3.6 * distance / seconds, 1) if seconds and distance is not None else None,
        "delayMinutes": round(max(0, seconds - reference) / 60, 1) if reference is not None and seconds is not None else None,
        "queueCount": queue_count,
        "queueSource": queue_source,
        "arrivalAt": arrival.isoformat() if arrival else None,
        "serviceMinutes": 1,
        "peak": peak,
        "serviceSlots": service_slots,
        "crowd": crowd,
        "waitMinutes": wait,
        "totalMinutes": seconds / 60 + wait + 1 if wait is not None else None,
    }
