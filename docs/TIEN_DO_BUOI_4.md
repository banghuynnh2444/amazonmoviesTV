# Buổi 4: Thực nghiệm — chất lượng gợi ý, hiệu năng index, so sánh hai CSDL, phân tích đồ thị

**Nhóm:** Huỳnh Công Bằng (4654100001) · Lê Minh Thuận (4654100012)

Mục 1 và 3 chạy lại ngày 14/11/2026 sau khi gộp ấn bản thành tác phẩm (`docs/SUA_LOI_2026-11-14.md`); mục 2 và PageRank/Louvain giữ số đo ngày 11/11 vì truy vấn và dữ liệu đo không đổi. Mọi số trùng với các tệp trong `reports/`. Báo cáo đầy đủ có biểu đồ: https://claude.ai/artifact/7ueR5VAtcxat4gsEMi8yjm

## 1. Chất lượng gợi ý (`reports/buoi4_evaluation.json`)

**Số cũ (Hybrid NDCG@10 = 0,0559, "gấp 51 lần Phổ biến") không còn dùng.** Khi đó 9,9% tác phẩm phù hợp trong Test là bản sao của một review đã có trong Train (cùng review hiển thị ở ấn bản DVD và Blu-ray), và Phổ biến dùng điểm Bayesian nên gần như không trúng. Lần chạy mới:

- Đơn vị là **tác phẩm**: các ấn bản của một phim được gộp, 150.464 dòng review bản sao bị bỏ trước khi chia.
- Mỗi người dùng: 80% review cũ nhất là Train, 20% mới nhất là Test. Review giống hệt nhau của cùng người ở hai tác phẩm khác nhau (dán lại cho các phần của series) không bị tách: 39.017 dòng như vậy được đưa cả vào Train.
- Tác phẩm phù hợp = trong Test, điểm TB của người dùng ≥ 4 sao, chưa có trong Train ở bất kỳ ấn bản nào. Kiểm tra lại: 0 / 2.700 review phù hợp trong Test giống hệt một review Train của chính người đó.
- Phổ biến = tác phẩm có nhiều review ≥ 4 sao nhất trong Train (mốc mạnh hơn điểm Bayesian cũ).
- 227.686 người dùng đủ điều kiện; 1.200 người kiểm thử và 600 người validation tách rời (seed 42); trung bình 2,25 tác phẩm phù hợp mỗi người. Thuật toán chạy là bản Python 1-1 của Cypher (`algorithms.py`) trên đồ thị chỉ gồm Train.

| Phương pháp | Precision@10 | Recall@10 | NDCG@10 | HitRate@10 | Có gợi ý riêng |
|---|---|---|---|---|---|
| Lai (hybrid) | **0,0108** | **0,0538** | **0,0393** | **9,25%** | 99,1% |
| Lọc cộng tác (CF) | 0,0103 | 0,0508 | 0,0375 | 8,67% | 77,8% |
| Mua/xem cùng | 0,0067 | 0,0333 | 0,0201 | 5,83% | 97,8% |
| Theo nội dung | 0,0027 | 0,0149 | 0,0104 | 2,25% | 99,0% |
| Phổ biến (mốc) | 0,0031 | 0,0170 | 0,0102 | 3,08% | — |

- Hybrid có NDCG@10 gấp gần **4 lần** Phổ biến và cao hơn CF đơn lẻ 5%; Nội dung chỉ ngang Phổ biến.
- CF chọn cùng lúc hai tham số trên validation (cặp ít lọc nhất, rồi λ nhỏ nhất, đạt 99% NDCG tốt nhất): **ít nhất 2 láng giềng cùng thích** (1: 0,0227 · 2: 0,0323 · 3: 0,0316 · 4: 0,0247 · 5: 0,0207 ở λ = 16) và **λ = 16** (0,0204 ở λ = 0 lên 0,0323; tốt nhất 0,0324 từ λ = 64). Không lọc thì láng giềng chỉ thích rất ít phim (Jaccard cao) kéo vào phim lạc đề. Website đổi λ 32 → 16 và thêm ngưỡng 2.
- Chuẩn hóa Hybrid chọn trên validation: chia cho điểm lớn nhất 0,0333 so với min–max 0,0307. Website đổi sang chia cho max.
- Kiểm chứng với Cypher của website (20 người dùng, toàn bộ dữ liệu): Top-10 giống hệt 100% ở cả 5 phương pháp.
- Hạn chế: also_buy/also_view không chia theo thời gian; chia 80/20 theo từng người; phim thích nhưng chưa review bị tính là không phù hợp; người dùng mới chỉ chấm vài phim thì CF dựa trên rất ít láng giềng.

## 2. Hiệu năng trước/sau index (`reports/buoi4_index_benchmark.json`)

Cùng một truy vấn trước và sau khi tạo index, trên tập con thật theo thời gian (10%, 50% review cũ nhất, 100%). Trung vị 3 lần sau 1 lần khởi động; MongoDB: `executionTimeMillis`; Neo4j: thời gian phía server của PROFILE. "< 1 ms" = dưới độ phân giải.

| Truy vấn | Không index 10% / 50% / 100% | Có index | Bản ghi đọc khi không index → có index (100%) |
|---|---|---|---|
| MongoDB · lịch sử review 1 người dùng | 312 / 2.644 / 4.943 ms | < 1 ms | 3.296.089 document → 20 |
| MongoDB · 20 review hữu ích nhất 1 phim | 227 / 2.423 / 4.629 ms | < 1 ms | 3.296.089 document → 20 |
| Neo4j · tìm review theo review_id | 155 / 849 / 1.790 ms | < 1 ms | 6.592.179 db hits → 2 |
| Neo4j · phim điểm TB ≥ 4,8 và ≥ 50 review | 15 / 27 / 22 ms | 2 / 5 / 6 ms | 128.244 db hits → 15.239 |

## 3. So sánh MongoDB và Neo4j (`reports/buoi4_db_comparison.json`)

Đo lại 14/11 với định nghĩa theo tác phẩm (bỏ review bản sao, gộp ấn bản, bỏ nút điều hướng). Trung vị 5 lần; số stage/mệnh đề đếm tự động từ truy vấn đã chạy; cả ba bài cho kết quả trùng nhau.

| Bài toán | MongoDB | Neo4j | Nhanh hơn |
|---|---|---|---|
| (a) 20 người dùng có nhiều phim cùng thích nhất | 31,6 ms · 12 stage (15 kể cả lồng) | 19,3 ms · 19 mệnh đề | Neo4j ×1,6 |
| (b) Phim mua/xem cùng 1–2 bước, gộp ấn bản | 44,2 ms · 16 stage (23 kể cả lồng) | 1,9 ms · 6 mệnh đề | Neo4j ×23,5 |
| (c) Điểm TB và số review theo thể loại | 266,0 ms · 8 stage | 132,6 ms · 9 mệnh đề | Neo4j ×2,0 |

Bản đo 11/11 MongoDB nhanh hơn ở bài (c) (228 so với 303 ms); khi chỉ tính ấn bản đại diện và bỏ nút điều hướng, Neo4j duyệt ít quan hệ hơn nên nhanh gấp đôi. Thêm `$project` trước `$unwind` không đổi thời gian MongoDB (260 ms). Bài (c) chỉ đọc ~59 nghìn sản phẩm; thống kê trên 3,1 triệu review và tìm kiếm toàn văn vẫn chỉ MongoDB làm được vì Neo4j không lưu nội dung review.

## 4. Phân tích đồ thị (`reports/buoi4_graph_analytics.json`, `reports/buoi3_gds_similarity.json`)

- **PageRank** (60.109 phim, 843.257 cạnh có hướng, damping 0,85): hội tụ sau 113 vòng. Top 3: War: 10-Movie Collection (51,89), John Wick (50,17), Drive-In Cult Cinema Collection (44,85). 9/10 phim đầu là bộ sưu tập chỉ có 15–250 review.
- **Louvain** (vô hướng): modularity 0,841, 3 mức, 15.512 cộng đồng; 15.133 phim không có liên kết; 58 cộng đồng từ 5 phim; 10 cộng đồng lớn nhất chiếm 59,7% phim có liên kết. Chủ đề theo danh mục đặc trưng: Sony/Fox, Musicals/MGM, Horror/Fantasy/Sci-Fi cổ điển, kinh dị nhiều phần (Lionsgate), phim truyền hình hài/hành động, Giáng sinh (Hallmark), tài liệu A&E, trinh thám BBC, Anime, HBO. Số hiệu cộng đồng đổi giữa các lần chạy, chủ đề giữ nguyên.
- **Node Similarity** (chạy lại 14/11 theo tác phẩm, bỏ bản sao): 4.884.618 quan hệ SIMILAR_TO cho 246.055 người dùng (82,7%), Jaccard trên phim ≥ 4 sao, topK 20, ngưỡng 0,05, 22,3 phút. Bản trước 5.260.638 quan hệ (88,9%) do bản sao làm tăng số phim chung.
