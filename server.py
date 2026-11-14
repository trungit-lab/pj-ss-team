import json
import math
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from station_evaluation import fetch_adjacent_traffic, find_stations, local_traffic_estimate, post


def rank_stations(stations):
    metric = "totalMinutes" if all(s["totalMinutes"] is not None for s in stations) else "travelMinutes"
    return sorted(stations, key=lambda station: (station[metric] is None, station[metric] or 0))


def summarize(stations):
    endpoint = os.getenv("FUEL_AGENT_URL")
    if not endpoint or not stations:
        return None
    token = os.getenv("FUEL_AGENT_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    context = [{
        "option": index,
        **{field: station[field] for field in
           ("travelMinutes", "speedKmh", "delayMinutes", "trafficDensityIndexPercent", "trafficJamFactor",
            "trafficSampleCount", "trafficQueueScaleVehicles", "trafficEstimateConfidence",
            "trafficRoads", "trafficSourceUpdated", "queueCount", "crowd",
            "waitMinutes", "totalMinutes")},
    } for index, station in enumerate(stations, 1)]
    try:
        result = post(endpoint, {
            "instruction": (
                "Tóm tắt tối đa một câu tiếng Việt về các lựa chọn đã xếp hạng. "
                "Giữ nguyên số liệu. null là chưa biết. Ùn tắc đường không cho biết "
                "chính xác hàng chờ cây xăng. trafficJamFactor là mức ùn tắc HERE từ 0 đến 10, "
                "không phải số xe. queueCount là quy đổi heuristic độ tin cậy thấp từ tối đa 6 đoạn đường. "
                "Nêu rõ đây là ước tính, không phải số xe quan sát."
            ),
            "assumptions": {"serviceMinutesPerVehicle": 1, "normalSlots": 2, "peakSlots": 4},
            "options": context,
        }, headers, timeout=3)
        summary = result.get("summary")
        return summary[:280] if isinstance(summary, str) else None
    except (OSError, ValueError, AttributeError):
        return None


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/chat":
            self.chat()
            return
        if self.path != "/api/stations":
            self.send_error(404)
            return
        key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not key:
            self.reply(503, {"error": "Chưa cấu hình GOOGLE_MAPS_API_KEY trên máy chủ."})
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 1024:
                raise ValueError()
            data = json.loads(self.rfile.read(size))
            lat, lon = float(data["lat"]), float(data["lon"])
            if not (math.isfinite(lat) and math.isfinite(lon)
                    and abs(lat) <= 90 and abs(lon) <= 180):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            self.reply(400, {"error": "Vị trí xuất phát không hợp lệ."})
            return
        try:
            stations = find_stations({"latitude": lat, "longitude": lon}, key)
        except (OSError, ValueError, KeyError, TypeError):
            self.reply(502, {"error": "Chưa lấy được dữ liệu Google Maps. Kiểm tra Places API, Routes API và khóa."})
            return
        display = [dict(station) for station in
                   rank_stations([station for station in stations if station["travelMinutes"] is not None])[:3]]
        here_key = os.getenv("HERE_TRAFFIC_API_KEY")
        for station in display:
            if here_key:
                try:
                    estimate = local_traffic_estimate(fetch_adjacent_traffic(station, here_key))
                except (OSError, ValueError, KeyError, TypeError):
                    estimate = local_traffic_estimate({})
            else:
                estimate = local_traffic_estimate({})
            station["trafficDensityIndexPercent"] = estimate["densityIndexPercent"]
            station["trafficJamFactor"] = estimate["jamFactor"]
            station["trafficSampleCount"] = estimate["sampleCount"]
            station["trafficQueueScaleVehicles"] = estimate["queueScaleVehicles"]
            station["trafficEstimateConfidence"] = estimate["confidence"]
            station["trafficRoads"] = estimate["roads"]
            station["trafficSourceUpdated"] = estimate["sourceUpdated"]
            station["queueCount"] = estimate["estimatedQueueCount"]
            station["queueSource"] = estimate["source"]
            if station["queueCount"] is not None and station["serviceSlots"]:
                wait = station["queueCount"] / station["serviceSlots"]
                station["waitMinutes"] = round(wait, 1)
                station["totalMinutes"] = round(station["travelMinutes"] + wait + station["serviceMinutes"], 1)
                count = station["queueCount"]
                station["crowd"] = "Vắng" if count < 10 else "Vừa" if count <= 20 else "Đông"
            else:
                station["waitMinutes"] = None
                station["totalMinutes"] = None
                station["crowd"] = None
        display = rank_stations(display)
        self.reply(200, {"stations": display, "candidates": stations, "summary": summarize(display),
                         "trafficProvider": "HERE" if here_key else None,
                         "trafficConfigRequired": not bool(here_key)})

    def chat(self):
        endpoint = os.getenv("FUEL_AGENT_URL")
        if not endpoint:
            self.reply(503, {"error": "Chưa cấu hình agent."})
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 16000:
                raise ValueError()
            data = json.loads(self.rfile.read(size))
            question = data["question"]
            stations = data["stations"]
            if not isinstance(question, str) or not 0 < len(question) <= 500:
                raise ValueError()
            if not isinstance(stations, list) or not 1 <= len(stations) <= 3:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            self.reply(400, {"error": "Câu hỏi hoặc dữ liệu cây xăng không hợp lệ."})
            return
        token = os.getenv("FUEL_AGENT_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            result = post(endpoint, {
                "instruction": (
                    "Trả lời ngắn bằng tiếng Việt dựa trên kết quả từng cây xăng. "
                    "null là chưa rõ. Chỉ so sánh tổng thời gian khi mọi cây có tổng. "
                    "Phân biệt thời gian đi với hàng chờ giả định. Không tự tạo số liệu. "
                    "Trả JSON với trường answer hoặc summary."
                ),
                "question": question,
                "options": stations,
            }, headers, timeout=6)
            answer = result.get("answer") or result.get("summary")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError()
        except (OSError, ValueError, AttributeError):
            self.reply(502, {"error": "Agent chưa trả lời được."})
            return
        self.reply(200, {"answer": answer[:1500]})

    def reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    handler = partial(Handler, directory=Path(__file__).resolve().parent / "dist")
    print("http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), handler).serve_forever()
