import json
import math
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen


HANOI_TIME = timezone(timedelta(hours=7))
ADJACENT_ROAD_SEARCH_METERS = 500
ADJACENT_ROAD_MIN = 4
ADJACENT_ROAD_MAX = 6
LOCAL_QUEUE_SCALE_VEHICLES = 40


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
        stations.append(evaluate_station(place, by_index.get(index), now))
    return stations


def _distance_m(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def fetch_adjacent_traffic(station, key):
    """Read HERE flow in the station area and retain up to six nearest road segments."""
    lat, lon = station["lat"], station["lon"]
    params = urlencode({"in": f"circle:{lat},{lon};r={ADJACENT_ROAD_SEARCH_METERS}",
                        "locationReferencing": "shape", "apiKey": key})
    request = Request(f"https://data.traffic.hereapi.com/v7/flow?{params}",
                      headers={"Accept": "application/json", "User-Agent": "FuelFinder/1.0"})
    with urlopen(request, timeout=12) as response:
        data = json.load(response)
    rows = []
    for item in data.get("results", []):
        flow = item.get("currentFlow", {})
        location = item.get("location", {})
        shape = location.get("shape", {})
        points = []
        for link in shape.get("links", []) if isinstance(shape, dict) else []:
            points.extend(link.get("points", []))
        if not points:
            continue
        coordinates = [(p.get("lat", p.get("latitude")), p.get("lng", p.get("longitude")))
                       for p in points if isinstance(p, dict)]
        distance = min((_distance_m(lat, lon, point_lat, point_lon)
                        for point_lat, point_lon in coordinates
                        if isinstance(point_lat, (int, float))
                        and isinstance(point_lon, (int, float))), default=None)
        if distance is not None:
            rows.append((distance, {"roadName": location.get("description"),
                                    "distanceMeters": round(distance), **flow}))
    rows.sort(key=lambda row: row[0])
    selected, seen = [], set()
    for _, row in rows:
        name = row.get("roadName") or f"segment-{len(selected) + 1}"
        if name in seen:
            continue
        seen.add(name)
        selected.append(row)
        if len(selected) == ADJACENT_ROAD_MAX:
            break
    if len(selected) < ADJACENT_ROAD_MIN:
        return {"results": selected, "sourceUpdated": data.get("sourceUpdated")}
    return {"results": selected, "sourceUpdated": data.get("sourceUpdated")}


def local_traffic_estimate(traffic_data):
    """Estimate relative congestion from HERE jamFactor on adjacent road segments."""
    samples = []
    results = traffic_data.get("results", []) if isinstance(traffic_data, dict) else []
    for item in results:
        flow = item if isinstance(item, dict) else {}
        jam = flow.get("jamFactor")
        if isinstance(jam, (int, float)) and math.isfinite(jam) and 0 <= jam <= 10:
            samples.append({"roadName": flow.get("roadName"), "jamFactor": jam,
                            "speedMps": flow.get("speed"), "freeFlowMps": flow.get("freeFlow"),
                            "densityIndexPercent": jam * 10})
    if not samples:
        return {"densityIndexPercent": None, "estimatedQueueCount": None,
                "sampleCount": 0, "queueScaleVehicles": LOCAL_QUEUE_SCALE_VEHICLES,
                "source": None, "confidence": "unknown", "roads": [], "jamFactor": None,
                "sourceUpdated": traffic_data.get("sourceUpdated") if isinstance(traffic_data, dict) else None}
    if len(samples) < ADJACENT_ROAD_MIN:
        return {"densityIndexPercent": None, "estimatedQueueCount": None,
                "sampleCount": len(samples), "queueScaleVehicles": LOCAL_QUEUE_SCALE_VEHICLES,
                "source": None, "confidence": "unknown", "roads": samples, "jamFactor": None,
                "sourceUpdated": traffic_data.get("sourceUpdated")}
    index = sum(sample["densityIndexPercent"] for sample in samples) / len(samples)
    queue = math.ceil(LOCAL_QUEUE_SCALE_VEHICLES * index / 100.0)
    return {
        "densityIndexPercent": round(index, 1),
        "jamFactor": round(index / 10, 1),
        "estimatedQueueCount": queue,
        "sampleCount": len(samples),
        "queueScaleVehicles": LOCAL_QUEUE_SCALE_VEHICLES,
        "source": "HERE Traffic API",
        "confidence": "low",
        "roads": samples,
        "sourceUpdated": traffic_data.get("sourceUpdated"),
    }


def service_at(when):
    local = when.astimezone(HANOI_TIME)
    peak = 7 <= local.hour < 9 or 16 <= local.hour < 19
    return peak, 4 if peak else 2


def duration_seconds(value):
    if not isinstance(value, str) or not value.endswith("s"):
        return None
    try:
        seconds = float(value[:-1])
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def evaluate_station(place, route, now=None, adjacent_traffic=None):
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
    traffic = local_traffic_estimate(adjacent_traffic)
    queue_count = traffic["estimatedQueueCount"] if arrival is not None else None
    queue_source = "ước tính từ giao thông 4–6 đường tiếp giáp" if queue_count is not None else None
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
        "trafficDensityIndexPercent": traffic["densityIndexPercent"],
        "trafficJamFactor": traffic.get("jamFactor"),
        "trafficSampleCount": traffic["sampleCount"],
        "trafficQueueScaleVehicles": traffic["queueScaleVehicles"],
        "trafficEstimateConfidence": traffic["confidence"],
        "trafficRoads": traffic["roads"],
        "trafficSourceUpdated": traffic["sourceUpdated"],
        "arrivalAt": arrival.isoformat() if arrival else None,
        "serviceMinutes": 1,
        "peak": peak,
        "serviceSlots": service_slots,
        "crowd": crowd,
        "waitMinutes": wait,
        "totalMinutes": seconds / 60 + wait + 1 if wait is not None else None,
    }
