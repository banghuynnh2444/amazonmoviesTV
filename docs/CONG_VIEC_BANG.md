# Huỳnh Công Bằng — buổi 1–6

**MSSV: 4654100001.** Phần việc theo đúng phân công trong thuyết minh: MongoDB, dữ liệu, phân tích cảm xúc, Backend Flask REST API, đồng bộ hai CSDL và thực nghiệm hiệu năng.

## Buổi 1: Cài đặt, khảo sát và thiết kế

MongoDB sử dụng binary sẵn có trên máy, chạy database đồ án riêng ở cổng 27028; dữ liệu đặt tại D:\AmazonMoviesTV\runtime\mongo-data. Hai tệp Amazon 2018 tải nguyên gốc vào D:\AmazonMoviesTV\data\raw. `reports/sources_downloaded.json` ghi đường nguồn, số byte và SHA-256 để xác định đúng phiên bản tệp.

EDA thực hiện bằng bộ đọc gzip/JSON Lines theo luồng, không đọc toàn bộ vào DataFrame. Pandas tính thống kê chiều dài trên 100.000 review đầu, có ghi rõ phạm vi mẫu; các số dòng, user, asin, sao và trường thiếu được đếm trên toàn bộ tệp.

Kết quả EDA đầy đủ:

- 3.410.019 review nguồn, 297.529 reviewerID, 60.175 asin trong 5-core.
- Metadata tải thực tế: 203.766 dòng, 181.839 asin khác nhau; 59 dòng thiếu tên hợp lệ.
- Đã khảo sát trường trống, định dạng style, phân bố sao, mốc thời gian và chiều dài review. Xem báo cáo JSON để lấy số chính xác, không sử dụng số của mẫu chạy thử thay cho toàn bộ.

Thiết kế products/reviews/users, hai collection phụ helpful_votes/jobs và các schema/index được trình bày trong THIET_KE_CSDL.md. Việc thêm collection phụ phục vụ chống bình chọn lặp và theo dõi tác vụ, không thay vai trò ba collection chính trong thuyết minh.

## Buổi 2: Làm sạch và nạp dữ liệu

File chính: `amazon_movies/data.py`, `amazon_movies/mongo.py`.

1. Giải mã HTML, ghép description dạng mảng, giữ nguyên dữ liệu nguồn gzip.
2. Chuẩn hóa giá, số hữu ích, thời gian UTC, định dạng từ style.
3. Upsert sản phẩm theo asin; bỏ metadata thiếu tên.
4. Chỉ nhận review có metadata hợp lệ. Mỗi review có review_id ổn định, khử trùng dòng JSON giống hệt; không làm mất các sự kiện khác nhau chung một cặp user–asin.
5. VADER chạy theo lô trong các worker; văn bản trống vẫn giữ số sao và nhãn unavailable.
6. Tính stats cho sản phẩm/người dùng; nhúng tối đa 5 trích đoạn review hữu ích.
7. Chỉ giữ sản phẩm thực sự có review được giữ lại; dựng secondary index sau bulk load.

Lệnh: `python -m amazon_movies import-mongo --workers 8`. Kết quả thật ở `reports/buoi2_mongodb_import.json`; trong khi chạy, xem `buoi2_import_progress.json` và log ổ D.

## Buổi 3: Truy vấn, cảm xúc và API

- Text index riêng trên products và reviews; tìm kiếm theo q, danh mục, format và giá.
- Aggregation có match/group/bucket/facet/lookup; thống kê sao, cảm xúc, ma trận đối chiếu số sao × cảm xúc (`sentiment_by_star` và `sentiment_alignment`), thời gian, danh mục và format.
- Computed/Subsets: số liệu trang chi tiết được tính sẵn; review tiêu biểu chỉ nhúng trích đoạn ngắn.
- API đăng ký/đăng nhập demo, tạo review, sửa review thuộc tài khoản và bình chọn hữu ích một lần.
- Password băm; mã DEMO_ và is_demo tách khỏi dữ liệu nghiên cứu. source_vote giữ số hữu ích gốc.
- MongoDB ghi trước; cập nhật Neo4j bằng review_id + version; khi lỗi trả 202 và thử lại qua sync worker.
- Token hết hạn sau 24 giờ; không cho client tự chọn reviewerID của người dùng Amazon để ghi review.

## Buổi 4: Đo hiệu năng MongoDB và so sánh hai CSDL

Số liệu của lần chạy lại ngày 11/11/2026 (`scripts/run_session4.py`), trùng với `reports/`.

- Đo cùng một truy vấn trước (`COLLSCAN`) và sau khi tạo index (`IXSCAN`) bằng `explain('executionStats')` ở 3 tập con theo thời gian: 10% (329.608 review), 50% (1.648.044) và 100% (3.296.089) (`reports/buoi4_index_benchmark.json`). Không index: lịch sử review của một người dùng mất 312 / 2.644 / 4.943 ms, 20 review hữu ích nhất của một phim mất 227 / 2.423 / 4.629 ms; có index: dưới 1 ms ở mọi mức, số document đọc giảm từ 3.296.089 xuống 20.
- Ba cặp truy vấn đối chứng MongoDB (Aggregation, `$lookup`) và Neo4j (Cypher) trên toàn bộ dữ liệu (`reports/buoi4_db_comparison.json`, `queries/`), trung vị 5 lần, cả ba cho kết quả trùng nhau, số stage đếm tự động:
  - Đo lại 14/11 theo tác phẩm (bỏ bản sao, gộp ấn bản, bỏ nút điều hướng); cả ba bài khớp kết quả:
  - **(a) Người dùng tương đồng**: MongoDB 31,6 ms (12 stage, 15 kể cả lồng), Neo4j 19,3 ms → Neo4j nhanh hơn 1,6 lần.
  - **(b) Mua/xem cùng 2 bước**: MongoDB 44,2 ms (16 stage, 23 kể cả lồng), Neo4j 1,9 ms → Neo4j nhanh hơn 23,5 lần.
  - **(c) Điểm trung bình theo thể loại**: MongoDB 266,0 ms (Computed Pattern), Neo4j 132,6 ms → Neo4j nhanh hơn 2 lần (bản 11/11 MongoDB nhanh hơn; nay Neo4j chỉ duyệt ấn bản đại diện). MongoDB vẫn giữ vai trò tìm kiếm toàn văn và thống kê trên 3,1 triệu review.
- API `/api/experiments` và `/api/analytics/communities` đưa kết quả lên website.

## Buổi 5: Backend Flask REST API cho website

- `amazon_movies/api.py` phục vụ giao diện tại `http://127.0.0.1:5055`; danh sách đầy đủ ở `docs/API.md`:
  - `GET /api/home` (cập nhật 14/11): phim được yêu thích nhất (số review ≥ 4 sao theo tác phẩm), điểm cao nhất (Bayesian), thể loại thật; PageRank và cộng đồng Louvain chuyển sang khu quản trị.
  - `GET /api/facets`: danh mục và định dạng lấy từ dữ liệu kèm số phim.
  - `GET /api/products`, `/api/reviews`: tìm kiếm Text Index, lọc, sắp xếp, phân trang. Với từ khóa quá phổ biến (hơn 30.000 review khớp) API trả kết quả chưa xếp hạng và báo rõ, thay vì mất hàng chục giây chấm điểm.
  - `GET /api/products/<asin>/keywords`: từ khóa TF-IDF (`keywords.py`), tách theo review tích cực / tiêu cực.
  - `GET /api/users/<uid>/profile`, `/similar`, `/api/graph/ego`, `/api/statistics` (có bộ nhớ đệm, ~35 ms).
  - Đăng ký/đăng nhập `DEMO_`, tạo/sửa review, bình chọn hữu ích (không lặp, không tự bình chọn), VADER tức thời, đồng bộ sang Neo4j, worker `sync --watch`.
- Kết quả gợi ý lưu đệm 15 phút và bị xóa khi người dùng ghi review; API làm nóng bộ nhớ đệm khi khởi động.

## Buổi 6: Kiểm thử, sửa lỗi, tổng hợp báo cáo

- Sửa lỗi `$merge` trong `rebuild_stats` làm mất PageRank/cộng đồng của phim khi ghi review; thêm kiểm thử hồi quy.
- Viết lại phép so sánh hai CSDL (cùng định nghĩa "thích", kiểm tra kết quả khớp, đếm stage tự động) và phép đo index MongoDB theo tập con thời gian.
- Từ khóa TF-IDF, bộ lọc lấy từ dữ liệu, giới hạn xếp hạng cho từ khóa quá phổ biến.
- 14/11: làm sạch Brand rác (2.743 giá trị) và tiêu đề lẫn HTML (855); gộp ấn bản thành tác phẩm (`editions.py`: 694 tác phẩm nhiều ấn bản, 150.464 dòng bản sao `is_copy`, `dup_group` cho review giống hệt giữa các tác phẩm); thống kê và dashboard tính trên 3.145.625 review khác nhau; VADER gắn `unsupported_language` cho review tiếng Việt; API tách khu người dùng (`/api/me/*`, xóa đánh giá, một đánh giá mỗi tác phẩm) và khu quản trị (`/api/admin/*`, 401/403).
- `scripts/verify_web_ui.py` kiểm tra endpoint của cả hai khu (kể cả 401 khi chưa đăng nhập quản trị) và ghi `reports/buoi5_web_ui.json`.
- Kiểm thử: 26/26 bài đạt (gồm tích hợp với CSDL thật). Tổng hợp trong `docs/SUA_LOI_2026-11-14.md`.

## Cách trình bày khi báo cáo

Xem `docs/KICH_BAN_DEMO.md`. Phần của Bằng: `buoi1_eda.json` → mô hình collection/schema → đoạn `normalize_review_batch` và `bulk_write` → các index trong `mongo.initialize` → trên website: tìm kiếm phim và review, trang chi tiết phim (Computed + Subset Pattern), viết review và xem đồng bộ MongoDB → Neo4j → trang Thực nghiệm mục 3 (index) và mục 4 (so sánh hai CSDL). Dùng kiểm thử lỗi đồng bộ trong `tests/test_integration.py` để chứng minh dữ liệu vẫn được giữ khi Neo4j tạm lỗi.
