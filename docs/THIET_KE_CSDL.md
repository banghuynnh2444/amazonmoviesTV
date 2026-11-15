# Thiết kế CSDL — buổi 1–3

Tên đề tài giữ theo thuyết minh: **Xây dựng hệ thống gợi ý phim cá nhân hóa và phân tích đánh giá người dùng trên dữ liệu Amazon Movies & TV, sử dụng MongoDB và Neo4j.**

Nhóm: **Huỳnh Công Bằng — 4654100001; Lê Minh Thuận — 4654100012.**

## Luồng dữ liệu

Amazon gzip JSON Lines → chuẩn hóa theo lô + VADER → MongoDB → Neo4j → mã asin và điểm gợi ý → lấy chi tiết từ MongoDB → REST API. MongoDB là nguồn nghiệp vụ chính. Hai CSDL chỉ nhận kết nối từ máy cục bộ.

## Phần của Bằng

| Collection | Khóa | Nội dung và chỉ mục |
|---|---|---|
| products | `_id = asin` | title, description, brand, category_paths, categories, price, images, formats, also_buy, also_view; **work** (asin của ấn bản đại diện), **primary**, **work_size**, **editions** và **price_any** (trên ấn bản đại diện); brand_raw/title_raw giữ giá trị gốc khi làm sạch; text index title/description; categories/price; review_count; work; primary + stats.work_positive |
| reviews | `_id = review_id` | reviewerID, asin, **work**, overall, reviewText, summary, vote, verified, style, timestamp, review_date, sentiment, version, synced, **is_copy**/**copy_of** (bản sao của cùng một review ở ấn bản khác), **dup_group** (nhóm review giống hệt nhau); user/time, asin/time, asin/vote, work/is_copy, reviewerID/is_copy, text index |
| users | `_id = reviewerID` | tên hiển thị, thống kê; tài khoản demo có username và password_hash; unique username áp dụng riêng tài khoản demo |
| helpful_votes | `_id` tự sinh; unique(review_id, reviewerID) | Bảng phụ chống bình chọn hữu ích lặp |
| jobs | tên tác vụ | Trạng thái ETL và kết quả của lần chạy |

Computed Pattern: products.stats lưu số review, điểm trung bình, phân bố sao và nhãn cảm xúc của từng ấn bản; ấn bản đại diện còn lưu stats.work_reviews, work_avg, work_positive, work_stars, work_sentiment của cả tác phẩm (bỏ bản sao); users.stats lưu số review (không tính bản sao) và điểm trung bình. Subset Pattern: products.top_reviews chỉ nhúng tối đa 5 trích đoạn review hữu ích nhất.

**Ấn bản và tác phẩm (buổi 6).** Amazon hiển thị chung review cho mọi ấn bản (DVD, Blu-ray, Region Free…) của một phim, nên cùng một review (cùng người, ngày, số sao, tiêu đề, 200 ký tự đầu) xuất hiện ở nhiều asin. Hai asin là ấn bản của cùng tác phẩm khi chung ≥ 80% review của mã ít review hơn và ≥ 3 review; các cặp nối với nhau bằng union-find. Kết quả: 694 tác phẩm có từ 2 ấn bản (1.408 mã), 59.395 tác phẩm; 150.464 dòng bản sao (`is_copy`) trong 3.296.089 dòng, còn 3.145.625 review khác nhau. Dòng bản sao không bị xóa (trang từng ấn bản vẫn đủ review) nhưng không được tính trong thống kê tác phẩm, người dùng, dashboard và gợi ý. Ngưỡng 80% giữ các phần/mùa khác nhau của series là tác phẩm riêng; 197.946 dòng giống hệt nhau giữa các tác phẩm đó (người dùng dán lại cùng một bài) được giữ và đánh dấu `dup_group`.

**Làm sạch bổ sung (buổi 6).** 2.743 giá trị Brand rác (Various 1.605, "." 537, n/a 138, "-" 132, "*" 92, None 67…) đưa về rỗng; 855 tiêu đề lẫn thẻ HTML được làm sạch. Với phim, trường brand của Amazon chủ yếu là tên diễn viên chính (John Wayne, Tom Hanks…), không phải hãng phát hành; giao diện ghi là "Diễn viên / thương hiệu". 55 mã có main_cat khác "Movies & TV" (Sports & Outdoors 30, Books 6…) vẫn giữ vì nằm trong tệp review 5-core Movies & TV của nguồn.

Raw review không có mã review riêng. review_id là SHA-256 của JSON nguồn được chuẩn hóa thứ tự khóa. Bản ghi trùng hệt có cùng khóa và được upsert một lần; hai review khác nhau nhưng chung người dùng–sản phẩm vẫn là hai sự kiện. Không dùng cặp này làm khóa duy nhất của review.

Giá không hợp lệ hoặc khoảng giá được giữ `price_raw` và đặt price=null. Ký tự HTML được giải mã. Description dạng mảng được ghép thành văn bản. Format trích từ khóa `Format:` trong style. Trường rỗng không được biến thành thông tin giả. Schema Validation kiểm tra kiểu và miền giá trị.

## Phần của Thuận

| Node | Khóa duy nhất |
|---|---|
| User | reviewerID |
| Product | asin |
| Category | SHA-256 của toàn bộ đường dẫn danh mục |
| Brand | name |
| Format | name |

8 loại quan hệ đúng phạm vi đề tài:

1. User → REVIEWED → Product: review_id, rating, timestamp, helpful, verified, sentiment, version, is_demo, **copy** (bản sao ở ấn bản khác; mọi truy vấn gợi ý bỏ qua).

Product còn có `work`, `primary`, `work_reviews`, `work_avg` (index product_work); User có `name` (tên công khai trên Amazon, để đồ thị hiện tên thay vì chỉ mã — 12.163 người tên "Amazon Customer" và 2.051 "Kindle Customer" được hiển thị kèm 6 ký tự cuối của mã).
2. Product → IN_CATEGORY → Category.
3. Category → SUBCATEGORY_OF → Category.
4. Product → BY_BRAND → Brand.
5. Product → AVAILABLE_AS → Format.
6. Product → ALSO_BOUGHT → Product.
7. Product → ALSO_VIEWED → Product.
8. User → SIMILAR_TO → User: kết quả tính toán Node Similarity, score.

Mỗi review nguồn hợp lệ sau khử trùng hệt có một REVIEWED, cho phép đối soát số lượng review giữa hai CSDL. Nội dung review dài không đưa vào Neo4j. Quan hệ sản phẩm liên quan chỉ được tạo nếu cả hai đầu có metadata và thuộc tập review đang nhập. AVAILABLE_AS phản ánh định dạng quan sát trong review lịch sử. Category là danh mục sản phẩm; Brand giữ nhãn nguồn — với phim chủ yếu là diễn viên chính, không phải hãng phát hành.

Mọi phương pháp gợi ý làm việc ở mức tác phẩm: bỏ REVIEWED có `copy = true`, gộp ứng viên theo `Product.work`, chỉ gợi ý ấn bản đại diện và không gợi ý lại tác phẩm đã review ở bất kỳ ấn bản nào. CF tính trung bình theo mỗi cặp người dùng–tác phẩm trước khi xác định sở thích ≥ 4 sao; tìm người có ít nhất 2 tác phẩm yêu thích chung; Jaccard xác định trọng số láng giềng (30 người). Điểm = trung bình người dùng mục tiêu + Σ sim·(sao − trung bình láng giềng) / (Σ sim + λ), λ = 16 chọn cùng ngưỡng láng giềng trên tập validation: λ co điểm của phim chỉ ít láng giềng thích về trung bình người dùng. Cold start (và phương pháp mốc) dùng Phổ biến = số review ≥ 4 sao của tác phẩm; danh sách "Điểm cao nhất" trên trang chủ dùng điểm Bayesian. Hằng số và công thức nằm chung trong `algorithms.py` cho cả Cypher và bản Python dùng để đánh giá.

Item-based khai thác ALSO_BOUGHT/ALSO_VIEWED một hoặc hai bước; content-based dùng danh mục, Brand, định dạng. CF chỉ đề xuất tác phẩm có ít nhất 2 láng giềng cùng thích (chọn trên validation; không lọc thì láng giềng chỉ thích vài phim kéo vào phim lạc đề). Hybrid chia điểm từng thành phần cho điểm lớn nhất (chọn trên validation: NDCG@10 0,0333 so với 0,0307 của min–max; vì điểm CF có cộng trung bình người dùng nên thành phần CF gần như "có/không được CF đề xuất") rồi kết hợp CF=0,45; liên quan=0,25; nội dung=0,20; cảm xúc=0,10. Trọng số là cấu hình cố định, chưa được tối ưu.

GDS 2.13.4 ghép Neo4j 5.26.33. `gds-similarity --min-reviews 5 --degree-cutoff 3` có bước ước lượng RAM (giới hạn mặc định 4 GiB); lần chạy toàn bộ (14/11, theo tác phẩm, bỏ bản sao) ghi 4.884.618 SIMILAR_TO cho 246.055 người dùng (82,7%). Projection được xóa sau khi dùng. PageRank (hội tụ sau 113 vòng), Louvain và đánh giá Precision/Recall/NDCG: xem `docs/TIEN_DO_BUOI_4.md`.

## Đồng bộ và đối soát

1. Ghi review vào MongoDB cùng version và synced=false.
2. Tính VADER cho văn bản tiếng Anh; không có nội dung thì nhãn unavailable, không giả nhãn neutral.
3. Cập nhật thống kê product/user từ MongoDB (`$merge` gộp vào object `stats`, giữ PageRank/cộng đồng do GDS ghi).
4. MERGE đúng review_id trong Neo4j; cập nhật thuộc tính bằng SET.
5. Chỉ đánh dấu synced=true nếu version hiện tại vẫn bằng version vừa đồng bộ. Một cập nhật mới xảy ra đồng thời vẫn được giữ ở hàng chờ.
6. Khi Neo4j lỗi, API trả 202 và review được giữ trong MongoDB; `sync --watch` thử lại. Lỗi không được làm mất review.

Mức nhất quán là nhất quán cuối cùng. Worker đồng bộ hiện chạy đơn để tránh tác vụ cũ ghi đè tác vụ mới. Không được chạy nhiều worker sync đồng thời. Khi import lại metadata/đồ thị, tạm dừng API ghi và worker để thống kê không bị reset giữa lần nạp.

`verify` so sánh số Product, User, REVIEWED, số review_id lặp và hàng chờ. `verify --exhaustive` kiểm tra từng review_id theo lô. Đánh giá 80/20 loại review demo và chạy bản Python trên tương tác Train; catalog vẫn lấy metadata/format toàn bộ nên chưa độc lập thời gian hoàn toàn. Các truy vấn so sánh CSDL và thống kê sản phẩm có thể gồm dữ liệu demo hiện có; cần ghi rõ snapshot khi đo. `parity_check` kiểm tra Top-K của Python và Cypher trên mẫu người dùng, không chứng minh tương đương trên mọi dữ liệu.

## Nguồn

- https://cseweb.ucsd.edu/~jmcauley/datasets/amazon_v2/
- https://aclanthology.org/D19-1018/
- https://www.mongodb.com/docs/manual/
- https://neo4j.com/docs/cypher-manual/5/
- https://neo4j.com/docs/graph-data-science/current/installation/supported-neo4j-versions/
- https://github.com/cjhutto/vaderSentiment
