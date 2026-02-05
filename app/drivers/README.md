# Drivers Module - Tầng kết nối phần cứng và mạng

Module này chứa các trình điều khiển (drivers) để tương tác với thiết bị ngoại vi và các giao thức mạng.

## 1. Thành phần chính
- `camera.py`: Trình điều khiển AI Camera.
- `mqtt.py`: Tập hợp các dịch vụ MQTT để nhận và gửi dữ liệu.

## 2. Chi tiết các Driver

### AI Camera Driver (`camera.py`)
Sử dụng thư viện **OpenCV** để kết nối luồng RTSP và **Ultralytics YOLO** để nhận diện đối tượng.
- **Cơ chế đọc luồng**: Chạy một luồng (thread) riêng biệt (`_camera_reader`) để liên tục lấy frame mới nhất từ Camera, tránh độ trễ tích tụ (buffer delay).
- **Hàm `capture_and_detect()`**: 
    - Lấy frame mới nhất.
    - Thực hiện AI Inference để đếm sản phẩm và phát hiện sản phẩm lỗi (dựa trên class name có chứa từ "ng" hoặc "defect").
    - Trả về số lượng, số lỗi và ảnh đã được vẽ khung nhận diện (annotated image).

### MQTT Services (`mqtt.py`)
Sử dụng thư viện **Paho MQTT**. Cấu trúc theo dạng thừa kế từ `BaseMQTTService`:
- **`CounterService`**: Subscribe topic `topic/sensor/counter` để nhận tín hiệu sản lượng từ cảm biến IoT.
- **`HMIDefectService`**: Subscribe topic `topic/defect/hmi` để nhận báo lỗi thủ công từ người vận hành.
- **`HMIChangeoverService`**: Subscribe topic `topic/changover/hmi` để nhận lệnh đổi mã sản phẩm.
- **`HMIDowntimeService`**: Subscribe topic `topic/downtimeinput` để nhận giải trình nguyên nhân dừng máy.
- **`DefectMasterService`**: Xử lý các yêu cầu lấy danh sách danh mục lỗi.
- **`ProductMasterService`**: Xử lý yêu cầu lấy danh mục sản phẩm phục vụ quá trình Changeover.
- **`ProductionRecordService`**: Chuyên trách việc Publish thông tin KPI/OEE lên topic `topic/get/productionrecord`.

## 3. Cách thức hoạt động
Các service được khởi tạo trong `main.py` và gán các hàm callback tương ứng. Khi có message đến, `BaseMQTTService` sẽ parse dữ liệu JSON và đẩy vào callback để `processor.py` xử lý.

## 4. Cấu trúc Payload chuẩn (Mandatory)

Để hệ thống hoạt động chính xác, các các Node gửi dữ liệu lên MQTT **BẮT BUỘC** phải tuân thủ cấu trúc sau:

### Tín hiệu Counter (`topic/sensor/counter`)
```json
{
    "machinecode": "m002",
    "timestamp": "2026-02-05T03:53:30Z",
    "shootcountnumber": 1439
}
```

### Báo lỗi từ HMI (`topic/defect/hmi`)
```json
{
  "machinecode": "m002",
  "defectcode": "d5"
}
```

### Lệnh Changeover (`topic/changover/hmi`)
```json
{
    "machinecode": "m002",
    "product": "pd002",
    "oldproduct": "pd001"
}
```

### Giải trình Downtime (`topic/downtimeinput`)
*Ghi chú: Status phải khác "active" hoặc "closed" để hệ thống nhận diện đây là lệnh cập nhật lý do.*
```json
{
    "id": "65b...",
    "machinecode": "m002",
    "downtimecode": "dt01"
}
```

### Yêu cầu danh mục sản phẩm (`topic/get/productcode`)
```json
{
    "machinecode": "m002",
    "getproduct": "changover"
}
```
