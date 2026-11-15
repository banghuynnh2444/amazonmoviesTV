# REST API và giao diện web

Địa chỉ mặc định: `http://127.0.0.1:5055`. `GET /` trả giao diện web (HTML/CSS/JavaScript thuần, Chart.js, vis-network); mọi dữ liệu trên giao diện lấy qua các API dưới đây. MongoDB 8.3 lưu phim, người dùng, review; Neo4j 5.26 + GDS 2.13.4 lưu đồ thị và tính gợi ý.

Website có hai khu với hai loại tài khoản:

- **Người dùng** (`#/`, `#/search`, `#/movie/…`, `#/for-you`, `#/account`, `#/reviewer/…`): ai cũng xem được; đăng ký tài khoản thường để chấm điểm, viết/sửa/xóa đánh giá, bình chọn hữu ích và nhận gợi ý riêng.
- **Quản trị** (`#/admin/…`): tình trạng CSDL, đối soát, phân tích thuật toán, đồ thị, thống kê, thực nghiệm. Đăng nhập bằng tài khoản quản trị cấu hình trong `.env` (`python -m amazon_movies create-admin` sinh mật khẩu ngẫu nhiên, không in ra màn hình). Các API ở mục "Khu quản trị" trả **401** khi chưa đăng nhập và **403** với token của tài khoản thường.

Mọi số liệu "theo tác phẩm" gộp các ấn bản (DVD, Blu-ray, Region Free…) của một phim và chỉ tính mỗi review một lần (bỏ dòng `is_copy`).

## Tài khoản

| Phương thức | Đường dẫn | Nội dung |
|---|---|---|
| GET | /api/health | Tình trạng hai CSDL; 503 khi một hệ lỗi |
| POST | /api/auth/register | `username` (3–32 ký tự a–z, 0–9, _), `password` (10–128 ký tự), `display_name`; trả `role='user'`, `reviewerID` tiền tố `DEMO_` và token. Không cho đặt trùng tên tài khoản quản trị |
| POST | /api/auth/login | `username`, `password`; trả `role` = `user` hoặc `admin` và token (hết hạn sau 24 giờ) |
| GET | /api/auth/me | Thông tin tài khoản thường đang đăng nhập |

## Khu người dùng

| Phương thức | Đường dẫn | Nội dung |
|---|---|---|
| GET | /api/home | Phim được yêu thích nhất (số review ≥ 4 sao theo tác phẩm), điểm cao nhất (Bayesian, ≥ 5 review), 18 thể loại, số tác phẩm/review/người xem |
| GET | /api/facets | `genres` (thể loại thật: con của "Genre for Featured Categories" và vài nhánh thể loại cấp 1), `categories` (mọi danh mục ≥ 30 tác phẩm), `formats`, khoảng giá |
| GET | /api/products | Mỗi tác phẩm một dòng (ấn bản đại diện). `q` (Text Index trên tên + mô tả), `category`, `format`, `min_price`, `max_price` (theo ấn bản rẻ nhất), `sort` = relevance / reviews / rating / price_asc / price_desc, `page`, `limit` ≤ 100 |
| GET | /api/products/{asin} | Metadata của ấn bản; `work`, `work_title`, `editions` (các ấn bản cùng tác phẩm, định dạng, giá), `price_any`, `work_stats` (số review, điểm TB, phân bố sao, cảm xúc theo tác phẩm) |
| GET | /api/products/{asin}/keywords | Từ khóa TF-IDF trong tối đa 500 review hữu ích nhất, tách theo toàn bộ / tích cực / tiêu cực |
| GET | /api/products/{asin}/related | `steps` = 1 hoặc 2: tác phẩm mua/xem cùng qua ALSO_BOUGHT / ALSO_VIEWED, tính từ ấn bản đại diện, bỏ chính tác phẩm đó |
| GET | /api/reviews | `q` (Text Index), `work` (mọi ấn bản của tác phẩm, bỏ bản sao), `asin`, `reviewerID`, `sentiment`, `sort` = relevance / recent / helpful, `page`, `limit` ≤ 100; mỗi review kèm `product_title` và `display_name` |
| POST | /api/reviews | Cần đăng nhập. `asin`, `overall` nguyên 1–5, `summary` ≤ 500 ký tự, `reviewText` ≤ 20.000 ký tự (có thể để trống: chỉ chấm sao). Mỗi người một đánh giá cho một tác phẩm: lần thứ hai trả **409** kèm `review_id` của đánh giá cũ |
| PUT | /api/reviews/{review_id} | Chỉ chủ tài khoản sửa đánh giá của mình |
| DELETE | /api/reviews/{review_id} | Chủ tài khoản xóa đánh giá: xóa REVIEWED trong Neo4j trước, rồi MongoDB, rồi tính lại thống kê. Neo4j lỗi → **503**, MongoDB giữ nguyên |
| POST | /api/reviews/{review_id}/helpful | Mỗi tài khoản bình chọn một lần; không tự bình chọn đánh giá của mình |
| GET | /api/users/{reviewerID}/profile | Trang công khai của một người đánh giá: tên hiển thị, số review (không tính bản sao), lịch sử (`page`, `limit`). Không trả tên đăng nhập |
| GET | /api/me/recommendations | Cần đăng nhập. Gợi ý lai cho chính mình, mỗi phim kèm `reasons` (ví dụ "Thường được mua/xem cùng “X”", "3 người có gu giống bạn đã chấm phim này từ 4 sao"); `rated`, `needs_more_ratings` (< 3 phim đã chấm), `fallback_to_popular` |
| GET | /api/me/to-rate | Cần đăng nhập. Phim phổ biến chưa chấm để "chấm nhanh" |

## Khu quản trị (cần token quản trị)

| Phương thức | Đường dẫn | Nội dung |
|---|---|---|
| GET | /api/admin/overview | Tình trạng hai CSDL, số lượng (mã sản phẩm, tác phẩm, dòng review, bản sao, review khác nhau, người dùng thật/tài khoản web), đối soát trực tiếp Product/User/REVIEWED bằng count store, hàng chờ đồng bộ, tóm tắt gộp ấn bản, tham số gợi ý đang dùng, thời điểm cập nhật các tệp trong reports/ |
| POST | /api/admin/verify | Chạy đối soát đầy đủ (`graph.verify`), ghi lại reports/buoi2_reconciliation.json |
| GET | /api/recommendations/{reviewerID} | `method` = hybrid / collaborative / related / content / popular, `limit` ≤ 50. Trả `items` (asin, score, support, components và via với hybrid, product), `fallback_to_popular`, `elapsed_ms`, `cached` |
| GET | /api/users/sample | Một số người dùng thật (30–120 review) để thử |
| GET | /api/users/{reviewerID}/similar | 10 người dùng tương đồng: SIMILAR_TO (GDS) nếu có, nếu không thì tính trực tiếp bằng Cypher ở mức tác phẩm |
| GET | /api/graph/ego | Đồ thị con quanh `asin` hoặc `user` cho vis-network; người dùng hiện tên công khai (tên chung chung như "Amazon Customer" kèm 6 ký tự cuối mã) |
| GET | /api/analytics/communities | Kết quả PageRank/Louvain, hoặc danh sách phim của `?community=<id>` |
| GET | /api/statistics | Phân bố sao, cảm xúc, cảm xúc × số sao, xu hướng theo tháng, thể loại, định dạng — trên review khác nhau (`?refresh=1` để tính lại) |
| GET | /api/experiments | Nội dung các tệp kết quả trong reports/: đánh giá gợi ý, hiệu năng index, so sánh hai CSDL, PageRank/Louvain, Node Similarity, đối soát, gộp ấn bản |

## Ghi chú

- Thao tác ghi gửi `Authorization: Bearer <token>`. Mật khẩu tài khoản thường được băm bằng Werkzeug. Không nhận reviewerID do client tự khai cho thao tác ghi. Token quản trị không dùng được để viết đánh giá.
- 201 nghĩa là đánh giá đã lưu và đồng bộ sang Neo4j ngay; 202 nghĩa là MongoDB đã lưu, Neo4j đang chờ đồng bộ lại (worker `python -m amazon_movies sync --watch`). Không gửi lại để thử lại.
- Ghi đánh giá chỉ cập nhật các trường thống kê review của phim và của tác phẩm; PageRank và cộng đồng do GDS ghi được giữ nguyên. Xóa đánh giá cuối cùng của một phim đưa thống kê về 0.
- Kết quả gợi ý được lưu đệm 15 phút theo người dùng và bị xóa khi người đó ghi, sửa hoặc xóa đánh giá.
- `vote` là số hữu ích hiển thị; `source_vote` giữ số gốc, `demo_vote_count` tách lượt bình chọn trên web khỏi dữ liệu nghiên cứu.
- VADER chỉ xử lý tiếng Anh: đánh giá tiếng Việt được gắn nhãn `unsupported_language`, không bị xếp sai thành tích cực/tiêu cực. Bảng IDF cho từ khóa dựng bằng `python -m amazon_movies keyword-idf`.

Ví dụ PowerShell (tài khoản thường):

```powershell
$base = 'http://127.0.0.1:5055'
$registration = @{username='bang_demo';password='<mật khẩu của bạn>';display_name='Bằng'} | ConvertTo-Json
$account = Invoke-RestMethod -Method Post -Uri "$base/api/auth/register" -ContentType 'application/json' -Body $registration
$headers = @{Authorization="Bearer $($account.token)"}
$review = @{asin='B00OV3VGP0';overall=5;summary='Great film';reviewText='I love this wonderful film.'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/api/reviews" -Headers $headers -ContentType 'application/json' -Body $review
Invoke-RestMethod "$base/api/me/recommendations" -Headers $headers
```
