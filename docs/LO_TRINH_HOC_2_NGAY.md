# Học để hiểu và bảo vệ Amazon Movies & TV trong hai ngày

Thứ Bảy **14/11/2026** và Chủ nhật **15/11/2026**, giờ Việt Nam. Tài liệu viết theo mã nguồn tại `D:\AmazonMoviesTV\project`, sau rà soát ngày 13/11. Mỗi ngày khoảng 7–7,5 giờ học thực chất, có nghỉ và ăn trưa.

Mục tiêu là giải thích được hệ thống và tự làm các ví dụ nhỏ. Hai ngày chưa đủ để thành thạo mọi công nghệ. Mỗi phần học theo vòng: **hiểu ý nghĩa → tính hoặc vẽ bằng tay → tìm đúng đoạn code → thực hành → tự trả lời không nhìn tài liệu**. Nếu vướng, giảm phần mở rộng, giữ nền tảng và luồng chính.

## 1. Đề tài của mình thực sự làm gì?

Hệ thống xếp hạng sản phẩm Movies & TV trên Amazon để gợi ý cho một người dùng. Nó dùng lịch sử đánh giá, quan hệ sản phẩm, thuộc tính sản phẩm và cảm xúc trong review. Website là nơi minh họa kết quả.

| Thời điểm | Đầu vào | Xử lý | Đầu ra |
|---|---|---|---|
| Xây dựng dữ liệu | Hai tệp gzip review và metadata Amazon 2018 | Đọc từng dòng, chuẩn hóa, khử trùng hệt, VADER, nhập MongoDB rồi Neo4j | Document, node, relationship, thống kê |
| Xin gợi ý | `reviewerID`, phương pháp và K | Tìm ứng viên, tính điểm, loại sản phẩm đã review, xếp hạng | Tối đa K sản phẩm cùng điểm và thông tin |
| Viết review demo | Token tài khoản, `asin`, số sao, nội dung | Kiểm tra đầu vào, ghi MongoDB, cập nhật thống kê, đồng bộ Neo4j | ID review, cảm xúc và trạng thái đồng bộ |
| Đánh giá | Lịch sử được chia Train/Test | Xây mô hình trên Train, so gợi ý với review giữ lại | Precision@K, Recall@K, NDCG@K, Hit rate |

**Bài toán chính là gợi ý/xếp hạng.** VADER tạo nhãn cảm xúc là phần phân loại phụ bằng từ điển và luật. Louvain tìm cộng đồng là phần phân cụm đồ thị. Công thức CF tạo điểm xếp hạng; dự án không có bước huấn luyện một mô hình hồi quy dự đoán sao riêng. Không cần cố ép toàn bộ đề tài vào một trong ba loại phân lớp/phân cụm/hồi quy.

## 2. Bản đồ dự án để khỏi bị lạc

```text
D:\AmazonMoviesTV
├── data/raw/          Hai tệp nguồn nén, giữ nguyên
├── runtime/           Python, MongoDB data, Neo4j, log
├── project/
│   ├── amazon_movies/
│   │   ├── data.py           Đọc và chuẩn hóa dữ liệu, VADER, EDA
│   │   ├── mongo.py          Schema, index, ETL, thống kê, tìm kiếm
│   │   ├── graph.py          Node/cạnh, nạp và đồng bộ Neo4j
│   │   ├── algorithms.py     Công thức và bản Python để đánh giá
│   │   ├── recommend.py      Truy vấn gợi ý khi dùng website
│   │   ├── session4.py       Đánh giá, PageRank/Louvain, benchmark
│   │   ├── api.py            Các đường dẫn REST API
│   │   ├── keywords.py       Từ khóa TF-IDF
│   │   └── static/templates  Giao diện web
│   ├── queries/       MongoDB và Cypher mẫu
│   ├── tests/         Kiểm thử dữ liệu, API/đồng bộ, giao diện
│   └── reports/       Kết quả thực nghiệm trên toàn bộ dữ liệu
└── tai_lieu/          Không phải code: báo cáo Word/PDF, thuyết minh, ảnh chụp website, gói mã nguồn nộp bài
```

Luồng cần tự vẽ được:

```text
Amazon JSON Lines nén
  → data.py: chuẩn hóa + VADER
  → mongo.py: products / users / reviews trong MongoDB
  → graph.py: node và cạnh trong Neo4j
  → recommend.py: asin + điểm xếp hạng
  → MongoDB: lấy tên, giá, thống kê theo asin
  → api.py → app.js → màn hình người dùng
```

MongoDB là nguồn nghiệp vụ chính. Neo4j giữ phần đồ thị phục vụ truy vấn quan hệ. Hai bên cùng định danh sản phẩm bằng `asin`, người dùng bằng `reviewerID`, sự kiện review bằng `review_id`.

## 3. Lịch thứ Bảy 14/11: nền tảng và dữ liệu

| Giờ | Học và làm | Code cần mở | Tự kiểm tra để qua phần |
|---|---|---|---|
| 08:00–09:30 | Data, dataset, database, DBMS; bảng/bản ghi; SQL và NoSQL | `config.py`, ba collection trong `mongo.py` | Phân biệt dữ liệu với phần mềm quản lý dữ liệu; giải thích MongoDB/Neo4j không phải thuật toán AI |
| 09:45–11:15 | Đọc một review và một sản phẩm; khóa, trùng lặp, giá thiếu, 5-core | `data.py`: `rows`, `product`, `review`; báo cáo EDA/import | Giải thích từng trường; vì sao review khác nhau cùng cặp user–product vẫn giữ |
| 13:30–15:00 | MongoDB: document/collection, CRUD, index; thống kê tính sẵn | `mongo.py`: `initialize`, `rebuild_stats`, `search_products`; `queries/mongodb.js` | Viết được truy vấn lấy John Wick và review mới nhất; giải thích index và thống kê tính sẵn |
| 15:15–16:45 | Neo4j: node, nhãn, thuộc tính, cạnh; Cypher | `graph.py`: `SCHEMA`, `PRODUCTS`, `USERS`, `REVIEWS`, `LINKS` | Vẽ một người dùng, hai sản phẩm và các cạnh; đọc được `MATCH`/`WHERE`/`RETURN` |
| 19:30–21:00 | Ghép ETL, API và đồng bộ; luyện giải thích 3 phút | `api.py`: ghi/sửa review và `synchronize`; `graph.py`: `acknowledge`, `sync_pending` | Mô tả đúng điều gì xảy ra khi Neo4j tắt; phân biệt 201 và 202 |

Sau mỗi 25–30 phút, nghỉ 5 phút trong từng buổi. Cuối ngày: tự nói lại luồng trên giấy trắng, không mở README. Chưa tự giải thích được MongoDB/Neo4j thì dành 30 phút đầu sáng Chủ nhật ôn lại và rút bớt PageRank/Louvain.

## 4. Lịch Chủ nhật 15/11: thuật toán và bảo vệ

| Giờ | Học và làm | Code cần mở | Tự kiểm tra để qua phần |
|---|---|---|---|
| 08:00–09:30 | Tập hợp, vector nhị phân, Jaccard; CF theo người dùng | `algorithms.py`: `Interactions`, `neighbors`, `collaborative`; `recommend.py`: `CF` | Tính Jaccard và một điểm CF bằng tay; giải thích λ và vì sao bỏ sản phẩm đã review |
| 09:45–11:15 | Related, Content, Popular, Hybrid; VADER | `recommend.py`, `rank_hybrid`, `data.sentiment` | Tính một đường đi và chuẩn hóa chia cho max (chọn trên validation); giải thích điểm gợi ý không phải xác suất |
| 13:30–15:00 | Train/Test, validation, Precision/Recall/NDCG; đọc kết quả thật | `session4.py`: `evaluate_recommendations`, `compute_ranking_metrics`, `parity_check` | Phân biệt chọn tham số với đánh giá; nêu ít nhất ba giới hạn |
| 15:15–16:15 | Index, benchmark; PageRank/Louvain ở mức nguyên lý | `benchmark_indexes`, `compare_databases`, `run_graph_analytics` | Giải thích vì sao không nói Neo4j luôn nhanh hơn; PageRank không đồng nghĩa phim hay |
| 16:30–17:30 | Chạy demo 10–12 phút hai lần; mỗi người trình bày cả luồng | `docs/KICH_BAN_DEMO.md`, các màn hình chính | Mở đúng code khi bị hỏi; xử lý được cold start và trạng thái đồng bộ chờ |
| 19:30–20:30 | Vấn đáp 20 câu bên dưới, không nhìn đáp án | Ghi lỗi hiểu sai vào một trang giấy | Trả lời đúng ít nhất 16/20 và toàn bộ câu 1–8; còn sai thì ôn phần đó |

## 5. Những kiến thức phải hiểu theo đúng code

### 5.1 Database, SQL và NoSQL

Data là thông tin: “người U đánh giá sản phẩm P 5 sao”. Dataset là bộ dữ liệu được thu thập, chẳng hạn tệp Amazon tải về. Database là dữ liệu đã được tổ chức để lưu và khai thác. DBMS là phần mềm quản lý database: MongoDB, Neo4j, MySQL.

Trong mô hình quan hệ thường dùng SQL, có thể lưu bảng Users, Products, Reviews, rồi kết nối bằng khóa. MongoDB dùng document gần dạng JSON; Neo4j dùng đồ thị node/cạnh và truy vấn bằng Cypher. NoSQL không có nghĩa là không có cấu trúc hay không có quy tắc: code có JSON Schema ở MongoDB và ràng buộc khóa duy nhất ở Neo4j.

Hai CSDL là lựa chọn kiến trúc của nhóm để nghiên cứu hai cách tổ chức dữ liệu. MongoDB vẫn có thể làm truy vấn quan hệ bằng aggregation/lookup; Neo4j cũng lưu được thuộc tính văn bản. Phải giải thích bằng sự phù hợp và số đo thực tế, không nói một bên “không làm được”.

Ví dụ SQL để hiểu cách hỏi dữ liệu (chỉ minh họa nếu có bảng Reviews, dự án này không có SQL server): `SELECT asin, overall FROM Reviews WHERE reviewerID = 'U' ORDER BY timestamp DESC LIMIT 5;`. Cùng ý nghĩa trong MongoDB: `db.reviews.find({reviewerID:'U'}, {asin:1, overall:1}).sort({timestamp:-1}).limit(5)`. Cả hai đều nói “tìm năm review mới nhất của U”; ngôn ngữ và mô hình lưu trữ khác nhau.

### 5.2 Dữ liệu thật và ETL

Nguồn là [Amazon Review Data 2018 của UCSD](https://cseweb.ucsd.edu/~jmcauley/datasets/amazon_v2/). Dự án dùng `Movies_and_TV_5.json.gz` và `meta_Movies_and_TV.json.gz`. JSON Lines nghĩa là mỗi dòng một object; gzip là cách nén tệp.

Review có `reviewerID` (ai), `asin` (sản phẩm nào), `overall` (mấy sao), `reviewText`/`summary` (nội dung), `unixReviewTime` (thời gian), `vote` (lượt hữu ích), `verified` (dấu xác minh của nguồn), `style` (thuộc tính giao dịch, có thể chứa định dạng). Metadata có tên, thương hiệu, danh mục, giá, mô tả, liên kết sản phẩm.

`asin` là sản phẩm Amazon, không đảm bảo mỗi mã là một tác phẩm điện ảnh khác nhau. Hai bản đĩa của cùng phim có thể là hai sản phẩm. `also_view` là liên kết trang sản phẩm, không phải nhật ký phát phim. Sao cao có thể khen đĩa hoặc giao hàng, không chỉ nội dung phim.

5-core là thuộc tính của tập nguồn: mỗi người dùng và mỗi sản phẩm có ít nhất năm review liên quan. Sau lọc thiếu metadata và khử trùng, tập sử dụng không còn được bảo đảm giữ nguyên tính chất đó.

ETL = Extract (đọc nguồn), Transform (chuẩn hóa), Load (nạp CSDL). Trong code: đọc theo lô; giải mã ký tự HTML; chuẩn hóa giá, brand, danh mục, format; tạo SHA-256 từ JSON nguồn đã sắp khóa để nhận ra dòng trùng hệt. Hai review khác nội dung/thời gian nhưng cùng user–product vẫn có khóa riêng. Giá không biết là `null`, không phải 0 đồng.

Số đếm đã đối chiếu: **3.410.019 dòng review nguồn − 5.227 dòng không có metadata được giữ − 108.703 dòng trùng hệt = 3.296.089 dòng review**. Trong đó **150.464 dòng là bản sao** của cùng một review ở ấn bản khác của cùng phim (DVD/Blu-ray…), nên còn **3.145.625 review khác nhau** (xem `SUA_LOI_2026-11-14.md`). Có **60.109 mã sản phẩm**, gộp thành **59.395 tác phẩm**. MongoDB đang có **297.530 user tổng cộng**; báo cáo nhập nguồn ghi 297.529 user không phải demo ở lần nhập. Không nhầm tổng user hiện tại với user nguồn.

### 5.3 MongoDB và thống kê tính sẵn

`products`, `reviews`, `users` là ba collection chính. Một product không nhúng hàng nghìn review: nó giữ `stats` và tối đa 5 trích đoạn `top_reviews`; review đầy đủ ở collection riêng. Đây là cách giữ trang chi tiết gọn và đọc nhanh.

`stats.review_count`, `stats.avg_rating`, phân bố sao và cảm xúc là số liệu tính từ review bằng aggregation. Khi ghi demo, code tính lại theo sản phẩm/người dùng liên quan. `$merge` gộp thống kê mới và giữ `pagerank`/`community` đã tính.

Index giống mục lục: tốn dung lượng và chi phí ghi để đổi lấy khả năng tìm nhanh. Index `(reviewerID, timestamp)` phù hợp lấy lịch sử của một người theo thời gian. Text index phục vụ tìm theo từ; nó khác phép dò chuỗi bất kỳ. `explain` cho biết kế hoạch và số bản ghi/chìa khóa phải đọc.

Thực hành chỉ đọc trong công cụ MongoDB đang kết nối cổng 27028:

```javascript
db.products.findOne({asin: 'B00OV3VGP0'}, {title: 1, stats: 1});
db.reviews.find({asin: 'B00OV3VGP0'}, {reviewerID: 1, overall: 1, summary: 1})
  .sort({timestamp: -1}).limit(3);
db.reviews.find({reviewerID: 'A1435P5AMCPB3X'})
  .sort({timestamp: -1}).limit(20).explain('executionStats');
```

Trước khi chạy, kiểm tra đang dùng database `amazon_movies_tv`. Không chạy lại import/benchmark như một bài học nhập môn: chúng là tác vụ nặng, có thay đổi index hoặc dữ liệu tạm.

### 5.4 Neo4j và ý nghĩa đồ thị

Năm nhãn node: `User`, `Product`, `Category`, `Brand`, `Format`. Tám loại cạnh: `REVIEWED`, `IN_CATEGORY`, `SUBCATEGORY_OF`, `BY_BRAND`, `AVAILABLE_AS`, `ALSO_BOUGHT`, `ALSO_VIEWED`, `SIMILAR_TO`.

Ví dụ `(U)-[REVIEWED {rating:5, review_id:...}]->(P)` nói người U đã có một sự kiện review sản phẩm P. Một cặp U–P có thể có nhiều cạnh review khác ID. Khi xác định thích cho CF, code lấy **trung bình các review của cặp đó**, rồi so với ngưỡng 4.

```cypher
MATCH (p:Product {asin:'B00OV3VGP0'})
RETURN p.title, p.review_count, p.avg_rating;

MATCH (u:User {reviewerID:'A1435P5AMCPB3X'})-[r:REVIEWED]->(p:Product)
RETURN p.asin, p.title, r.rating
ORDER BY r.timestamp DESC LIMIT 5;
```

`MERGE` tìm hoặc tạo theo mẫu khóa; nó giúp nạp lại cùng review ID không tạo thêm sự kiện. Ràng buộc/index và cách chọn khóa vẫn quan trọng; chỉ dùng chữ MERGE không tự giải quyết mọi vấn đề đồng thời.

### 5.5 CF: từ tập sở thích đến điểm gợi ý

Code hiện dùng **lọc cộng tác theo người dùng**. Ví dụ minh họa tự tạo: U thích A, B, C; V thích A, B, D. Giao có 2 phần tử; hợp có 4. Jaccard = 2/4 = 0,5. Vector nhị phân tương ứng trên (A,B,C,D) là U=(1,1,1,0), V=(1,1,0,1). 0 ở đây chỉ là không có tín hiệu thích trong biểu diễn, không kết luận chắc chắn người đó ghét sản phẩm.

Trong code: lấy tối đa 100 sản phẩm thích gần nhất của U; tìm người khác cùng thích ít nhất 2 sản phẩm; giữ tối đa 300 ứng viên theo số chung rồi chọn 30 láng giềng theo Jaccard. Do giới hạn này, đây là cách tìm láng giềng có cắt giảm ứng viên, không phải so sánh toàn bộ mọi cặp người dùng.

Điểm ứng viên i:

`score(U,i) = mean(U) + Σ[sim(U,V) × (rating(V,i) − mean(V))] / (Σ sim(U,V) + 32)`.

Chỉ các ứng viên chưa được U review và được láng giềng chấm trung bình ≥4 được xét. Trung bình của láng giềng giúp giảm khác biệt giữa người dễ và khó chấm điểm. λ=16 làm mức điều chỉnh nhỏ khi ít bằng chứng. Giá trị này được chọn trên validation (14/11, sau khi gộp ấn bản; trước đó là 32); trọng số Hybrid thì đang cố định.

Tính tay: mean(U)=4; chỉ V có sim=0,5, mean(V)=3,5 và rating(V,D)=5. Khi λ=16, điểm D = 4 + 0,5×(5−3,5)/(0,5+16) ≈ **4,0455**. Khi λ=0, điểm là 5,5: cho thấy công thức không được chặn trong khoảng 1–5 và không nên gọi điểm xếp hạng là xác suất hoặc số sao được bảo đảm.

[GDS Node Similarity](https://neo4j.com/docs/graph-data-science/current/algorithms/node-similarity/) cũng có thể tính tương đồng trên tập hàng xóm. Nhưng `SIMILAR_TO` do GDS ghi là kết quả chạy trước, còn CF trực tuyến của dự án tự tìm láng giềng bằng truy vấn Cypher. Hai phần có vai trò khác nhau; CF hiện không trực tiếp đọc cạnh SIMILAR_TO để tính điểm.

### 5.6 Bốn phương pháp còn lại

**Related:** từ 5 review ≥4 sao gần nhất, đi theo ALSO_BOUGHT/ALSO_VIEWED 1–2 bước. Điểm cho một seed bằng số đường đi chia số bước ngắn nhất, sau đó cộng qua seed. Nếu có 3 đường tới X và bước ngắn nhất là 2 thì điểm là 1,5. Đây là gợi ý dựa liên kết sản phẩm, chưa phải item-item CF tính từ ma trận đánh giá.

**Content:** lấy tối đa 20 sản phẩm thích; tìm chung danh mục sâu hoặc Brand; Format bổ sung điểm. Điểm = số seed khớp + 0,2×số thuộc tính chung. Không dùng embedding hay Cosine trong triển khai này. Cùng format đơn thuần không đủ tạo ứng viên nếu không khớp danh mục/Brand theo truy vấn.

**Popular:** sản phẩm có ít nhất 5 review, điểm `(n×avg + 10×mean_chung)/(n+10)`. Trong code mean chung là trung bình các điểm trung bình sản phẩm, không phải trung bình có trọng số của toàn bộ review. Cách làm trơn tránh để sản phẩm rất ít review 5 sao tự động vượt lên đầu. Đây là baseline và cách dự phòng khi phương pháp được yêu cầu không trả ứng viên; nếu trả ít hơn K nhưng vẫn có kết quả, code chưa tự bù cho đủ K.

**Hybrid:** chuẩn hóa từng thành phần bằng `(score−min)/(max−min)`, rồi cộng **0,45 CF + 0,25 Related + 0,20 Content + 0,10 cảm xúc**. Nếu mọi điểm của một thành phần bằng nhau, code cho chúng cùng giá trị 1. Thiếu ứng viên trong thành phần nào thì không được điểm của thành phần đó. Các trọng số đang đặt cố định; không được nói đã học tối ưu từ dữ liệu.

**VADER:** dùng từ điển và luật, không huấn luyện mô hình cảm xúc mới trong dự án. Compound ≥0,05 là tích cực, ≤−0,05 là tiêu cực, còn lại trung tính. Review không có nội dung được ghi unavailable. Hybrid dùng **tỷ lệ review có nhãn positive trong các review có nhãn cảm xúc hợp lệ**, không dùng trực tiếp compound của một review. Đối chiếu với sao chỉ là kiểm tra sự đồng thuận hai tín hiệu, không phải accuracy trên bộ nhãn con người. [Mô tả của tác giả VADER](https://github.com/cjhutto/vaderSentiment).

### 5.7 Đánh giá: phải biết mẫu số

Mỗi người có ≥5 review: sắp theo `(timestamp, review_id)`, lấy khoảng 80% cũ làm Train và 20% mới làm Test. Người ít hơn 5 review được giữ toàn bộ vào Train. Relevant là sản phẩm trong Test được chấm ≥4 và chưa có trong Train. Chọn ngẫu nhiên 1.200 người test và 600 người validation khác nhau trong nhóm đủ điều kiện, seed=42.

Validation chọn λ và cách chuẩn hóa Hybrid. Sau khi chọn, tập test báo kết quả. Code chạy bản Python trên tương tác Train; parity chạy bản Python và Cypher trên dữ liệu vận hành đầy đủ để kiểm tra Top-K có khớp trên mẫu. Parity không phải điểm chất lượng gợi ý và không chứng minh mọi trường hợp đều tương đương.

Ví dụ tự tạo: K=5, gợi ý [A,B,C,D,E], relevant={A,C,Z}. Hit=2.

- Precision@5 = 2/5 = 0,4: có bao nhiêu kết quả đúng trong 5 vị trí yêu cầu.
- Recall@5 = 2/3 ≈ 0,667: tìm lại bao nhiêu sản phẩm relevant đã giữ lại.
- DCG = 1/log2(2) + 1/log2(4) = 1,5.
- IDCG = 1/log2(2) + 1/log2(3) + 1/log2(4) ≈ 2,1309.
- NDCG@5 ≈ 0,704: thưởng việc kết quả đúng nằm trên cao.
- Hit@5 = 1 vì có ít nhất một kết quả đúng.

Khi danh sách ngắn hơn K, code vẫn chia Precision cho K. Không gọi Precision@10=0,0108 (Hybrid, lần chạy 14/11) là “độ chính xác 1,08% của toàn hệ thống”; đó là trung bình số lần khớp nhãn giữ lại trong 10 vị trí theo giao thức cụ thể.

Giới hạn phải tự nói được: metadata liên kết là ảnh chụp không chia thời gian; formats tổng hợp cả review Train/Test; Train của người này có thể mới hơn Test của người kia; không có nhãn sở thích cho mọi sản phẩm chưa review; chỉ một lần chia và chưa có khoảng tin cậy. Vì vậy kết quả ngoại tuyến chưa chứng minh người dùng thật hài lòng hơn hay thuật toán luôn tốt nhất.

### 5.8 Benchmark và phân tích đồ thị

Trước/sau index phải cùng truy vấn, cùng tập dữ liệu và cùng cách đo. Dự án bỏ lượt đầu và lấy trung vị các lượt sau. Đọc thêm số document/key phải duyệt, kế hoạch COLLSCAN/IXSCAN hoặc Neo4j PROFILE. “0 ms” ở độ phân giải mili giây không có nghĩa là thực thi tức thời.

Mẫu truy vấn quan hệ và mẫu thống kê cho kết quả nhanh/chậm khác nhau giữa hai CSDL. Không suy rộng một user/phim trên một máy thành kết luận cho mọi ứng dụng. Ở benchmark Neo4j theo quy mô, tập review tạm thay đổi nhưng `avg_rating`/`review_count` của Product vẫn lấy từ toàn bộ dữ liệu; phải nói đúng phạm vi đó.

PageRank đo mức quan trọng trong mạng liên kết sản phẩm, không phải chất lượng nghệ thuật. Louvain nhóm sản phẩm theo cấu trúc kết nối, không phải phân loại bằng nhãn thể loại có sẵn. TF-IDF trong `keywords.py` phục vụ mô tả từ khóa review; nó không phải thuật toán tạo danh sách gợi ý Content trong code hiện tại.

### 5.9 Đồng bộ và lỗi

MongoDB ghi review trước với version và synced=false. Sau khi Neo4j nhận được sự kiện, MongoDB chỉ xác nhận synced=true nếu version chưa đổi. Neo4j có kiểm tra version của cạnh để bản cũ không ghi đè review mới. Nếu Neo4j lỗi, API trả 202 và worker thử lại. Đây là **nhất quán cuối cùng**, không phải một giao dịch nguyên tử xuyên hai CSDL.

Ví dụ: worker đọc version 1; người dùng sửa thành version 2; worker hoàn tất version 1. Bộ lọc `_id + version=1` không được phép đánh dấu version 2 đã đồng bộ. Tuy nhiên snapshot thống kê của node và các cache vẫn có giới hạn cập nhật; không khẳng định mọi màn hình luôn tức thời.

## 6. Thực hành nhanh qua API

Khởi động theo README khi cần, rồi mở các địa chỉ này trên máy:

- `http://127.0.0.1:5055/api/health`: hai CSDL có kết nối được không?
- `http://127.0.0.1:5055/api/products/B00OV3VGP0`: John Wick; chỉ ra asin, title, review_count, avg_rating.
- `http://127.0.0.1:5055/api/reviews?asin=B00OV3VGP0&limit=3`: ba sự kiện review.
- `http://127.0.0.1:5055/api/recommendations/A1435P5AMCPB3X?method=hybrid&limit=5`: chỉ ra input, score, components, product.
- `http://127.0.0.1:5055/api/recommendations/NGUOI_DUNG_MOI?method=hybrid`: giải thích fallback.
- `http://127.0.0.1:5055/api/graph/ego?asin=B00OV3VGP0`: nhận ra nodes và edges.

Chỉ đọc, chưa cần tự viết review trong buổi đầu. Không gửi `.env` lên chat hoặc cho người khác; dùng thông tin kết nối cục bộ khi thực hành Neo4j Browser.

## 7. Hai mươi câu vấn đáp và ý trả lời

Tự trả lời 45–90 giây/câu trước khi nhìn cột phải. Khi bị hỏi “ở đâu trong code?”, mở đúng tệp thay vì đọc thuộc README.

| Câu hỏi | Ý trả lời cần có |
|---|---|
| 1. Đầu vào/đầu ra? | Phân biệt dữ liệu xây dựng với request user/method/K; output Top-K sản phẩm và điểm |
| 2. Database khác MongoDB thế nào? | Database là dữ liệu có tổ chức; MongoDB là DBMS |
| 3. Vì sao hai CSDL? | Document cho nội dung/thống kê, graph cho quan hệ; vẫn làm được bằng một hệ, có chi phí đồng bộ |
| 4. Một asin là một bộ phim duy nhất? | Là sản phẩm Amazon, có thể nhiều phiên bản một tác phẩm |
| 5. Vì sao 3,41 triệu còn 3,296 triệu review? | Lọc metadata và khử dòng trùng hệt; nêu phép trừ và báo cáo import |
| 6. Cùng user–asin có được nhiều review? | Có; sự kiện khác nhau giữ ID riêng, CF lấy trung bình cặp |
| 7. Dữ liệu đi từ đâu tới đâu? | Vẽ luồng gzip → MongoDB → Neo4j → asin/score → MongoDB → API |
| 8. Neo4j tắt lúc ghi review? | MongoDB giữ lại, 202, synced=false, worker thử lại; nhất quán cuối cùng |
| 9. CF theo user hay item? | Theo user; sở thích ≥4, Jaccard, láng giềng, điểm có mean và shrinkage |
| 10. Jaccard của {A,B,C} và {A,B,D}? | Giao 2/hợp 4 = 0,5; biết giải thích vector nhị phân |
| 11. λ=16 ở đâu ra? | Grid validation 600 người, chọn λ nhỏ nhất đạt ≥99% NDCG tốt nhất |
| 12. Hybrid 0,45… đã tối ưu chưa? | Trọng số cố định; chỉ λ và kiểu chuẩn hóa được chọn trên validation |
| 13. Điểm gợi ý 0,7 có nghĩa 70% thích? | Không; là điểm tổng hợp/xếp hạng, chưa hiệu chỉnh xác suất |
| 14. GDS SIMILAR_TO có trực tiếp tạo CF không? | CF live tự truy vấn Jaccard; GDS là snapshot dùng cho phần hiển thị tương đồng |
| 15. VADER accuracy 84%? | Chưa có nhãn chuẩn con người; đó là tỷ lệ đồng thuận với cực tính số sao theo định nghĩa báo cáo |
| 16. Precision/Recall khác nhau? | Mẫu số K so với số relevant giữ lại; tự tính ví dụ nhỏ |
| 17. Train/Test đã hết rò rỉ chưa? | Chưa; metadata, format và thời gian giữa người dùng là hạn chế |
| 18. Neo4j luôn nhanh hơn? | Không; tùy truy vấn, index, phần cứng, cache; đưa hai ví dụ đối chứng |
| 19. PageRank cao là phim hay? | Chỉ quan trọng trong đồ thị liên kết; không chứng minh hay/phù hợp cá nhân |
| 20. Bước cải tiến tiếp theo? | Cắt thời gian toàn cục, format chỉ từ Train, đánh giá nhiều lần/CI; sau đó tối ưu ứng viên/cache và đồng bộ |

## 8. Bắt đầu ngay: bài 1 trong 20 phút

Đọc câu: **“Người U chấm sản phẩm P 5 sao.”**

1. Đây là một thông tin, tức dữ liệu.
2. Hàng triệu thông tin tương tự trong tệp Amazon tạo thành dataset.
3. Nhóm tổ chức chúng thành reviews/products/users trong một database.
4. MongoDB là phần mềm giúp lưu, tìm và thống kê database đó.
5. Neo4j biểu diễn quan hệ U → REVIEWED → P để khai thác các liên kết.

Tự trả lời bằng lời của mình, không dùng câu mẫu:

1. Trong đề tài, tệp Amazon, database và MongoDB khác nhau ở điểm nào?
2. Với câu U chấm P 5 sao, đâu là người, sản phẩm và quan hệ?
3. Nếu chưa có lịch sử của U, hệ thống còn cách gợi ý nào đang được code?

Đạt bài 1 khi tự giải thích được ba câu và nêu một lý do cần CSDL với hàng triệu review. Sau đó mới học bài 2: một document MongoDB và cách đọc dữ liệu của chính dự án.
