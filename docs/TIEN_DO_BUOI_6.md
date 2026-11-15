# Buổi 6: Kiểm thử tổng thể, sửa phương pháp thực nghiệm, làm lại giao diện, báo cáo

**Nhóm:** Huỳnh Công Bằng (4654100001) · Lê Minh Thuận (4654100012) · Ngày 11/11/2026, cập nhật 14/11/2026

> **Cập nhật 14/11/2026.** Rà soát lần hai phát hiện cùng một review hiện ở nhiều ấn bản (DVD/Blu-ray) của một phim, làm số đánh giá gợi ý bị thổi lên (9,9% phim "phù hợp" trong Test đã có trong Train) và mốc Phổ biến quá yếu. Đã gộp ấn bản thành tác phẩm, chạy lại thực nghiệm (Hybrid NDCG@10 0,0559 → 0,0393, gấp gần 4 lần Phổ biến thay vì 51 lần; λ 32 → 16; thêm ngưỡng ≥ 2 láng giềng cùng thích cho CF; chuẩn hóa min–max → chia cho max), làm sạch Brand/tiêu đề, tách website thành khu người dùng và khu quản trị, 26/26 kiểm thử đạt. Chi tiết và số mới: `docs/SUA_LOI_2026-11-14.md`. Bảng bên dưới là lần sửa 11/11, giữ để đối chiếu.

## Sản phẩm bàn giao

| Sản phẩm | Vị trí |
|---|---|
| Báo cáo cuối kỳ (13 mục, biểu đồ/sơ đồ, ảnh chụp website) | https://claude.ai/artifact/7ueR5VAtcxat4gsEMi8yjm · `D:\AmazonMoviesTV\tai_lieu\bao_cao\BAO_CAO_CUOI_KY_Amazon_MoviesTV.docx` và `.pdf` |
| Slide thuyết trình (14 trang, có ghi chú người nói) | https://claude.ai/artifact/JbPa5mdzNty7bzQn8TCYmP (tải về PowerPoint hoặc PDF từ trang slide) |
| Kịch bản demo 12 phút, cách xử lý sự cố, câu hỏi thường gặp | `docs/KICH_BAN_DEMO.md` |
| Ảnh chụp website | `D:\AmazonMoviesTV\tai_lieu\anh_chup_website\` |
| Mã nguồn (không kèm `.env`) | `D:\AmazonMoviesTV\tai_lieu\ma_nguon_nop\` |

Hai liên kết claude.ai là riêng tư: người khác chỉ mở được sau khi chủ tài khoản chia sẻ từ nút Share trên trang.

## Những gì đã sửa sau khi rà soát đối chiếu với thuyết minh

| Vấn đề phát hiện | Cách sửa | Tệp |
|---|---|---|
| Phần đánh giá gợi ý chạy một bản Python viết lại với công thức khác Cypher của website (CF dùng `4,6 − điểm TB`, cộng thêm thưởng log(support); số phim gốc khác) | Gom hằng số và công thức vào `algorithms.py`; Cypher và bản Python dùng chung. Thêm `parity_check`: cùng 20 người dùng chạy qua cả hai bản trên toàn bộ dữ liệu (CF, Nội dung, Phổ biến trùng 100%; Mua/xem cùng, Hybrid trùng 90% do thứ tự các review cùng thời điểm) | `algorithms.py`, `recommend.py`, `session4.py` |
| `zero_test_leakage: True` gán cứng; mẫu đánh giá chỉ lấy người dùng có ≥ 5 phim thích | Bỏ cờ gán cứng, ghi rõ 3 hạn chế (also_buy không chia theo thời gian…); chọn ngẫu nhiên đều trong 254.472 người dùng đủ điều kiện | `session4.py` |
| Công thức CF chia trung bình đẩy lên đầu phim chỉ một láng giềng thích (NDCG@10 validation 0,0094) | Thêm hệ số co λ, chọn trên 600 người dùng validation tách rời: λ = 32 (NDCG@10 0,0483) | `algorithms.py` |
| Hybrid chuẩn hóa bằng cách chia cho max, nhưng điểm CF có cộng điểm TB người dùng nên mọi ứng viên ≈ 1 | Chuẩn hóa min–max, chọn trên validation (0,0566 so với 0,0467) | `algorithms.py` |
| Đo index Neo4j: truy vấn "trước" và "sau" khác nhau, "sau" không đổi theo quy mô, mức 10/50% giả lập bằng LIMIT | Cùng một truy vấn trước/sau; tập con thật theo thời gian (sao chép REVIEWED → BENCH_REVIEWED theo đúng thứ tự review của MongoDB, xóa sau khi đo); thời gian phía server, trung vị 3 lần | `session4.py` |
| Số stage/mệnh đề trong so sánh hai CSDL gõ tay (bài b ghi 14, thực tế 15); bài (a) không kiểm tra kết quả khớp | Đếm tự động từ pipeline và câu Cypher; bài (a) dùng cùng định nghĩa "thích" ở hai CSDL và kiểm tra khớp; trung vị 5 lần | `session4.py` |
| PageRank chưa hội tụ (20 vòng) | 200 vòng tối đa, hội tụ sau 113 vòng (Top-20 không đổi) | `session4.py` |
| Tài liệu buổi 4 lệch số với JSON (ranLevels = 4 thay vì 3, chọn các cộng đồng thứ 8–10) | Viết lại từ kết quả mới; cộng đồng được gắn danh mục đặc trưng theo độ nâng (lift) | `docs/TIEN_DO_BUOI_4.md`, `session4.py` |
| SIMILAR_TO chỉ phủ 1,8% người dùng | Node Similarity cho người dùng từ 5 review: 88,9% người dùng; còn lại tính trực tiếp bằng Cypher | `graph.py`, `api.py` |
| Bộ lọc danh mục gõ cứng ("Sci-Fi" ra 0 phim) | Lấy danh mục/định dạng từ dữ liệu kèm số phim (`/api/facets`) | `mongo.py`, `api.py` |
| Trang chủ ghi "Bayesian" nhưng sắp theo số review | Dùng đúng hàm Phổ biến (Bayesian) | `api.py` |
| Từ khóa đếm tần suất, lẫn từ dừng ("his", "good") | TF-IDF với bảng IDF từ 300.000 review, tách theo review tích cực/tiêu cực | `keywords.py` |
| Ghi review làm mất PageRank và cộng đồng của phim (`$merge` thay cả object `stats`) | `$merge` gộp object `stats`; thêm kiểm thử hồi quy | `mongo.py`, `tests/test_integration.py` |
| Gợi ý lần đầu mất ~8 giây (page cache Neo4j 512 MB < đồ thị 1,3 GB) | Page cache 3 GB, heap 4 GB; làm nóng khi khởi động; lưu đệm kết quả gợi ý 15 phút | `neo4j.conf`, `api.py` |
| Có thể tự bình chọn review của mình | Chặn, trả 400 | `api.py` |
| Tìm trong review với từ quá phổ biến ("good") mất 45 giây | Chỉ xếp hạng khi ≤ 30.000 review khớp; vượt ngưỡng trả kết quả chưa xếp hạng (~1 giây) và báo rõ | `api.py`, `static/app.js` |
| Chart.js và vis-network tải từ CDN, demo cần Internet | Đặt bản gốc từ gói npm vào `static/vendor/` (đã đối chiếu SHA-256 giữa jsDelivr và unpkg) | `templates/index.html`, `static/vendor/` |
| Script nạp lại dữ liệu dùng ngưỡng Node Similarity cũ và xóa SIMILAR_TO trong một giao dịch | Mặc định mới (từ 5 review, ít nhất 3 phim thích); xóa theo lô 50.000 | `graph.py`, `cli.py`, `scripts/run_sessions_1_3.py` |
| Tài liệu và tệp kết quả còn số liệu cũ | Viết lại `CONG_VIEC_*.md`; tạo lại `buoi3_queries_api.json`, `buoi5_web_ui.json`, `RUN_STATUS.json`; chuyển `ui_audit_*` vào `reports/archive_giao_dien_cu/` | `docs/`, `reports/`, `scripts/verify_web_ui.py` |
| Giao diện nhiều emoji, gradient, hiệu ứng; khó đọc | Làm lại: nền sáng, bảng số liệu, mỗi trang một đường dẫn, đủ 9 nhóm chức năng | `templates/`, `static/` |

## Kiểm thử

- `python -m pytest -q`: 14 đạt (dữ liệu + giao diện bằng Node.js), 4 bỏ qua (cần CSDL).
- `MOVIES_INTEGRATION=1 python -m pytest -q`: 18/18 đạt.
- Kiểm tra trên trình duyệt: tất cả các trang; viết, sửa review và bình chọn bằng tài khoản demo tạm (dữ liệu thử đã xóa, thống kê đã tính lại).

## Chạy lại thực nghiệm

```powershell
& $python -m amazon_movies gds-similarity --min-reviews 5 --degree-cutoff 3   # ~22 phút
& $python -m amazon_movies keyword-idf
& $python .\scripts\run_session4.py
& $python -m amazon_movies verify
```
