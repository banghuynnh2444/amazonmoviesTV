# Buổi 5: Backend Flask REST API và giao diện website

**Nhóm:** Huỳnh Công Bằng (4654100001) — Backend Flask, REST API, luồng ghi review và đồng bộ · Lê Minh Thuận (4654100012) — giao diện, trang gợi ý, khám phá đồ thị.

> Giao diện được làm lại ở buổi 6 theo hướng đơn giản, rõ ràng: nền sáng, bảng số liệu, không hiệu ứng trang trí; mỗi trang có đường dẫn riêng (`#/...`) nên dùng được nút Back và gửi liên kết cho người khác. Tài liệu này mô tả bản hiện tại.

## Địa chỉ và mã nguồn

- Website: `http://127.0.0.1:5055` (chạy `python -m amazon_movies serve` hoặc `scripts/start-local.ps1 -StartApi`).
- Backend: `amazon_movies/api.py` (REST API), `recommend.py` (Cypher gợi ý), `algorithms.py` (hằng số và công thức dùng chung), `keywords.py` (TF-IDF), `mongo.py`, `graph.py`.
- Giao diện: `amazon_movies/templates/index.html`, `static/styles.css`, `static/app.js`. Thư viện: Chart.js 4.4.3, vis-network 9.1.9, đặt sẵn trong `static/vendor/` (xem README ở đó) nên website chạy không cần Internet.
- Danh sách API: `docs/API.md`.

## Các trang (tách hai khu ngày 14/11/2026)

Website trước đây trộn nội dung kỹ thuật (ASIN, PageRank, Cypher, HTTP 201…) vào trang cho người dùng. Nay tách hai khu; API của khu quản trị cần token quản trị (401 khi chưa đăng nhập, 403 với tài khoản thường).

**Khu người dùng**

| Trang | Đường dẫn | Chức năng |
|---|---|---|
| Trang chủ | `#/` | Gợi ý cho bạn (khi đã đăng nhập), thể loại, phim được yêu thích nhất, phim điểm cao nhất |
| Tìm phim | `#/search` | Từ khóa (Text Index trên tên và mô tả), thể loại, định dạng, khoảng giá, sắp xếp, phân trang; mỗi tác phẩm một dòng |
| Tìm trong lời đánh giá | `#/search?mode=reviews` | Tìm toàn văn trong hơn 3 triệu đánh giá, lọc khen/chê, sắp theo độ liên quan / mới nhất / hữu ích nhất |
| Chi tiết phim | `#/movie/{asin}` | Thông tin (diễn viên/thương hiệu, thể loại, định dạng, giá), điểm và phân bố sao gộp mọi phiên bản, khen/chê, từ khóa, các phiên bản đang bán, đánh giá của bạn (chấm/sửa/xóa), đánh giá của người xem có lọc và phân trang, bình chọn hữu ích, phim thường mua cùng |
| Gợi ý cho bạn | `#/for-you` | Chấm nhanh khi chưa đủ 3 phim; danh sách gợi ý lai kèm lý do |
| Người đánh giá | `#/reviewer/{reviewerID}` | Các đánh giá của một người xem |
| Tài khoản | `#/account` | Đăng ký / đăng nhập, phim bạn đã chấm, đăng xuất |

**Khu quản trị** (`#/admin`)

| Trang | Đường dẫn | Chức năng |
|---|---|---|
| Hệ thống & dữ liệu | `#/admin` | Trạng thái hai CSDL, đối soát trực tiếp và đầy đủ, hàng chờ đồng bộ, gộp ấn bản, tham số gợi ý, các tệp kết quả |
| Phân tích gợi ý | `#/admin/recommend` | 5 phương pháp kèm công thức; điểm, độ hỗ trợ, thành phần Hybrid; hồ sơ và người dùng tương đồng |
| Người dùng | `#/admin/user/{reviewerID}` | Lịch sử review, người dùng tương đồng |
| Đồ thị Neo4j | `#/admin/graph` | Đồ thị con quanh một phim hoặc người dùng (vis-network); người dùng hiện tên công khai |
| Thống kê review | `#/admin/stats` | Kiểm chứng VADER với số sao; 6 biểu đồ |
| Thực nghiệm | `#/admin/experiments` | Đối soát, chất lượng gợi ý, hiệu năng index, so sánh hai CSDL, GDS |
| Cộng đồng phim | `#/admin/communities` | PageRank, Louvain, 10 cộng đồng lớn nhất và danh sách phim từng cộng đồng |

## Luồng ghi review (đã kiểm tra trên giao diện)

1. Người dùng demo gửi form → `POST /api/reviews`; review lưu vào MongoDB với `synced = false` và điểm VADER.
2. `rebuild_stats` cập nhật thống kê phim và người dùng (chỉ gộp các trường thống kê review, không xóa PageRank/cộng đồng).
3. Backend MERGE quan hệ `REVIEWED` trong Neo4j, rồi đánh dấu `synced = true` nếu phiên bản trong MongoDB vẫn khớp.
4. Giao diện báo HTTP 201 (đã đồng bộ) hoặc 202 (chờ worker đồng bộ), nhãn cảm xúc và tải lại trang phim với số liệu mới.

Lần kiểm tra ngày 11/11/2026: tạo tài khoản demo, viết review 4 sao (VADER: tích cực 0,74, HTTP 201), sửa thành 2 sao (VADER: tiêu cực −0,66, HTTP 200), bình chọn một review khác (653 → 654 lượt); phân bố sao và cảm xúc của phim cập nhật đúng. Dữ liệu thử đã được xóa và thống kê đã tính lại sau khi kiểm tra.

## Hiệu năng khi demo

- Neo4j dùng page cache 3 GB và heap 4 GB (`runtime/neo4j/.../conf/neo4j.conf`) để toàn bộ đồ thị 1,3 GB nằm trong bộ nhớ; MongoDB dùng WiredTiger cache 2 GB (`scripts/start-local.ps1`).
- Khi khởi động, API chạy nền một bước làm nóng (quét quan hệ REVIEWED, tính thử gợi ý, nạp thống kê và bảng IDF) để lần gợi ý đầu tiên khi demo không chậm.
- Kết quả gợi ý lưu đệm 15 phút và bị xóa khi chính người dùng đó ghi review.
- Tìm toàn văn trong review: xếp hạng theo độ liên quan phải chấm điểm mọi review khớp, nên với từ quá phổ biến (ví dụ "good": 867.327 review, 45 giây) API chỉ xếp hạng khi có tối đa 30.000 review khớp; vượt ngưỡng thì trả kết quả chưa xếp hạng trong khoảng 1 giây và giao diện báo rõ.

## Kiểm thử

- `python scripts/verify_web_ui.py`: 54 kiểm tra trên dữ liệu thật (trang, tệp tĩnh, mọi API của khu người dùng, mọi API khu quản trị khi chưa đăng nhập phải trả 401 và khi đăng nhập quản trị phải trả 200, các mã lỗi 400/404), kiểm tra người dùng mới nhận gợi ý Phổ biến, từ khóa quá phổ biến được giới hạn và trang chủ không chứa số liệu kỹ thuật; ghi `reports/buoi5_web_ui.json`.
- `python -m pytest -q`: kiểm thử dữ liệu và giao diện (Node.js): định dạng ngày, escape HTML, nút sửa/bình chọn, phiên lưu hỏng, phản hồi tìm kiếm đến muộn không ghi đè kết quả mới.
- `MOVIES_INTEGRATION=1 python -m pytest -q`: thêm 4 bài trên CSDL thật (database MongoDB riêng): đăng nhập, ghi/sửa, bình chọn không lặp và không tự bình chọn, giữ PageRank khi ghi review, cờ phiên bản, phục hồi khi Neo4j lỗi, người dùng mới nhận gợi ý Phổ biến.
