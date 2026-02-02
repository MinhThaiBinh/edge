# Edge AIoT - Production Record Management System

Hệ thống Backend chuyên dụng cho Edge AIoT, tự động quản lý bản ghi sản xuất (Production Record), tính toán chỉ số OEE, theo dõi sản lượng và phát hiện lỗi bằng AI Camera trong thời gian thực.

## 1. Cấu trúc Dự án (Edge Refactored)

Hệ thống được thiết kế theo cấu trúc Modular chuyên biệt cho Edge Backend:

```text
fast_api_edge/
├── app/
│   ├── main.py            # Entry point: Quản lý Lifecycle & Startup Workers
│   ├── config.py          # Cấu hình tập trung (MQTT, Camera, DB, Thresholds)
│   ├── drivers/           # Tầng thiết bị (Hardware: Camera AI, MQTT Clients)
│   ├── engine/            # Bộ não xử lý (Signal Processing & OEE Logic)
│   ├── storage/           # Lưu trữ (MongoDB Connection & Schemas)
│   └── tasks/             # Các tác vụ chạy ngầm (Shift Monitor)
├── run.py                 # Script khởi động nhanh hệ thống
├── weights/               # Chứa các Model YOLO (.pt)
└── .gitignore             # Cấu hình bỏ qua các file rác và model nặng
```

## 2. Quy tắc sinh mã (Record ID)

Mỗi lượt sản xuất trên một máy được định danh duy nhất (Unique ID):
`{Mã_Sản_Phẩm}-{Ngày}-{Tháng}-{Năm}-{Mã_Máy}-{STT}`

*   **Ví dụ:** `pd001-02-02-2026-m002-1`
*   **STT:** Tự động tăng nếu trong ngày có nhiều lượt sản xuất cùng một mã hàng trên cùng một máy (sau khi Changeover).

## 3. Quy trình Xử lý Dữ liệu

### Trạng thái `running` (Đang hoạt động)
*   **Khởi tạo:** Khi bắt đầu ca hoặc ngay khi HMI gửi tín hiệu Changeover.
*   **Nhiệm vụ:** Đánh dấu mốc thời gian `createtime` để hệ thống lọc dữ liệu IoT và Defect tương ứng.

### Trạng thái `closed` (Đã đóng)
*   **Kích hoạt:** Khi mã hàng cũ bị thay thế bởi mã hàng mới.
*   **Hành động hệ thống khi chốt bản ghi:**
    1. Tổng hợp `total_count` từ cảm biến (IoT records).
    2. Tổng hợp `defect_count` từ AI Camera và ghi nhận từ HMI.
    3. Truy vấn `idealcyclesec` từ bảng Master `workingparameter`.
    4. Tính toán **OEE** bao gồm:
        - **Availability (A):** Tỷ lệ thời gian chạy.
        - **Performance (P):** Hiệu suất theo chu kỳ lý tưởng.
        - **Quality (Q):** Tỷ lệ sản phẩm đạt chất lượng.
    5. Cập nhật `status = "closed"`.

## 4. Quản lý Ca và Giờ nghỉ (Shift & Break)

Hệ thống tự động đồng bộ theo thời gian thực:
*   **Nhận diện ca:** Tự động dựa trên giờ Server (đã hỗ trợ cả ca ngày và ca đêm vắt ngày).
*   **Giờ nghỉ (Break Time):** Tự động nạp thông tin `breakstart` và `breakend` từ Master Data vào bản ghi sản xuất để phục vụ tính toán thời gian chạy thực tế (Net Run Time) trong tương lai.

## 5. Hướng dẫn sử dụng

### Cài đặt môi trường
1. Tạo môi trường ảo: `python3 -m venv venv`
2. Kích hoạt: `source venv/bin/activate`
3. Cài đặt thư viện: `pip install -r requirements.txt`

### Cấu hình
Mọi thông số kỹ thuật được quản lý tại `app/config.py`:
- `RTSP_URL`: Địa chỉ luồng Camera.
- `MQTT_HOST`: Địa chỉ Broker (Counter, HMI).
- `MONGODB_URL`: Kết nối cơ sở dữ liệu.
- `THRESHOLD`: Ngưỡng AI để xác định hàng lỗi.

### Khởi động hệ thống
Để khởi động hệ thống với chế độ tự động tải lại (Reload):
```bash
python3 run.py
```

## 6. Thành phần Master Data cần thiết
Để hệ thống vận hành chính xác, Database `masterdata` cần đảm bảo:
*   **shift**: Chứa `shiftcode`, `shiftstarttime`, `shiftendtime`, `breaktime`.
*   **workingparameter**: Chứa `productcode` và `idealcyclesec`.
*   **product**: Chứa `productcode` và `plannedqty`.
