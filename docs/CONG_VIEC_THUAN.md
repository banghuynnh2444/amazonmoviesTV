# Lê Minh Thuận — buổi 1–6

**MSSV: 4654100012.** Phần việc theo phân công: Neo4j, GDS, mô hình đồ thị, các phương pháp gợi ý, đánh giá thực nghiệm và giao diện Frontend Website (`Chart.js`, `vis-network`).

## Buổi 1: Neo4j, GDS và mô hình

Neo4j Community 5.26.33 và GDS 2.13.4 đã chuẩn bị riêng tại D:\AmazonMoviesTV\runtime\neo4j. Dùng Java 17 đã có tại ổ D. Bolt cổng 7698, Browser cổng 7485, bind 127.0.0.1. Mật khẩu khởi tạo ngẫu nhiên nằm trong .env cục bộ.

5 nhãn User/Product/Category/Brand/Format; 8 loại quan hệ REVIEWED, IN_CATEGORY, SUBCATEGORY_OF, BY_BRAND, AVAILABLE_AS, ALSO_BOUGHT, ALSO_VIEWED, SIMILAR_TO. Mã reviewerID/asin thống nhất với MongoDB. Category dùng mã toàn bộ đường dẫn, tránh gộp nhầm hai danh mục cùng tên lá.

Khởi tạo unique constraints cho khóa node và index review_id trên quan hệ. `doctor` xác nhận phiên bản; `graph-init` kiểm tra `RETURN gds.version()`.

## Buổi 2: Import và đối soát

File chính: `amazon_movies/graph.py`.

1. Đọc sản phẩm/người dùng đã làm sạch từ MongoDB theo lô.
2. Tạo node thuộc tính và danh mục phân cấp, thương hiệu, format quan sát được.
3. Chỉ tạo ALSO_BOUGHT/ALSO_VIEWED khi cả hai Product đã có trong tập dữ liệu; bỏ self-link.
4. Mỗi review hợp lệ có một REVIEWED theo review_id; chỉ giữ thuộc tính phục vụ truy vấn, không chép reviewText dài sang Neo4j.
5. Sau commit đồ thị, chỉ xác nhận synced nếu version MongoDB còn đúng. Phiên bản cũ không được ghi đè phiên bản mới trên Neo4j.
6. Đếm node, quan hệ, kiểm tra trùng review_id, hàng chờ và đối soát với MongoDB; tùy chọn kiểm tra từng ID theo lô.

Lệnh: `python -m amazon_movies import-graph`; `python -m amazon_movies verify`. Đọc `buoi2_neo4j_import.json` và `buoi2_reconciliation.json` để lấy kết quả cuối cùng; không dùng bản smoke để báo cáo quy mô đầy đủ.

## Buổi 3: Thuật toán gợi ý

File chính: `amazon_movies/recommend.py`; câu Cypher minh họa: `queries/neo4j.cypher`.

**Mức tác phẩm (buổi 6, 14/11):** mọi phương pháp bỏ REVIEWED có `copy = true` (bản sao của cùng một review ở ấn bản DVD/Blu-ray khác), gộp ứng viên theo `Product.work`, chỉ gợi ý ấn bản đại diện và loại mọi tác phẩm user đã đánh giá ở bất kỳ ấn bản nào.

**Collaborative filtering:** trung bình điểm theo cặp user–tác phẩm, chọn tác phẩm từ 4 sao; tối đa 100 tác phẩm yêu thích gần nhất; yêu cầu tối thiểu 2 tác phẩm chung. Từ tối đa 300 người có nhiều tác phẩm chung, tính Jaccard và giữ 30 người tương đồng nhất. Điểm = điểm TB người dùng + Σ sim·(sao − điểm TB láng giềng) / (Σ sim + λ), λ = 16 chọn trên tập validation.

**Item-based:** đi qua ALSO_BOUGHT/ALSO_VIEWED một hoặc hai bước; điểm = số đường đi / số bước ngắn nhất. Đây là liên kết sản phẩm quan sát trong dữ liệu Amazon lịch sử, không phải log xem nội dung phim.

**Content-based:** danh mục sâu (bỏ hai mức Category gốc quá rộng) và Brand của tối đa 20 sản phẩm yêu thích gần nhất, kết hợp điểm cộng Format ưu tiên (`AVAILABLE_AS`) trên tập ứng viên đầu bảng.

**Ngưỡng láng giềng của CF:** chỉ đề xuất tác phẩm có ít nhất 2 láng giềng cùng thích (`CF_MIN_SUPPORT`, chọn cùng λ trên validation; Cypher: `WHERE support >= $min_support`).

**Hybrid:** chia điểm từng thành phần cho điểm lớn nhất (chọn trên validation: 0,0333 so với min–max 0,0307), rồi cộng CF 0,45, liên quan 0,25, nội dung 0,20, cảm xúc 0,10; giữ phim gốc (`via`) và số láng giềng (`support`) để website ghi lý do gợi ý. Metadata kết quả lấy lại từ MongoDB theo đúng thứ tự điểm. Các trọng số là cấu hình cố định, chưa được tối ưu.

**Cold start / mốc Phổ biến:** tác phẩm có nhiều review từ 4 sao nhất (không tính bản sao); response ghi `fallback_to_popular` để không nhầm baseline với kết quả CF. Điểm Bayesian chỉ dùng cho danh sách "Điểm cao nhất" trên trang chủ.

**Node Similarity GDS:** Jaccard trên tác phẩm ≥ 4 sao (bỏ review bản sao), chiếu người dùng từ 5 review và có ít nhất 3 phim thích, topK 20, ngưỡng 0,05: lần chạy 14/11 ghi 4.884.618 cạnh `SIMILAR_TO` cho 246.055 người dùng (82,7%) trong 22,3 phút (`reports/buoi3_gds_similarity.json`). Projection trong RAM được xóa ngay sau khi ghi. Hằng số và công thức của mọi phương pháp nằm chung trong `amazon_movies/algorithms.py`.

## Buổi 4: PageRank, Louvain, đánh giá thuật toán và hiệu năng Neo4j

Số liệu của lần chạy lại ngày 11/11/2026 (`scripts/run_session4.py`), trùng với `reports/`.

- **PageRank** (60.109 phim, 843.257 cạnh có hướng, damping 0,85): hội tụ sau 113 vòng; đứng đầu là War: 10-Movie Collection (51,89), John Wick (50,17), Drive-In Cult Cinema Collection (44,85).
- **Louvain**: modularity 0,841, 3 mức; 58 cộng đồng từ 5 phim, 10 cộng đồng lớn nhất chiếm 59,7% phim có liên kết. Chủ đề theo danh mục đặc trưng (độ nâng): Anime ×24, BBC ×15, Christmas ×13, A&E ×11, HBO ×8, Horror/Fantasy, Musicals/MGM, Sony/Fox. `pagerank` và `community` được ghi về MongoDB.
- **Đánh giá thuật toán** (`reports/buoi4_evaluation.json`, chạy lại 14/11 ở mức tác phẩm, bỏ review bản sao, nhóm review giống hệt nhau không bị tách): 80% review cũ làm Train, 20% mới làm Test; 1.200 người kiểm thử và 600 người validation tách rời, chọn ngẫu nhiên trong 227.686 người đủ điều kiện. Hybrid tốt nhất trên cả 4 độ đo (Precision@10 0,0108; Recall@10 0,0538; NDCG@10 0,0393; HitRate@10 9,25%; gần 4 lần Phổ biến), tiếp theo là CF (NDCG@10 0,0375, với ngưỡng ≥ 2 láng giềng cùng thích), Mua/xem cùng (0,0201), Nội dung (0,0104), Phổ biến (0,0102). Số cũ (Hybrid 0,0559, "gấp 51 lần") bị thổi lên do rò rỉ bản sao giữa các ấn bản và mốc Phổ biến yếu.
- **Kiểm chứng**: bản Python dùng để đánh giá là bản 1-1 của Cypher; trên 20 người dùng với toàn bộ dữ liệu, Top-10 giống hệt 100% ở CF, Nội dung, Phổ biến và 90% ở Mua/xem cùng, Hybrid.
- **Hiệu năng Neo4j `PROFILE`** (`reports/buoi4_index_benchmark.json`): cùng truy vấn trước/sau index trên tập con thật 10/50/100%. Tìm review theo `review_id`: 155 / 849 / 1.790 ms khi không index (6.592.179 db hits ở 100%), dưới 1 ms khi có index (2 db hits). Lọc phim điểm cao: 22 ms → 6 ms ở 100%.

## Buổi 5: Giao diện website và trực quan hóa đồ thị

Giao diện (`templates/index.html`, `static/styles.css`, `static/app.js`) được làm lại ở buổi 6 theo hướng đơn giản, rõ ràng; mô tả từng trang ở `docs/TIEN_DO_BUOI_5.md`:

- Khu người dùng: Trang chủ, Tìm phim (phim / lời đánh giá), Chi tiết phim (các phiên bản, chấm/sửa/xóa đánh giá), Gợi ý cho bạn (chấm nhanh, lý do gợi ý), Tài khoản. Khu quản trị `#/admin`: Hệ thống & dữ liệu, Phân tích gợi ý, Đồ thị Neo4j, Thống kê review, Thực nghiệm, Cộng đồng phim; cần tài khoản quản trị.
- Trang Gợi ý: 5 phương pháp kèm mô tả công thức, điểm và 4 thành phần của Hybrid, hồ sơ và người dùng tương đồng.
- Trang Đồ thị: đồ thị con (`ego_graph`) bằng vis-network, màu theo loại nút và loại cạnh, nhấp đúp để đổi trung tâm.
- Trang Thống kê: 6 biểu đồ Chart.js. Hai thư viện nằm trong `static/vendor/` nên website chạy không cần Internet.

## Buổi 6: Sửa phương pháp đánh giá, hoàn thiện giao diện

- Gom hằng số và công thức gợi ý vào `algorithms.py`; thêm hệ số co λ cho CF và cách chuẩn hóa Hybrid, cả hai chọn trên tập validation (14/11: λ = 16, chia cho max); thêm `parity_check` (Top-10 trùng Cypher 100% ở cả 5 phương pháp).
- Đo index Neo4j trên tập con thật (quan hệ tạm `BENCH_REVIEWED`), PageRank chạy tới hội tụ, cộng đồng Louvain gắn danh mục đặc trưng.
- Node Similarity cho toàn bộ người dùng 5-core (82,7% sau khi bỏ bản sao); người dùng chưa có `SIMILAR_TO` được tính láng giềng trực tiếp.
- Làm lại toàn bộ giao diện; kiểm thử giao diện bằng Node.js (`tests/test_frontend.cjs`).

## Cách trình bày khi báo cáo

Xem `docs/KICH_BAN_DEMO.md`. Phần của Thuận: Neo4j Browser → `SHOW CONSTRAINTS` → đếm 5 nhãn và 8 quan hệ → câu CF trong `queries/neo4j.cypher` → trên website, khu quản trị: Phân tích gợi ý (đổi phương pháp, giải thích thành phần Hybrid), Đồ thị Neo4j, Cộng đồng phim → trang Thực nghiệm mục 2 (đánh giá, chọn λ, kiểm chứng với Cypher) và mục 5 (PageRank, Louvain, Node Similarity).
