# Rà soát và sửa giao diện Amazon Movies & TV

> **Tài liệu lịch sử.** Bản rà soát này áp dụng cho giao diện ban đầu (modal, 6 tab). Giao diện đã được làm lại ở buổi 6 và tách khu người dùng / khu quản trị ngày 14/11; xem `docs/TIEN_DO_BUOI_5.md` và `docs/SUA_LOI_2026-11-14.md`. Các tệp `ui_audit_*` của giao diện cũ đã bỏ khi dọn thư mục ngày 14/11.

Cập nhật: **11/11/2026 11:53 — giờ Việt Nam**. Bản chạy được rà soát: **D:\AmazonMoviesTV\project**, địa chỉ **http://127.0.0.1:5055**.

## Kết luận

Đã sửa lỗi làm toàn bộ giao diện dừng hoạt động và kiểm tra lại 6 màn hình bằng trình duyệt. Bộ kiểm thử hiện tại: **18/18 đạt**, không có lỗi JavaScript mới trong lượt kiểm tra. MongoDB và Neo4j đều trả trạng thái **ok**.

## Lỗi đã tìm thấy và xử lý

| Mức độ | Lỗi | Cách xử lý |
|---|---|---|
| Nghiêm trọng | app.js có dấu backtick không được xử lý bên trong chuỗi HTML mẫu, tại ba chỗ: ALSO_BOUGHT/ALSO_VIEWED, summary và reviewText. Trình duyệt báo Unexpected identifier và dừng toàn bộ file. | Sửa các chuỗi nhãn; kiểm tra cú pháp toàn bộ JavaScript; thêm kiểm thử frontend vào pytest. |
| Chức năng | Nút sửa review chèn trực tiếp nội dung vào lệnh onclick. Review tiếng Anh có dấu nháy, dấu ngoặc kép hoặc xuống dòng có thể làm hỏng nút và tạo rủi ro chèn mã vào handler. | Mã hóa riêng chuỗi JavaScript bằng JSON.stringify và thuộc tính HTML; kiểm thử nội dung có dấu nháy/xuống dòng. |
| Hiển thị | Ngày bị cắt thành dạng Sun, 01 Ma, mất tháng đầy đủ và năm. | Định dạng thành DD/MM/YYYY; đã thấy 01/10/2018 trên giao diện thật. |
| Chức năng | Phản hồi tìm kiếm/gợi ý/đồ thị về không đúng thứ tự có thể ghi đè lựa chọn mới. Bộ lọc cộng đồng còn kích hoạt truy vấn mặc định thừa. | Chỉ hiển thị phản hồi của yêu cầu mới nhất; bỏ tải lặp; xóa bộ lọc cũ khi chọn cộng đồng. |
| Điều hướng | Chuyển tab giữ vị trí cuộn cũ; phân trang vẫn cho đi tiếp khi không có kết quả; đổi đồ thị tạo đối tượng mới mà không dọn đối tượng cũ. | Đưa tab mới về đầu trang, khóa nút phân trang tương ứng, dọn đồ thị cũ trước khi tạo mới; Esc đóng hộp chi tiết/đăng nhập. |
| Hiệu năng | Danh sách review mặc định phải quét và sắp xếp hơn 3 triệu bản ghi. | Thêm review_recent_global trên timestamp giảm dần + _id; tổng không lọc dùng metadata collection, tổng có bộ lọc vẫn đếm chính xác. |
| Độ bền giao diện | Dữ liệu phiên đăng nhập lưu trong trình duyệt không hợp lệ có thể làm lỗi lúc mở trang. | Đọc phiên đăng nhập có kiểm tra và xử lý lỗi; có kiểm thử hồi quy. |

Bản sao lưu trước khi sửa: **D:\AmazonMoviesTV\backups\before-ui-audit-20261111-113438.zip**. Báo cáo buổi 5 cũ có thời gian ghi file trước lần chỉnh app.js gần nhất; kết quả kiểm tra cũ không xác nhận được bản giao diện đã sửa sau đó. Bản mã nguồn trên ổ D đã có thêm phần buổi 4–5, vì vậy không khôi phục đè bằng bản buổi 1–3 cũ trong chat.

## Kết quả kiểm tra bằng trình duyệt

| Màn hình / thao tác | Kết quả |
|---|---|
| Trang chủ | Hiển thị 24 thẻ phim và 6 cộng đồng, hai trạng thái CSDL ok. |
| Tìm kiếm sản phẩm | Trả danh sách phim; trường hợp không có kết quả khóa cả hai nút phân trang. |
| Tìm review | Hiển thị review và ngày đầy đủ; danh sách mới nhất tải được bằng chỉ mục. |
| Chi tiết phim | Có thông tin, biểu mẫu và review; Esc đóng hộp thoại. |
| Đăng nhập | Mở đúng biểu mẫu; Esc đóng hộp thoại. Không tạo tài khoản thật trong lần rà soát trình duyệt. |
| Gợi ý cá nhân | Hybrid và Popular đều hiển thị 10 phim; đổi nhanh thuật toán không bị kết quả cũ ghi đè. |
| Đồ thị | Vẽ được đồ thị người dùng mẫu: 23 nút, 33 cạnh. |
| Thống kê | Biểu đồ và các tổng số hiển thị. |
| Thực nghiệm | Hiển thị 20 dòng bảng và 4 biểu đồ. Chỉ kiểm tra việc hiển thị, không thẩm định lại phương pháp hay số liệu buổi 4 trong lần sửa giao diện này. |

## Kiểm tra tốc độ danh sách review

- Trước: **6.7356 giây**, kế hoạch COLLSCAN + SORT.
- Sau khi thêm chỉ mục: **2.9850 giây**.
- Sau khi tối ưu tổng số không lọc: **0.0168 giây**, kế hoạch IXSCAN + FETCH + LIMIT.
- Mỗi lần lấy 15 review; tổng collection vẫn là **3.296.089**.

Đây là các lần đo trực tiếp trên máy hiện tại, không phải kết luận benchmark tổng quát hoặc cam kết thời gian cho mọi truy vấn. Tổng không có bộ lọc lấy từ metadata collection; tổng truy vấn có bộ lọc vẫn dùng count_documents.

## Dữ liệu và phạm vi

Số liệu gốc sau làm sạch vẫn là **60.109 sản phẩm, 3.296.089 review, 297.529 người dùng**. Lần sửa này không nạp lại dữ liệu, không thay thuật toán hay kết quả thực nghiệm buổi 4. Thay đổi CSDL chỉ là bổ sung chỉ mục đọc; các kiểm thử ghi dùng database tích hợp riêng và dữ liệu TEST_/DEMO_ được dọn sau kiểm thử.

Các file chỉnh sửa: app.js, styles.css, mongo.py, api.py; thêm tests/test_frontend.cjs và tests/test_frontend.py. Hash các file, kết quả kiểm thử và tốc độ được lưu trong reports/ui_audit_final.json.

## Mở lại

Mở **http://127.0.0.1:5055** và nhấn **Ctrl+F5** để tải lại JavaScript/CSS mới. Mã nguồn đang dùng nằm ở **D:\AmazonMoviesTV\project**. Tệp .env và thông tin đăng nhập cục bộ không được đưa vào gói mã nguồn chia sẻ.
