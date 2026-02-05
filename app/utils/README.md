# Utils Module - Các công cụ tiện ích

Module này chứa các hàm bổ trợ dùng chung cho toàn hệ thống.

## 1. Thành phần chính
- `messaging.py`: Tiện ích làm cầu nối gửi tin nhắn MQTT từ bất kỳ đâu trong ứng dụng.

## 2. MQTT Messaging Utility
Module này giải quyết bài toán gửi message MQTT từ các module logic mà không cần phải khởi tạo lại kết nối MQTT hay giữ tham chiếu trực tiếp đến các MQTT Services.

- **`set_mqtt_publish_func(func)`**: Được gọi một lần duy nhất trong `main.py` khi khởi động để đăng ký hàm publish của `ProductionRecordService` vào biến global.
- **`mqtt_publish(topic, data)`**: Hàm tiện ích có thể gọi ở bất cứ đâu (`logic.py`, `processor.py`) để gửi dữ liệu đi. Nếu hàm publish chưa được đăng ký, nó sẽ in ra cảnh báo thay vì gây lỗi ứng dụng.
