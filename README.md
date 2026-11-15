# Amazon Movies & TV — công việc buổi 1–6

**Sửa lỗi ngày 14/11/2026 (bản mới nhất):** xem `docs/SUA_LOI_2026-11-14.md` — gộp ấn bản DVD/Blu-ray thành tác phẩm, bỏ review bản sao gây rò rỉ khi đánh giá, chạy lại thực nghiệm (số liệu mới thay toàn bộ số cũ), làm sạch Brand/tiêu đề, VADER không gán nhãn review tiếng Việt, tách website thành khu người dùng và khu quản trị. Rà soát 13/11 (`docs/RA_SOAT_2026-11-13.md`) và các báo cáo cũ chỉ còn giá trị lịch sử; học từ đầu theo `docs/LO_TRINH_HOC_2_NGAY.md`.

**Huỳnh Công Bằng — 4654100001 · Lê Minh Thuận — 4654100012**

Tên đề tài giữ nguyên theo thuyết minh: **Xây dựng hệ thống gợi ý phim cá nhân hóa và phân tích đánh giá người dùng trên dữ liệu Amazon Movies & TV, sử dụng MongoDB và Neo4j.**

Mã nguồn này triển khai công việc của cả hai thành viên từ Buổi 1 đến Buổi 6: dữ liệu thật Amazon 2018, EDA, MongoDB, Neo4j + GDS, ETL theo lô, VADER, tìm kiếm, thống kê, gợi ý CF/mua-xem cùng/nội dung/lai, PageRank, Louvain, Node Similarity, đánh giá thực nghiệm (`Precision@10`, `Recall@10`, `NDCG@10`), đo hiệu năng index (10%/50%/100%), so sánh MongoDB vs Neo4j, website demo (`Chart.js` + `vis-network`) và Flask REST API tại `http://127.0.0.1:5055`.

Sản phẩm buổi 6:

- Báo cáo cuối kỳ: https://claude.ai/artifact/7ueR5VAtcxat4gsEMi8yjm — bản Word và PDF tại `D:\AmazonMoviesTV\tai_lieu\bao_cao\BAO_CAO_CUOI_KY_Amazon_MoviesTV.docx` / `.pdf`
- Tài liệu không phải code (báo cáo Word/PDF, thuyết minh đề tài, ảnh chụp website, gói mã nguồn nộp bài) nằm riêng ở `D:\AmazonMoviesTV\tai_lieu\`; thư mục `project\` chỉ chứa mã nguồn, truy vấn, kiểm thử, kết quả thực nghiệm (`reports\`) và tài liệu kỹ thuật (`docs\`).
- Slide thuyết trình: https://claude.ai/artifact/JbPa5mdzNty7bzQn8TCYmP
- Kịch bản demo: `docs/KICH_BAN_DEMO.md`; tổng hợp những gì đã sửa: `docs/TIEN_DO_BUOI_6.md`

## Mở lại dự án trên máy này

Tất cả tệp tải về, dữ liệu và nơi lưu CSDL đặt ở **D:\AmazonMoviesTV**. Mã nguồn bàn giao được sao chép vào **D:\AmazonMoviesTV\project**; bản đính kèm trong chat là cùng nội dung nguồn.

| Thành phần | Nơi lưu / địa chỉ |
|---|---|
| Review 5-core đầy đủ | D:\AmazonMoviesTV\data\raw\Movies_and_TV_5.json.gz |
| Metadata đầy đủ | D:\AmazonMoviesTV\data\raw\meta_Movies_and_TV.json.gz |
| Python và thư viện riêng | D:\AmazonMoviesTV\runtime\venv |
| MongoDB data | D:\AmazonMoviesTV\runtime\mongo-data |
| Neo4j + GDS + graph data | D:\AmazonMoviesTV\runtime\neo4j\neo4j-community-5.26.33 |
| Log xử lý dữ liệu | D:\AmazonMoviesTV\runtime\logs\full_pipeline.log |
| Bộ nhớ CSDL | Neo4j: page cache 3 GB, heap 4 GB (conf/neo4j.conf); MongoDB: WiredTiger cache 2 GB (scripts/start-local.ps1) |
| MongoDB | mongodb://127.0.0.1:27028 — database amazon_movies_tv |
| Neo4j Browser | http://127.0.0.1:7485 |
| Neo4j Bolt | bolt://127.0.0.1:7698 |
| REST API | http://127.0.0.1:5055 |

Thông tin đăng nhập Neo4j và khóa ký token API nằm trong `.env` cục bộ; không đưa tệp này lên Git hoặc gửi cho người khác. MongoDB chạy riêng bằng binary 8.3.11 đã có trên máy, không cài thêm Windows service hoặc thay CSDL của bài khác. Neo4j Community 5.26.33 và GDS 2.13.4 dùng Java 17 sẵn có tại D:\BigData\jdk17.

```powershell
cd D:\AmazonMoviesTV\project
.\scripts\start-local.ps1 -StartApi -StartSync
```

Kiểm tra nhanh:

```powershell
$python = 'D:\AmazonMoviesTV\runtime\venv\Scripts\python.exe'
& $python -m amazon_movies doctor
Invoke-RestMethod http://127.0.0.1:5055/api/health
Invoke-RestMethod 'http://127.0.0.1:5055/api/products?limit=3'
```

Không mở cổng ra Internet. Nếu Windows không cho chạy file PowerShell, dùng các lệnh Python bên dưới sau khi khởi động CSDL; không cần thay chính sách bảo mật máy để đọc hoặc dùng mã nguồn.

## Phân công và kết quả theo buổi

| Buổi | Huỳnh Công Bằng | Lê Minh Thuận | Minh chứng |
|---|---|---|---|
| 1 | EDA dữ liệu review/metadata, collection và schema | Neo4j, GDS, 5 loại node và 8 loại quan hệ | reports/buoi1_environment.json; buoi1_eda.json; docs/THIET_KE_CSDL.md |
| 2 | ETL theo luồng, chuẩn hóa, upsert MongoDB | Nạp node/quan hệ theo lô; kiểm tra khóa và số lượng | reports/buoi2_mongodb_import.json; buoi2_neo4j_import.json; buoi2_reconciliation.json |
| 3 | Text index, Aggregation, VADER, API review và đồng bộ | Cypher CF, liên quan 1–2 bước, nội dung, hybrid | queries/; amazon_movies/; reports/buoi3_queries_api.json; tests/ |
| 4 | Đo hiệu năng MongoDB (10%/50%/100%); 3 cặp truy vấn so sánh 2 CSDL | PageRank, Louvain; đánh giá Precision@10, Recall@10, NDCG@10; Neo4j PROFILE | reports/buoi4_graph_analytics.json; buoi4_evaluation.json; buoi4_index_benchmark.json; buoi4_db_comparison.json; docs/TIEN_DO_BUOI_4.md |
| 5 | Hoàn thiện Backend Flask REST API (`/api/home`, `/api/users/.../profile`, `/api/graph/ego`, tối ưu cache Dashboard, đồng bộ review real-time) | Xây dựng Frontend Website (`templates/index.html`, `static/styles.css`, `static/app.js`) với `Chart.js` và `vis-network` | amazon_movies/api.py; amazon_movies/templates/; amazon_movies/static/; reports/buoi5_web_ui.json; docs/TIEN_DO_BUOI_5.md |

**Trạng thái chạy thật:** xem `reports/RUN_STATUS.json`, `docs/TIEN_DO_BUOI_1_2_3.md`, `docs/TIEN_DO_BUOI_4.md` và `docs/TIEN_DO_BUOI_5.md`. `complete=true` chỉ được ghi sau khi nhập MongoDB, nhập Neo4j, đối soát và kiểm tra API thành công. Mọi tệp trong `reports/` là kết quả trên toàn bộ dữ liệu (kết quả chạy thử 10.000 dòng đã bỏ).

## Các lệnh xử lý dữ liệu

Chạy từ thư mục project; dùng biến `$python` ở trên.

```powershell
& $python -m amazon_movies download
& $python -m amazon_movies eda
& $python -m amazon_movies mongo-init
& $python -m amazon_movies graph-init
& $python -m amazon_movies import-mongo --workers 8
& $python -m amazon_movies import-graph --batch-size 2000
& $python -m amazon_movies verify
& $python -m amazon_movies verify --exhaustive
& $python -m amazon_movies serve
```

Hoặc chạy chuỗi công việc đầy đủ:

```powershell
& $python .\scripts\run_sessions_1_3.py --workers 8
```

ETL mặc định nhập toàn bộ dữ liệu, không giới hạn 100.000 hay 300.000 review. Có thể dùng `--limit 10000` để thử trên một database trống riêng bằng biến `MONGO_DATABASE`; không dùng giới hạn nhỏ để thay đổi quy mô một database đã có toàn bộ dữ liệu.

VADER chạy trong các worker xử lý song song; bộ đọc và hàng đợi đều giới hạn kích thước, không nạp cả tệp gzip vào RAM. Secondary index được dựng sau khi nhập hàng loạt. Nếu phiên xử lý bị ngắt, upsert theo ID ổn định cho phép chạy lại; việc chạy lại vẫn cần quét nguồn và có thể tính lại cảm xúc. Chưa có checkpoint để nhảy thẳng tới dòng gzip giữa tệp.

MongoDB chỉ giữ sản phẩm có tên hợp lệ và có review được giữ lại; graph chỉ tạo liên kết sản phẩm khi đủ cả hai đầu. Raw gzip được giữ nguyên. Ghi nhận riêng số dòng nguồn, dòng không có metadata hợp lệ và dòng trùng hệt; số dòng nguồn vì thế có thể lớn hơn số review sau làm sạch.

## Gợi ý và đồng bộ

```powershell
& $python -m amazon_movies recommend REPLACE_USER_ID --method collaborative
& $python -m amazon_movies recommend REPLACE_USER_ID --method related
& $python -m amazon_movies recommend REPLACE_USER_ID --method content
& $python -m amazon_movies recommend REPLACE_USER_ID --method hybrid
& $python -m amazon_movies sync
& $python -m amazon_movies sync --watch --interval 10
& $python -m amazon_movies gds-similarity --top-k 20
```

Hằng số và công thức của các phương pháp nằm chung trong `amazon_movies/algorithms.py`; `recommend.py` truyền chúng vào Cypher, còn phần đánh giá chạy bản Python 1-1 của cùng các truy vấn. Mọi phương pháp làm việc ở **mức tác phẩm**: các ấn bản (DVD, Blu-ray, Region Free…) của một phim được gộp, review bản sao giữa các ấn bản (`is_copy`) bị bỏ, chỉ gợi ý ấn bản đại diện và không gợi ý lại tác phẩm đã review ở bất kỳ ấn bản nào. CF dùng tối đa 100 tác phẩm thích gần nhất, xét tối đa 300 ứng viên láng giềng theo số tác phẩm chung (≥ 2) rồi lấy 30 người theo Jaccard; chỉ đề xuất tác phẩm có ít nhất 2 láng giềng cùng thích; điểm = điểm TB người dùng + Σ sim·(sao − điểm TB láng giềng) / (Σ sim + λ), λ = 16; cả hai tham số chọn trên tập validation. Content-based dùng tối đa 20 tác phẩm thích gần nhất, bỏ hai mức danh mục gốc quá chung; lưu ý trường Brand của Amazon với phim chủ yếu là tên diễn viên chính. Hybrid chuẩn hóa từng phương pháp bằng điểm / điểm lớn nhất (chọn trên validation, tốt hơn min–max) rồi cộng 0,45 CF + 0,25 mua/xem cùng + 0,20 nội dung + 0,10 cảm xúc. Phổ biến = số review ≥ 4 sao của tác phẩm; danh sách “Điểm cao nhất” trên trang chủ dùng điểm Bayesian.

GDS Node Similarity tạo SIMILAR_TO (Jaccard trên tác phẩm ≥ 4 sao, bỏ review bản sao), độc lập với CF tính tại thời điểm truy vấn: `gds-similarity --min-reviews 5 --degree-cutoff 3` ghi 4.884.618 quan hệ cho 246.055 người dùng (82,7%) trong khoảng 22 phút. Có bước ước lượng bộ nhớ (giới hạn mặc định 4 GiB) trước khi chạy; đồ thị GDS trong RAM được xóa sau khi dùng. Người dùng chưa có SIMILAR_TO được website tính láng giềng trực tiếp bằng Cypher.

Đọc `docs/API.md` để đăng ký tài khoản demo, tạo/sửa review và bình chọn. Khi Neo4j tạm lỗi, MongoDB giữ review và API trả 202; worker tự đồng bộ lại. Chỉ mở một worker sync. Neo4j không cho một review phiên bản cũ ghi đè phiên bản mới hơn; cờ synced cũng chỉ được xác nhận nếu version MongoDB còn khớp.

## Thực nghiệm buổi 4

```powershell
& $python -m amazon_movies keyword-idf          # bảng IDF cho từ khóa TF-IDF
& $python .\scripts\run_session4.py             # PageRank/Louvain → đánh giá 80/20 → index 10/50/100% → so sánh 2 CSDL
& $python -m amazon_movies verify                # đối soát số lượng hai CSDL
& $python .\scripts\verify_session3.py           # kiểm tra 5 phương pháp gợi ý và API buổi 3
& $python .\scripts\verify_web_ui.py             # kiểm tra 36 endpoint của website
```

- Đánh giá: mỗi người dùng 80% review cũ là Train, 20% mới là Test, tính ở mức tác phẩm và bỏ review bản sao; review giống hệt nhau của cùng người ở hai tác phẩm khác nhau (`dup_group`) không bị chia giữa Train và Test. 1.200 người kiểm thử và 600 người validation tách rời, chọn ngẫu nhiên trong 227.686 người đủ điều kiện. λ của CF và cách chuẩn hóa Hybrid được chọn trên validation; `parity_check` chạy cùng người dùng qua Cypher của website và bản Python để xác nhận hai bản trùng nhau (20/20 người, cả 5 phương pháp).
- Hiệu năng: cùng một truy vấn trước và sau khi tạo index, trên tập con theo thời gian thật ở cả hai CSDL (Neo4j dùng quan hệ tạm BENCH_REVIEWED, xóa sau khi đo).
- Nên chạy khi máy không có tác vụ nặng khác để số đo thời gian không bị nhiễu.

## Kiểm thử

```powershell
& $python -m pytest -q
$env:MOVIES_INTEGRATION='1'
& $python -m pytest -q
& $python .\scripts\verify_session3.py
```

Kiểm thử tích hợp dùng MongoDB **amazon_movies_tv_test_<mã ngẫu nhiên>** riêng cho từng bài; graph chỉ tạo ID TEST_/DEMO_ được dọn sau mỗi bài. Các bài kiểm tra gồm: trùng review nguồn và sự kiện khác nhau cùng cặp, giá thiếu, HTML, VADER, chuẩn hóa điểm hybrid, đăng nhập, ghi/sửa, bình chọn không lặp, cờ phiên bản, chống ghi đè cũ, phục hồi khi Neo4j lỗi và tính nhất quán khi review cùng timestamp. Không dùng dữ liệu kiểm thử giả để báo cáo số liệu Amazon.

## Cài lại trên máy khác

1. Cài Python ≥3.11, MongoDB Community, Java 17/21, Neo4j Community 5.26 và GDS 2.13 tương thích; hoặc đổi cấu hình cho phiên bản đã kiểm tra khác.
2. Tạo môi trường riêng: `python -m venv D:\AmazonMoviesTV\runtime\venv`.
3. Cài gói từ thư mục project: `python -m pip install -e ".[test]"` trong môi trường đó; `requirements-lock.txt` lưu toàn bộ phiên bản đã chạy trên máy này.
4. Sao chép `.env.example` thành `.env`, đặt mật khẩu Neo4j và APP_SECRET đủ ngẫu nhiên. Chỉnh DATA_DIR, địa chỉ CSDL nếu khác.
5. Chạy download, doctor, rồi chuỗi ETL bên trên. Không đưa file `.env` của máy này cho người khác.

## Dữ liệu và tài liệu

- [Amazon Review Data 2018 — UCSD](https://cseweb.ucsd.edu/~jmcauley/datasets/amazon_v2/)
- [Bài báo Ni, Li, McAuley — EMNLP-IJCNLP 2019](https://aclanthology.org/D19-1018/)
- [MongoDB Documentation](https://www.mongodb.com/docs/manual/)
- [Neo4j Cypher](https://neo4j.com/docs/cypher-manual/5/)
- [Tương thích Neo4j–GDS](https://neo4j.com/docs/graph-data-science/current/installation/supported-neo4j-versions/)
- [VADER của tác giả](https://github.com/cjhutto/vaderSentiment)

Metadata trên trang giới thiệu ghi 203.970 sản phẩm, trong khi tệp chính thức được tải ở lần chạy này có 203.766 dòng và 181.839 asin khác nhau. Đây là số đếm thực tế sau khi đọc tới hết gzip và kiểm tra checksum, được giữ minh bạch trong báo cáo EDA. Danh mục Movies & TV là sản phẩm Amazon, có thể gồm nhiều phiên bản của một tác phẩm; also_view là quan tâm/xem trang sản phẩm, không phải lịch sử phát video.


## Làm sạch dữ liệu và gộp ấn bản (buổi 6)

```powershell
& $python -m amazon_movies clean-data   # Brand rác (Various, ".", n/a…) → rỗng, bỏ thẻ HTML trong tiêu đề; giữ giá trị gốc ở *_raw
& $python -m amazon_movies editions     # gộp ấn bản thành tác phẩm, đánh dấu is_copy, dup_group; cập nhật cả Neo4j (~4 phút)
& $python -m amazon_movies work-sync    # chạy lại an toàn: bổ sung reviews.work, index, thuộc tính tác phẩm trên Neo4j
```

## Giao diện: khu người dùng và khu quản trị

Website tách hai khu. **Khu người dùng** (`#/`): Trang chủ, Tìm phim (theo tên/thể loại/định dạng/giá, hoặc tìm trong lời đánh giá), Chi tiết phim (điểm gộp mọi phiên bản, khen/chê, các phiên bản đang bán, chấm/sửa/xóa đánh giá, phim mua cùng), Gợi ý cho bạn (chấm nhanh khi chưa đủ 3 phim, mỗi gợi ý kèm lý do), Tài khoản — không hiện ASIN, PageRank, Cypher hay thuật ngữ kỹ thuật. **Khu quản trị** (`#/admin`): trạng thái và đối soát hai CSDL, hàng chờ đồng bộ, gộp ấn bản, phân tích gợi ý của bất kỳ người dùng nào, đồ thị Neo4j, thống kê review, thực nghiệm, cộng đồng phim. API của khu quản trị trả 401 khi chưa đăng nhập và 403 với tài khoản thường.

Tạo tài khoản quản trị (mật khẩu ngẫu nhiên ghi vào `.env`, không in ra màn hình; khởi động lại API sau đó):

```powershell
& $python -m amazon_movies create-admin
```

Xem `docs/API.md` và `docs/KICH_BAN_DEMO.md`. Chạy `python -m pytest -q` với Node.js trong PATH (hoặc biến NODE_BINARY) để gồm kiểm thử giao diện.
