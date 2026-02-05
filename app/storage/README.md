# Storage Module - Lưu trữ và Cấu trúc dữ liệu

Module này quản lý việc kết nối cơ sở dữ liệu MongoDB và định nghĩa các khuôn mẫu dữ liệu (Schemas).

## 1. Thành phần chính
- `db.py`: Quản lý kết nối (Connection) và khởi tạo Collection.
- `schemas.py`: Định nghĩa các Pydantic Models để kiểm tra tính hợp lệ của dữ liệu.

## 2. Cơ sở dữ liệu (MongoDB)
Hệ thống sử dụng **Motor** (Async Python driver cho MongoDB) để đảm bảo hiệu năng bất đồng bộ cao.
Chia làm 2 database chính:
1.  **`masterdata`**: Lưu trữ các thông tin cấu hình ít thay đổi (Danh mục máy, sản phẩm, ca, thông số kỹ thuật).
2.  **`production`**: Lưu trữ dữ liệu phát sinh theo thời gian thực (IoT logs, Lỗi, Bản ghi sản xuất, KPI).

### Các Collection quan trọng trong `production`:
- `iot_records`: Lưu tín hiệu từ cảm biến và thời gian chu kỳ (cycle time).
- `defect_records`: Lưu thông tin sản phẩm lỗi từ AI Camera hoặc HMI.
- `production_records`: Lưu thông tin chi tiết từng lượt sản xuất (OEE, sản lượng, trạng thái máy).
- `shift_stats`: Tổng hợp KPI theo từng ca làm việc.
- `downtime_records`: Lưu vết các khoảng thời gian máy dừng.

## 3. Schemas (Pydantic Models)
Hệ thống sử dụng Pydantic v2 để định nghĩa các mô hình dữ liệu:
- **`ProductionRecord`**: Model chính chứa thông tin `machinecode`, `productcode`, `kpis` và `stats`. Bao gồm cả dữ liệu mở rộng như `good_product`, `productname`, `machinename`.
- **`ShiftSummary`**: Model dùng để lưu trữ dữ liệu tổng hợp ca.
- **`IoTRecord` / `DowntimeRecord`**: Các mô hình cho dữ liệu sự kiện.

## 4. Tự động khởi tạo
Hàm `ensure_timeseries()` trong `db.py` được gọi khi hệ thống khởi động để đảm bảo các Collection cần thiết đã tồn tại trong Database.
