# Thuật toán ước lượng mức đông cây xăng

## Mục tiêu

Xếp hạng tối đa 3 cây xăng gần điểm xuất phát theo tổng thời gian dự kiến. Mật độ đường chỉ là tín hiệu gián tiếp; hệ thống không quan sát trực tiếp số xe đang xếp hàng tại cây xăng.

## Luồng xử lý

```text
Vị trí xuất phát
  -> Google Places Nearby Search: tìm cây xăng trong 3 km
  -> Google Routes Compute Route Matrix: ETA và khoảng cách đến từng cây
  -> Chọn tối đa 3 cây theo ETA
  -> HERE Traffic Flow: lấy các đoạn đường trong vùng 500 m quanh từng cây
  -> Chọn tối đa 6 đoạn có hình học gần cây xăng nhất
  -> Tính chỉ số ùn tắc tổng hợp và quy đổi heuristic thành số xe chờ
  -> Tính thời gian chờ và tổng thời gian
  -> Gửi dữ liệu có nguồn, thời điểm và độ tin cậy cho agent so sánh
```

## API và dữ liệu

### 1. Google Places API

- **Input:** tọa độ xuất phát; bán kính tìm kiếm 3 km; loại `gas_station`.
- **Output dùng:** `place.id`, tên, địa chỉ, tọa độ, trạng thái hoạt động.
- Loại trạm đã đóng hoặc tạm đóng.

### 2. Google Routes API — Compute Route Matrix

- **Input:** tọa độ xuất phát; Place ID các cây xăng; `TWO_WHEELER`; `TRAFFIC_AWARE`.
- **Output dùng:** `duration`, `staticDuration`, `distanceMeters`, `condition`, `status`.
- `duration` dùng làm ETA hiện tại. `staticDuration` chỉ là thời gian tham chiếu mà API trả về, không phải dữ liệu lịch sử do ứng dụng tự thu thập.
- Tốc độ tuyến suy ra: `distanceMeters / durationSeconds × 3.6` (km/h).
- Độ trễ suy ra: `max(0, durationSeconds − staticDurationSeconds) / 60` (phút).

### 3. HERE Traffic Flow API v7

- **Endpoint:** `GET https://data.traffic.hereapi.com/v7/flow`
- **Input:** `in=circle:{lat},{lon};r=500`, `locationReferencing=shape`, API key.
- **Output dùng:** `results[].location.description`, `results[].location.shape`, `results[].currentFlow.speed`, `freeFlow`, `jamFactor`, `traversability`, `sourceUpdated`.
- Chỉ giữ tối đa 6 đoạn đường có hình học nằm gần tọa độ cây xăng nhất. Nếu có dưới 4 đoạn hợp lệ, không tính hàng chờ và trả trạng thái chưa đủ dữ liệu.
- Jam factor 0–10 biểu thị mức ùn tắc của **đoạn đường**; nó không phải lưu lượng xe/giờ hay số xe tại cây xăng.

## Công thức nội bộ

Với mỗi đoạn đường `i` có `jamFactor_i` hợp lệ trong `[0, 10]`:

```text
jamFactorTrungBinh = sum(jamFactor_i) / số đoạn hợp lệ
chiSoUnTacPercent = jamFactorTrungBinh × 10
sốXeChờƯớcTính = ceil(40 × chiSoUnTacPercent / 100)
```

`40 xe` là hệ số heuristic hiện cấu hình trong code (`LOCAL_QUEUE_SCALE_VEHICLES`), **không phải thông số đo đạc hoặc công thức giao thông đã hiệu chuẩn**. Cần thay bằng hệ số hiệu chỉnh từ dữ liệu quan sát cây xăng nếu muốn số chờ có ý nghĩa thực tế. `jamFactor` không được giả định là tỷ lệ tuyến tính của mật độ; phép quy đổi trên chỉ tạo một chỉ số tương đối để agent dùng làm context.

Thời điểm đến dự kiến là giờ hiện tại cộng ETA. Khung giờ cao điểm đang giả định 07:00–09:00 và 16:00–19:00, giờ địa phương Hà Nội.

```text
xePhụcVụSongSong = 4 nếu giờ cao điểm, ngược lại 2
thờiGianChờPhút = sốXeChờƯớcTính / xePhụcVụSongSong
tổngThờiGianPhút = ETA_phút + thờiGianChờPhút + 1
```

Giả định phục vụ cố định: 1 phút/xe; 2 xe đồng thời giờ thường; 4 xe đồng thời giờ cao điểm. Đây là giả định sản phẩm do người phát triển cung cấp, không lấy từ API.

## Output cho agent

Mỗi cây xăng nên gửi các trường:

```json
{
  "name": "Tên cây xăng",
  "address": "Địa chỉ",
  "travelMinutes": 5.2,
  "distanceMeters": 1800,
  "speedKmh": 20.4,
  "delayMinutes": 1.1,
  "arrivalAt": "2026-11-14T16:10:00+07:00",
  "peak": true,
  "serviceSlots": 4,
  "trafficProvider": "HERE Traffic API",
  "trafficJamFactor": 4.2,
  "trafficDensityIndexPercent": 42,
  "trafficSampleCount": 5,
  "trafficRoads": [
    {"roadName": "Tên đoạn đường", "jamFactor": 4.2, "speed": 5.1, "freeFlow": 8.0}
  ],
  "trafficSourceUpdated": "2026-11-14T09:00:00Z",
  "queueCount": 17,
  "queueSource": "HERE Traffic API",
  "trafficEstimateConfidence": "low",
  "waitMinutes": 4.3,
  "totalMinutes": 10.5
}
```

Giá trị JSON trên chỉ là **ví dụ cấu trúc**, không phải kết quả API thực tế. Khi thiếu dữ liệu hoặc thiếu key, các giá trị giao thông/hàng chờ phải để `null`; agent không tự điền số. Agent được xếp hạng và giải thích các lựa chọn, không thay đổi dữ liệu đầu vào.

## Giới hạn và kiểm chứng

- API giao thông phản ánh tốc độ/ùn tắc trên đường, không đo xe đang chờ tại trạm.
- Đoạn đường HERE tìm trong vùng bán kính không đảm bảo tất cả đều là lối vào trực tiếp của trạm. Cần kiểm tra hình học và hướng đường nếu dùng để kết luận tuyến tiếp cận.
- Không có HERE API key thì không có dữ liệu giao thông live; không thay bằng dữ liệu demo.
- Muốn hiệu chỉnh số xe chờ, cần thu thập nhãn thực tế: thời điểm quan sát, số xe xếp hàng, số vòi/xe phục vụ song song và thời gian phục vụ tại từng trạm.
- Đây là thuật toán dự toán tham khảo; không dùng để khẳng định mật độ xe chính xác.
