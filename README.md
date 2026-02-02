# Production Record Management System

Hệ thống quản lý bản ghi sản xuất (Production Record) tự động tính toán hiệu suất (OEE), theo dõi sản lượng và lỗi trong thời gian thực tại Edge.

## 1. Quy tắc sinh mã (Record ID)
Mỗi bản ghi được định danh duy nhất theo cấu trúc:
`{Mã_Sản_Phẩm}-{Ngày}-{Tháng}-{Năm}-{Mã_Máy}-{STT}`

*   **Ví dụ:** `pd001-02-02-2026-MC01-1`
*   **STT:** Tự động tăng nếu trong cùng một ngày, trên cùng một máy có nhiều lượt sản xuất cùng một mã hàng (VD: sau khi đổi mã hàng rồi quay lại mã cũ).

## 2. Vòng đời và Trạng thái (Status)
Bản ghi có hai trạng thái chính:

### `running` (Đang hoạt động)
*   **Khởi tạo:** Khi bắt đầu ca làm việc hoặc ngay sau khi có sự kiện đổi mã hàng (Changeover).
*   **Mục đích:** Đánh dấu mốc thời gian bắt đầu (`createtime`) để hệ thống biết phạm vi thu thập dữ liệu IoT.
*   **Dữ liệu:** Các chỉ số sản lượng và OEE lúc này bằng 0.

### `closed` (Đã đóng)
*   **Kích hoạt:** Khi nhận tín hiệu Changeover từ HMI (mã hàng cũ bị thay thế bởi mã mới).
*   **Hành động hệ thống:**
    1.  Tìm bản ghi đang `running` của máy đó.
    2.  Tổng hợp `total_count` từ cảm biến (IoT records).
    3.  Tổng hợp `defect_count` từ AI Camera và HMI.
    4.  Truy vấn `idealcyclesec` từ bảng `workingparameter`.
    5.  Tính toán các chỉ số OEE (Availability, Performance, Quality).
    6.  Cập nhật trạng thái thành `closed`.

## 3. Quản lý Ca làm việc (Shift)
Hệ thống tự động nhận diện ca dựa trên giờ hệ thống và dữ liệu trong bảng `shift`:
*   **Đơn vị:** Thời gian bắt đầu/kết thúc ca lưu bằng **giây** tính từ 00:00 (VD: 7h sáng = 25200s).
*   **Xử lý ca đêm:** Hệ thống tự động nhận diện nếu ca kéo dài qua ngày hôm sau (VD: 22h - 06h).
*   **Thông tin lưu trữ:** Mỗi bản ghi sẽ chứa `shiftcode`, `startshift` và `endshift` tương ứng tại thời điểm phát sinh.

## 4. Master Data phụ thuộc
Để Production Record hoạt động chính xác, các bảng sau cần có dữ liệu:
*   `shift`: Chứa cấu hình thời gian các ca.
*   `workingparameter`: Chứa `idealcyclesec` (giây/sản phẩm) của từng mã hàng.
*   `product`: Chứa thông tin mã hàng và sản lượng dự kiến (`plannedqty`).

## 5. Luồng xử lý kỹ thuật (Logic.py)
1.  **Chốt bản ghi:** `create_production_record_on_changeover` thực hiện "Flush" dữ liệu từ memory/logs xuống DB và đóng record.
2.  **Mở bản ghi:** `initialize_production_record` chuẩn bị vùng chứa dữ liệu cho lượt sản xuất tiếp theo.
3.  **Nhận diện ca:** `get_current_shift` trả về thông tin ca hiện tại theo thời gian thực.
