# Tasks Module - Các tác vụ chạy ngầm

Module này được thiết kế để chứa các logic tác vụ chạy ngầm (Background Tasks). 

*Lưu ý: Hiện tại các tác vụ chính đang được định nghĩa trực tiếp trong `main.py` để dễ dàng quản lý vòng đời khởi động, nhưng định hướng sẽ được tách dần ra module này.*

## Các tác vụ hiện tại trong hệ thống:

1.  **`auto_record_ensurer_task`**: 
    - Chạy định kỳ mỗi 5 phút.
    - Kiểm tra xem tất cả các máy trong danh mục đã có bản ghi sản xuất (Production Record) cho ca hiện tại chưa. 
    - Nếu chưa có (ví dụ: do mất điện khởi động lại giữa ca), nó sẽ tự động tạo bản ghi mới để không làm gián đoạn việc thu thập dữ liệu.

2.  **`production_record_publisher_task`**: 
    - Chạy định kỳ mỗi 1 giây.
    - Tính toán lại KPI/OEE cho tất cả các máy đang sản xuất (`status: running`).
    - Publish dữ liệu tổng hợp ca (`shiftstat`) lên MQTT để các thiết bị giám sát (HMI, Web Dashboard) cập nhật giao diện.

3.  **`main_monitor_task`**: 
    - Giám sát việc đổi ca làm việc. Khi phát hiện giờ hệ thống bước sang ca mới, nó sẽ tự động chốt toàn bộ bản ghi ca cũ và mở bản ghi ca mới cho tất cả các máy.
    - Tự động kiểm tra và chốt các khoảng dừng (Downtime) quá hạn.
