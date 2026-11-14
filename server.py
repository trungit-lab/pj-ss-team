import json
import math
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from station_evaluation import find_stations, post


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
           ("travelMinutes", "speedKmh", "delayMinutes", "queueCount", "crowd", "waitMinutes", "totalMinutes")},
    } for index, station in enumerate(stations, 1)]
    try:
        result = post(endpoint, {
            "instruction": (
                "Tóm tắt tối đa một câu tiếng Việt về các lựa chọn đã xếp hạng. "
                "Giữ nguyên số liệu. null là chưa biết. Ùn tắc đường không cho biết "
                "hàng chờ cây xăng. Không dự đoán số xe hoặc phút chờ khi thiếu dữ liệu."
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
        display = rank_stations([station for station in stations if station["travelMinutes"] is not None])[:3]
        self.reply(200, {"stations": display, "candidates": stations, "summary": summarize(display)})

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
