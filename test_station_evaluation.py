import json
import unittest
from datetime import datetime, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

import server
from station_evaluation import duration_seconds, evaluate_station, find_stations, project_queue, service_at


ORIGIN = {"latitude": 21.03, "longitude": 105.8}
NOW = datetime.fromisoformat("2026-11-14T15:58:00+07:00")


def place(id, **fields):
    return {"id": id, "displayName": {"text": id}, "formattedAddress": "Hà Nội",
            "location": ORIGIN, **fields}


class StationEvaluationTests(unittest.TestCase):
    def test_zero_reference_duration_is_known(self):
        route = {"duration": "60s", "staticDuration": "0s"}
        self.assertEqual(evaluate_station(place("A"), route, NOW)["delayMinutes"], 1)

    def test_duration_seconds_parses_google_format(self):
        for value, seconds in (("0s", 0), ("60s", 60), ("90.125s", 90.125)):
            with self.subTest(value=value):
                self.assertEqual(duration_seconds(value), seconds)

    def test_duration_seconds_rejects_missing_invalid_and_nonfinite_values(self):
        for value in (None, 60, "", "s", "9m", "abc s", "-1s", "NaNs", "infs"):
            with self.subTest(value=value):
                self.assertIsNone(duration_seconds(value))

    def test_project_queue_grows_by_arrivals_minus_capacity(self):
        self.assertEqual(project_queue(4, 3, NOW, NOW + timedelta(minutes=1)), 5)

    def test_project_queue_rounds_once_after_forecast(self):
        start = datetime.fromisoformat("2026-11-14T15:59:30+07:00")
        end = start + timedelta(minutes=1)
        self.assertEqual(project_queue(5, 3, start, end), 5)

    def test_rank_stations_uses_total_when_every_total_is_known(self):
        fast_drive = {"id": "A", "travelMinutes": 4, "totalMinutes": 11}
        fast_total = {"id": "B", "travelMinutes": 7, "totalMinutes": 9.5}
        self.assertEqual(server.rank_stations([fast_drive, fast_total]), [fast_total, fast_drive])

    def test_rank_stations_uses_eta_when_a_total_is_unknown(self):
        stations = [
            {"id": "A", "travelMinutes": None, "totalMinutes": None},
            {"id": "B", "travelMinutes": 7, "totalMinutes": 9.5},
            {"id": "C", "travelMinutes": 0, "totalMinutes": None},
        ]
        self.assertEqual([s["id"] for s in server.rank_stations(stations)], ["C", "B", "A"])

    def test_bad_route_does_not_hide_other_candidates(self):
        places = [place(str(index)) for index in range(4)]
        routes = [
            None,
            {"condition": "ROUTE_EXISTS", "destinationIndex": 99, "duration": "1s"},
            {"condition": "ROUTE_EXISTS", "status": {"code": 13}, "duration": "1s"},
            {"condition": "ROUTE_EXISTS", "duration": "NaNs", "distanceMeters": -1},
            {"condition": "ROUTE_EXISTS", "destinationIndex": 2, "duration": "90.5s",
             "staticDuration": None, "distanceMeters": 200},
        ]
        with patch("station_evaluation.post", side_effect=[{"places": places}, routes]):
            results = find_stations(ORIGIN, "fixture")
        self.assertEqual(len(results), 4)
        self.assertIsNone(results[0]["travelMinutes"])
        self.assertIsNone(results[0]["distanceMeters"])
        self.assertAlmostEqual(results[2]["travelMinutes"], 90.5 / 60)
        self.assertIsNone(results[2]["delayMinutes"])

    def test_invalid_and_zero_route_durations(self):
        for duration in (None, 20, "20", "-1s", "infs", "NaNs", "1e100s"):
            with self.subTest(duration=duration):
                result = evaluate_station(place("A"), {"duration": duration}, NOW)
                self.assertIsNone(result["travelMinutes"])
                self.assertIsNone(result["arrivalAt"])
        zero = evaluate_station(place("A"), {"duration": "0s", "distanceMeters": 0}, NOW)
        self.assertEqual(zero["travelMinutes"], 0)
        self.assertIsNone(zero["speedKmh"])

    def test_service_at_exact_boundaries(self):
        for hour, expected in [("06:59", 2), ("07:00", 4), ("08:59", 4), ("09:00", 2),
                               ("15:59", 2), ("16:00", 4), ("18:59", 4), ("19:00", 2)]:
            with self.subTest(hour=hour):
                when = datetime.fromisoformat(f"2026-11-14T{hour}:00+07:00")
                self.assertEqual(service_at(when), (expected == 4, expected))

    def test_queue_empty_before_capacity_drops(self):
        start = datetime.fromisoformat("2026-11-14T18:58:00+07:00")
        self.assertEqual(project_queue(1, 3, start, start + timedelta(minutes=4)), 2)

    def test_queue_crosses_midnight_without_negative_count(self):
        start = datetime.fromisoformat("2026-11-14T23:59:00+07:00")
        self.assertEqual(project_queue(1, 0, start, start + timedelta(minutes=3)), 0)

    def test_observation_exact_expiry_and_invalid_rates(self):
        observation = {"observedAt": (NOW - timedelta(minutes=15)).isoformat(),
                       "queueCount": 4, "arrivalsPerMinute": 2}
        route = {"duration": "60s"}
        self.assertEqual(evaluate_station(place("A"), route, NOW, observation)["queueCount"], 4)
        for rate in (-1, float("nan"), float("inf"), True, None):
            with self.subTest(rate=rate):
                bad = dict(observation, arrivalsPerMinute=rate)
                self.assertIsNone(evaluate_station(place("A"), route, NOW, bad)["queueCount"])

    def test_candidates_keep_missing_routes_and_exclude_closed_stations(self):
        places = [place(str(index)) for index in range(5)]
        places.insert(1, place("closed", businessStatus="CLOSED_TEMPORARILY"))
        routes = [
            {"destinationIndex": 4, "condition": "ROUTE_EXISTS", "duration": "120s"},
            {"condition": "ROUTE_EXISTS", "duration": "240s", "staticDuration": "180s",
             "distanceMeters": 1000},
            {"destinationIndex": 2, "condition": "ROUTE_NOT_FOUND"},
        ]
        with patch("station_evaluation.post", side_effect=[{"places": places}, routes]) as post:
            results = find_stations(ORIGIN, "fixture")
        self.assertEqual([station["id"] for station in results], list("01234"))
        self.assertEqual([station["travelMinutes"] for station in results], [4, None, None, None, 2])
        self.assertEqual(results[0]["address"], "Hà Nội")
        self.assertEqual(results[0]["speedKmh"], 15)
        self.assertEqual(results[0]["delayMinutes"], 1)
        self.assertLess(post.call_args_list[0].args[1]["locationRestriction"]["circle"]["radius"], 3000)
        self.assertEqual(post.call_args_list[1].args[1]["travelMode"], "TWO_WHEELER")

    def test_empty_places_skip_routes(self):
        with patch("station_evaluation.post", return_value={}) as post:
            self.assertEqual(find_stations(ORIGIN, "fixture"), [])
        post.assert_called_once()

    def test_queue_crosses_peak_boundary(self):
        observation = {"observedAt": NOW.isoformat(), "queueCount": 14, "arrivalsPerMinute": 3}
        result = evaluate_station(place("A"), {"duration": "240s"}, NOW, observation)
        self.assertTrue(result["peak"])
        self.assertEqual(result["queueCount"], 14)
        self.assertEqual(result["waitMinutes"], 3.5)
        self.assertEqual(result["totalMinutes"], 8.5)

    def test_crowd_thresholds_and_zero(self):
        for count, label in [(0, "Vắng"), (9, "Vắng"), (10, "Vừa"), (20, "Vừa"), (21, "Đông")]:
            with self.subTest(count=count):
                observation = {"observedAt": NOW.isoformat(), "queueCount": count, "arrivalsPerMinute": 2}
                result = evaluate_station(place("A"), {"duration": "60s"}, NOW, observation)
                self.assertEqual(result["crowd"], label)
                self.assertEqual(result["waitMinutes"], count / 2)

    def test_missing_stale_or_invalid_observation_stays_unknown(self):
        for timestamp in (None, (NOW - timedelta(minutes=16)).isoformat(),
                          (NOW + timedelta(minutes=1)).isoformat(), "invalid"):
            with self.subTest(timestamp=timestamp):
                observation = {"observedAt": timestamp, "queueCount": 0, "arrivalsPerMinute": 2}
                result = evaluate_station(place("A"), {"duration": "60s"}, NOW, observation)
                for field in ("queueCount", "waitMinutes", "totalMinutes", "crowd"):
                    self.assertIsNone(result[field])


class StationsApiTests(unittest.TestCase):
    def setUp(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        worker = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(worker.join)
        self.addCleanup(httpd.shutdown)
        self.connection = HTTPConnection(*httpd.server_address, timeout=3)
        self.addCleanup(self.connection.close)

    def request(self, payload):
        self.connection.request("POST", "/api/stations", json.dumps(payload),
                                {"Content-Type": "application/json"})
        response = self.connection.getresponse()
        return response.status, json.loads(response.read())

    def test_api_returns_all_candidates_and_three_fallback_choices(self):
        candidates = [evaluate_station(place(str(index)), {"duration": f"{index + 1}s"}, NOW)
                      for index in range(5)]
        candidates.append(evaluate_station(place("unknown"), None, NOW))
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "fixture", "FUEL_AGENT_URL": ""}):
            with patch.object(server, "find_stations", return_value=candidates):
                status, payload = self.request({"lat": 21, "lon": 105})
        self.assertEqual(status, 200)
        self.assertEqual(payload["candidates"], candidates)
        self.assertEqual([station["id"] for station in payload["stations"]], ["0", "1", "2"])

    def test_api_rejects_invalid_coordinates(self):
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "fixture"}):
            with patch.object(server, "find_stations") as find:
                status, _ = self.request({"lat": 91, "lon": 105})
        self.assertEqual(status, 400)
        find.assert_not_called()

    def test_api_reports_missing_google_key(self):
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": ""}):
            status, payload = self.request({"lat": 21, "lon": 105})
        self.assertEqual(status, 503)
        self.assertIn("GOOGLE_MAPS_API_KEY", payload["error"])

    def test_api_upstream_timeout_returns_error_without_secret(self):
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "fixture-secret"}):
            with patch("station_evaluation.post", side_effect=TimeoutError("fixture-secret")):
                status, payload = self.request({"lat": 21, "lon": 105})
        self.assertEqual(status, 502)
        self.assertNotIn("fixture-secret", payload["error"])
