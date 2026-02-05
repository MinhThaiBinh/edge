# Engine Module - Bộ não xử lý hệ thống

Module này chịu trách nhiệm xử lý logic nghiệp vụ chính, tính toán các chỉ số OEE và điều phối luồng dữ liệu từ các cảm biến/AI Camera.

## 1. Thành phần chính
- `logic.py`: Chứa các hàm tính toán OEE, quản lý ca làm việc (Shift) và vòng đời của bản ghi sản xuất (Production Record).
- `processor.py`: Tiếp nhận dữ liệu thô từ các Driver (MQTT, Camera), xử lý và gọi các hàm logic để cập nhật cơ sở dữ liệu.

## 2. Nguyên lý hoạt động các hàm trong `logic.py`

### Quản lý Bản ghi Sản xuất (Production Record)
*   **`initialize_production_record(machinecode, productcode)`**: 
    - Khởi tạo một bản ghi mới với trạng thái `running`.
    - Tra cứu `productname` và `machinename` từ database master để lưu vào bản ghi, giúp đồng bộ thông tin hiển thị.
    - Sinh mã ID duy nhất theo format: `{productcode}-{DD-MM-YYYY}-{machinecode}-{STT}`.
*   **`finalize_production_record_on_shift_change(...)`**: 
    - Chốt bản ghi cũ khi phát hiện đổi ca hoặc đổi sản phẩm. 
    - Tính toán các chỉ số cuối cùng trước khi chuyển sang trạng thái `closed`.
*   **`update_current_production_stats(machinecode)`**:
    - Được gọi liên tục để cập nhật sản lượng (`total_count`, `defect_count`, `good_product`) và tính toán OEE thời gian thực cho bản ghi đang chạy.

### Tính toán OEE & Chỉ số KPI
Hệ thống tính toán OEE dựa trên 3 thành phần chính:
1.  **Availability (A) - Tính khả dụng**: 
    - `actual_run_seconds / run_seconds`.
    - `actual_run_seconds` được tính bằng tổng thời gian của bản ghi (`run_seconds`) trừ đi thời gian dừng (`downtime_seconds`). 
    - **Lưu ý**: `downtime_seconds` được giới hạn chỉ tính trong phạm vi thời gian của bản ghi hiện tại (nếu máy dừng trước khi bản ghi bắt đầu, phần thời gian dừng trước đó sẽ bị loại bỏ).
2.  **Performance (P) - Hiệu suất**: 
    - `(idealcyclesec * total_count) / actual_run_seconds`.
    - So sánh thời gian thực hiện thực tế với thời gian lý tưởng cấu hình trong `workingparameter`.
3.  **Quality (Q) - Chất lượng**: 
    - `(total_count - defect_count) / total_count`.
    - Tỷ lệ sản phẩm đạt chuẩn trên tổng sản phẩm cảm biến ghi nhận.
    - `good_product = total_count - defect_count`.

### Vận tốc trung bình (Average Cycle Time)
- **Cấp độ bản ghi**: `actual_run_seconds / total_count`.
- **Cấp độ ca (Shift)**: Được tính bằng `Tổng actual_run_seconds của ca / Tổng total_count của ca`. Cách tính này đảm bảo chỉ số vận tốc trung bình không bị kéo tụt khi máy đang dừng.

### Quản lý Ca và Giờ nghỉ (Shift & Break)
*   **`get_current_shift()`**: 
    - Xác định ca hiện tại dựa trên giờ hệ thống và cấu hình trong bảng `shift` (Master data).
    - Tự động xử lý các ca làm việc xuyên đêm (vắt ngày).
*   **`get_current_shift_stats(machinecode)`**: 
    - Tổng hợp toàn bộ các bản ghi sản xuất trong ca hiện tại của một máy để đưa ra KPI tổng của ca đó.

### Giám sát Downtime
*   **`check_and_create_downtime()`**: 
    - Tự động phát hiện máy dừng nếu quá một khoảng thời gian (`downtimethreshold`) mà không nhận được tín hiệu Counter mới.
*   **`close_active_downtime(machinecode)`**: 
    - Tự động đóng thời gian dừng khi máy bắt đầu có tín hiệu chạy lại.

## 3. Quy trình Xử lý Sự kiện trong `processor.py`
- **`process_and_save_counter`**: Khi có tín hiệu Counter từ MQTT -> Lưu IoT record -> Kích hoạt AI Camera -> Cập nhật OEE.
- **`process_and_save_defect`**: Nhận kết quả từ AI Camera -> Phân loại lỗi (d1: thiếu số lượng, d3: lỗi sản phẩm) -> Lưu vào `defect_records`.
- **`process_hmi_changeover`**: Xử lý lệnh đổi mã hàng từ màn hình HMI. Chốt bản ghi cũ và khởi tạo bản ghi mới ngay lập tức.

## 4. Quy định về cấu trúc dữ liệu đầu vào (Input Payload)

Tất cả các hàm xử lý trong `processor.py` đã được chuẩn hóa để sử dụng key duy nhất cho máy là `machinecode`.

| Chức năng | Topic | Trường dữ liệu bắt buộc |
| :--- | :--- | :--- |
| **Counter** | `topic/sensor/counter` | `machinecode`, `shootcountnumber` |
| **HMI Defect** | `topic/defect/hmi` | `machinecode`, `defectcode` |
| **Changeover** | `topic/changover/hmi` | `machinecode`, `product` |
| **Downtime Reason** | `topic/downtimeinput` | `machinecode`, `downtimecode`, `id` (ObjectId) |
| **Product Master Req**| `topic/get/productcode`| `machinecode`, `getproduct` ("changover") |

*Lưu ý: Nếu dữ liệu đầu vào không đúng cấu trúc (thiếu `machinecode`, sai tên trường), hệ thống sẽ bỏ qua và in thông báo lỗi vào log.*
