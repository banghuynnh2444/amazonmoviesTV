# Kịch bản demo và thuyết trình (khoảng 12 phút)

**Nhóm:** Huỳnh Công Bằng (4654100001) · Lê Minh Thuận (4654100012)

Slide (14 trang, có ghi chú người nói): https://claude.ai/artifact/JbPa5mdzNty7bzQn8TCYmP · Báo cáo: https://claude.ai/artifact/7ueR5VAtcxat4gsEMi8yjm (bản Word và PDF trong `D:\AmazonMoviesTV\tai_lieu\bao_cao\`)

Website có **hai khu**: khu người dùng (người xem phim) và khu quản trị (`#/admin`, nhóm phát triển). Khi demo, nói rõ ranh giới này: người xem không thấy mã ASIN, PageRank, Cypher hay trạng thái CSDL.

## Chuẩn bị trước giờ trình bày (5 phút)

1. Khởi động hệ thống và chờ dòng `doctor` báo cả hai CSDL `ok`:

   ```powershell
   cd D:\AmazonMoviesTV\project
   .\scripts\start-local.ps1 -StartApi -StartSync
   ```

2. Tài khoản quản trị: tên `admin`, mật khẩu là dòng `ADMIN_PASSWORD` trong tệp `.env` (tạo bằng `python -m amazon_movies create-admin`; không chiếu tệp `.env` lên màn hình).
3. Mở `http://127.0.0.1:5055`. Website không cần Internet. Chờ khoảng 30 giây để API làm nóng bộ nhớ đệm.
4. Kiểm tra nhanh toàn bộ endpoint (tùy chọn, ~30 giây): `python scripts\verify_web_ui.py` phải in "… kiểm tra endpoint đạt".
5. Mở sẵn Neo4j Browser `http://127.0.0.1:7485` (đăng nhập bằng thông tin trong `.env`) nếu muốn chạy Cypher trực tiếp.

Dữ liệu dùng khi demo: phim `B00OV3VGP0` (John Wick), người dùng `A1435P5AMCPB3X` (120 review), phim nhiều ấn bản Guardians of the Galaxy (`B00Q0G2VXM`).

## Trình tự demo

| Phút | Người nói | Thao tác trên website | Ý cần nói |
|---|---|---|---|
| 0–1 | Bằng | **Trang chủ** | 59.395 phim, 3,1 triệu đánh giá khác nhau. Hai danh sách: "Được yêu thích nhất" (nhiều người chấm từ 4 sao) và "Điểm cao nhất" (điểm Bayesian, phim ít đánh giá không chiếm chỗ). Thể loại lấy từ dữ liệu, không lẫn tên hãng phim |
| 1–3 | Bằng | **Tìm phim** → gõ `star wars`, định dạng Blu-ray, giá 5–30 → tab **Tìm trong lời đánh giá** gõ `masterpiece`, chọn "Chê" | MongoDB Text Index trên tên + mô tả và trên nội dung review; mỗi phim hiện một dòng dù có nhiều ấn bản. Gõ `good` để thấy cách xử lý từ quá phổ biến |
| 3–4 | Bằng | Mở **Guardians Of The Galaxy Region Free** | "Một phiên bản của Guardians of the Galaxy"; bảng 4 phiên bản đang bán. Điểm 4,6 từ 7.137 đánh giá là gộp mọi phiên bản, mỗi đánh giá tính một lần (trước đây cùng một review bị đếm 3–4 lần) |
| 4–5 | Bằng | Mở **John Wick**: điểm, khen/chê, "Được nhắc nhiều" | Thống kê tính sẵn trong document (Computed Pattern); phân loại khen/chê bằng VADER chỉ cho tiếng Anh, ghi rõ có thể sai với câu mỉa mai |
| 5–7 | Bằng | **Tài khoản** → tạo tài khoản mới → **Gợi ý cho bạn** → chấm nhanh 5–6 phim → **Cập nhật gợi ý** → mở một phim, viết đánh giá, sửa, xóa | Người mới chưa có lịch sử nhận danh sách phổ biến và lời mời chấm nhanh. Sau khi chấm: mỗi gợi ý có lý do ("Thường được mua/xem cùng …", "N người có gu giống bạn …"). Chấm lại cùng phim bị chặn, phải sửa đánh giá cũ. Ghi: MongoDB (synced=false) → Neo4j MERGE → synced=true |
| 7–8 | Thuận | Đăng xuất → đăng nhập `admin` → **Hệ thống & dữ liệu** | Tình trạng hai CSDL; đối soát Product/User/REVIEWED khớp; hàng chờ đồng bộ = 0; gộp ấn bản: 694 phim có nhiều ấn bản, 150.464 dòng bản sao. Bấm "Chạy đối soát đầy đủ" |
| 8–9 | Thuận | **Phân tích gợi ý** → `A1435P5AMCPB3X` → lần lượt Lai, CF, Mua/xem cùng, Nội dung, Phổ biến | Công thức từng phương pháp; 4 cột thành phần của Hybrid; Neo4j trả asin + điểm, MongoDB bổ sung chi tiết; người dùng tương đồng (SIMILAR_TO) |
| 9–10 | Thuận | **Đồ thị Neo4j** với `B00OV3VGP0`, nhấp đúp một phim; đổi sang người dùng | 5 loại nút, màu theo cạnh; người dùng hiện tên công khai (tên "Amazon Customer" kèm 6 ký tự cuối mã) thay vì chuỗi mã |
| 10–11 | Bằng | **Thống kê review** | VADER gán "tích cực" cho 88,4% review 4–5 sao nhưng chỉ gán "tiêu cực" cho 51,9% review 1–2 sao (31,8% review 1 sao bị gán tích cực) — hạn chế của từ điển |
| 11–12 | Cả hai | **Thực nghiệm** | Mục 2: Hybrid NDCG@10 = 0,0393, gấp gần 4 lần Phổ biến; số cũ 0,0559 bị thổi lên do review bản sao giữa các ấn bản (rò rỉ 9,9%) và mốc Phổ biến yếu. λ = 16, ngưỡng ≥ 2 láng giềng cùng thích và cách chuẩn hóa chọn trên validation, Top-10 trùng Cypher 100%. Mục 3: không index 4.943 ms → dưới 1 ms. Mục 4: so sánh hai CSDL |

## Nếu có sự cố

| Sự cố | Cách xử lý |
|---|---|
| Trang quản trị báo một CSDL "Không kết nối" | Chạy lại `.\scripts\start-local.ps1 -StartApi`; Neo4j cần khoảng 20 giây để sẵn sàng |
| Đăng nhập `admin` báo sai | Kiểm tra dòng `ADMIN_PASSWORD` trong `.env`; nếu vừa chạy `create-admin` thì khởi động lại API |
| Gợi ý lần đầu chậm vài giây | Bộ nhớ đệm chưa nóng; bấm lại, hoặc mở sẵn trang trước khi trình bày |
| Lưu đánh giá báo "gợi ý sẽ cập nhật sau ít phút" | Neo4j tạm lỗi (HTTP 202), đánh giá vẫn nằm trong MongoDB; worker `sync --watch` sẽ ghi lại. Đây chính là luồng chịu lỗi của thiết kế |
| Không mở được website | Dùng ảnh chụp trong `D:\AmazonMoviesTV\tai_lieu\anh_chup_website\` và các bảng trong báo cáo |

Sau buổi demo, có thể xóa các đánh giá đã viết ngay trên web (nút Xóa); tài khoản tạo trên web mang tiền tố `DEMO_` và bị loại khỏi mọi thực nghiệm.

## Câu hỏi có thể gặp

- **Vì sao số cũ (NDCG 0,0559, gấp 51 lần) khác số mới?** Amazon hiện chung review cho mọi ấn bản của một phim, nên cùng một review có ở DVD và Blu-ray. Khi chia 80/20, ấn bản này nằm ở Train, ấn bản kia ở Test → 9,9% "phim phù hợp" là đáp án đã biết. Nhóm gộp ấn bản thành tác phẩm, bỏ bản sao, giữ nhóm review giống hệt nhau cùng một phía, và đổi mốc Phổ biến sang số review từ 4 sao (mốc mạnh hơn). Kiểm tra lại: 0 / 2.700 phim phù hợp trùng một review đã học.
- **Vì sao Precision@10 chỉ 0,0108?** Mỗi người kiểm thử trung bình chỉ có 2,25 phim phù hợp trong gần 60.000 phim; phim người dùng thích nhưng chưa review bị tính là sai. Điều cần xem là so sánh tương đối giữa các phương pháp trên cùng tập.
- **Vì sao đánh giá bằng Python chứ không chạy Cypher?** Đồ thị vận hành chứa toàn bộ lịch sử. Nhóm dựng cấu trúc tương tác Train riêng trong Python; bản Python dùng chung hằng số và công thức với Cypher và cho Top-10 trùng 100% trên 20 người (seed 99) ở cả 5 phương pháp — không chứng minh mọi trường hợp đều tương đương.
- **λ = 16 và "ít nhất 2 láng giềng" lấy từ đâu?** Chọn cùng lúc trên 600 người dùng validation tách rời tập test: cặp ít lọc nhất rồi λ nhỏ nhất đạt 99% NDCG@10 tốt nhất. Không lọc (1 láng giềng) CF chỉ đạt 0,0227 và gợi ý phim lạc đề cho người mới; λ = 0 chỉ đạt 0,0204.
- **User trong Neo4j sao chỉ là chuỗi mã?** Bộ dữ liệu Amazon không có tài khoản thật: reviewerID là mã ẩn danh, reviewerName là tên công khai. Nút User nay có thuộc tính `name`; tên chung chung được kèm 6 ký tự cuối mã để phân biệt.
- **"$12.99 → số", "'1,234' → int" trong thuyết minh là gì?** Giá trong metadata là chuỗi có ký hiệu đô la, được đổi thành số thực để lọc theo giá (khoảng giá hoặc rỗng thì null); lượt hữu ích là chuỗi có dấu phẩy ngăn cách hàng nghìn, được đổi thành số nguyên để sắp xếp.
- **Brand là hãng phát hành?** Không hẳn: với phim, Amazon ghi brand chủ yếu là tên diễn viên chính (John Wayne 103 phim, Tom Hanks 39). Web ghi "Diễn viên / thương hiệu"; 2.743 giá trị rác (Various, ".", n/a) đã đưa về rỗng.
- **Vì sao cần cả hai CSDL?** Bài mua/xem cùng 2 bước: MongoDB cần 16 stage với 2 tầng `$lookup` (44 ms), Neo4j một mẫu đường đi (1,9 ms, ×23,5). Neo4j cũng nhanh hơn ở hai bài còn lại, nhưng Neo4j không lưu nội dung review: tìm kiếm toàn văn, trang chi tiết phim và thống kê trên 3,1 triệu review chỉ MongoDB làm được. Lưu ý: bản đo 11/11 cho MongoDB nhanh hơn ở bài thống kê theo thể loại; đo lại theo tác phẩm thì Neo4j nhanh gấp đôi — nhóm báo đúng số đo mới.
- **Nếu hai CSDL lệch nhau thì sao?** MongoDB là nguồn gốc; review có cờ `synced` và `version`; `sync --watch` ghi lại bằng `MERGE` nên chạy nhiều lần không tạo trùng; trang Hệ thống & dữ liệu đối soát trực tiếp, `python -m amazon_movies verify` đối soát đầy đủ. Xóa đánh giá: xóa ở Neo4j trước, lỗi thì không xóa ở MongoDB.
- **Hạn chế?** Trọng số Hybrid cố định; also_buy/also_view không chia theo thời gian; người dùng mới chỉ chấm vài phim thì CF dựa trên rất ít láng giềng nên gợi ý dễ lệch gu; VADER khớp kém với review chê; SIMILAR_TO là ảnh chụp tại thời điểm chạy GDS. Xem `SUA_LOI_2026-11-14.md`.
