# Tiến độ thực hiện Buổi 1, 2, 3

**Đề tài:** Xây dựng hệ thống gợi ý phim cá nhân hóa và phân tích đánh giá người dùng trên dữ liệu Amazon Movies & TV, sử dụng MongoDB và Neo4j.  
**Nhóm thực hiện:** Huỳnh Công Bằng (4654100001) · Lê Minh Thuận (4654100012)

---

## 1. Kết quả Buổi 1 — Môi trường, EDA và Thiết kế CSDL

- **Môi trường CSDL cục bộ** (`reports/buoi1_environment.json`):
  - MongoDB Community `8.3.11` (`127.0.0.1:27028`, database `amazon_movies_tv`).
  - Neo4j Community `5.26.33` + Graph Data Science (GDS) `2.13.4` (`bolt://127.0.0.1:7698`, HTTP `7485`).
- **Tải và kiểm tra toàn vẹn dữ liệu gốc** (`reports/sources_downloaded.json`, `reports/buoi1_eda.json`):
  - `Movies_and_TV_5.json.gz`: **3.410.019** dòng review nguồn, **297.529** người dùng (`reviewerID`), **60.175** mã sản phẩm (`asin`).
  - `meta_Movies_and_TV.json.gz`: **203.766** dòng metadata (**203.707** dòng có `asin` và `title` hợp lệ, **181.839** `asin` phân biệt).
- **Thiết kế mô hình dữ liệu** (`docs/THIET_KE_CSDL.md`):
  - **MongoDB**: 3 collection nghiệp vụ chính (`products`, `reviews`, `users`) có `$jsonSchema` validation, Text Index (`product_fulltext`, `review_fulltext`), Compound Index, áp dụng **Computed Pattern** (`stats`) và **Subset Pattern** (`top_reviews`).
  - **Neo4j**: 5 nhãn Node (`User`, `Product`, `Category`, `Brand`, `Format`) với Unique Constraints và 8 loại Relationship (`REVIEWED`, `IN_CATEGORY`, `SUBCATEGORY_OF`, `BY_BRAND`, `AVAILABLE_AS`, `ALSO_BOUGHT`, `ALSO_VIEWED`, `SIMILAR_TO`).

---

## 2. Kết quả Buổi 2 — ETL theo lô và Đối soát hai CSDL

- **Kết quả nạp MongoDB** (`reports/buoi2_mongodb_import.json`):
  - Số dòng review nguồn đọc qua luồng: **3.410.019**.
  - Số review loại do sản phẩm không có metadata hợp lệ: **5.227**.
  - Số dòng JSON trùng hệt được khử bằng khóa băm SHA-256 (`review_id`): **108.703**.
  - Số bản ghi hợp lệ lưu trong MongoDB: **60.109** `products`, **297.529** `users`, **3.296.089** `reviews` (đã tính điểm cảm xúc VADER và dựng đầy đủ `stats`, `top_reviews`, Text Index).
- **Kết quả nạp Neo4j và đối soát** (`reports/buoi2_neo4j_import.json`, `reports/buoi2_reconciliation.json`):
  - **Nodes**: `Product = 60.109`, `User = 297.529`, `Category = 653`, `Brand = 22.556`, `Format = 44`.
  - **Relationships**: `REVIEWED = 3.296.089`, `ALSO_BOUGHT = 559.978`, `ALSO_VIEWED = 283.279`, `IN_CATEGORY = 193.232`, `AVAILABLE_AS = 100.151`, `BY_BRAND = 51.711`, `SUBCATEGORY_OF = 652`, `SIMILAR_TO = 5.260.638` (sau lần chạy Node Similarity cho toàn bộ người dùng 5-core ở buổi 6; lần chạy đầu chỉ lấy người dùng từ 50 review nên có 5.797 quan hệ). Cập nhật 14/11: sau khi bỏ Brand rác và gộp ấn bản, `BY_BRAND = 48.968` (22.526 Brand), `SIMILAR_TO = 4.884.618`; REVIEWED vẫn 3.296.089 dòng nguồn, trong đó 150.464 dòng mang `copy = true` (xem `SUA_LOI_2026-11-14.md`).
  - **Đối soát (`verify`)**: `ok = true` (khớp 100% số lượng `Product`, `User`, `REVIEWED`, không có `review_id` trùng lặp, `all_reviews_synced = true`).

---

## 3. Kết quả Buổi 3 — Truy vấn, Cảm xúc, Thuật toán Gợi ý và Đồng bộ

- **Tìm kiếm và Thống kê (MongoDB)**:
  - Tìm kiếm toàn văn theo từ khóa kết hợp lọc danh mục, định dạng, khoảng giá.
  - Aggregation `$facet` thống kê phân bố sao, cảm xúc VADER, xu hướng theo tháng, phân khúc giá (`$bucket`) và **ma trận đối chiếu Số sao × Cảm xúc (`sentiment_by_star` & `sentiment_alignment`)**.
- **Thuật toán Gợi ý và GDS (Neo4j + MongoDB)** (`reports/buoi3_queries_api.json`, `reports/buoi3_gds_similarity.json`):
  - Đã triển khai và kiểm chứng 5 phương pháp: `collaborative` (Jaccard + chuẩn hóa điểm lệch trung bình), `related` (`ALSO_BOUGHT`/`ALSO_VIEWED` 1–2 bước), `content` (Category sâu > 2 tầng, Brand và Format ưu tiên), `hybrid` (chuẩn hóa thang đo và kết hợp có trọng số), `popular` (làm trơn Bayesian cho người dùng mới).
  - Đã chạy GDS `gds.nodeSimilarity.write` tạo quan hệ `SIMILAR_TO` trên đồ thị.
- **API Ghi Review và Đồng bộ Chịu lỗi**:
  - Hỗ trợ đăng ký/đăng nhập tài khoản `DEMO_`, tạo/sửa review, bình chọn hữu ích chống lặp (`helpful_votes`).
  - Đồng bộ MongoDB → Neo4j theo `version` chống ghi đè ngược; tự động xếp hàng chờ (`HTTP 202`) và đồng bộ lại qua worker `sync --watch` khi Neo4j tạm ngưng.
