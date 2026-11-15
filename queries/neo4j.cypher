// Lê Minh Thuận — buổi 1–3. Browser: http://127.0.0.1:7485
RETURN gds.version();
SHOW CONSTRAINTS;

// Kiểm tra 5 loại node và các quan hệ đã có dữ liệu.
MATCH (n) UNWIND labels(n) AS label RETURN label,count(*) AS total;
MATCH ()-[r]->() RETURN type(r) AS relationship,count(*) AS total;

// Các tham số mẫu sử dụng ID thực tế trong tập dữ liệu 5-core đã nạp.
:param user => 'AP9WKJ5YFQWWB';
:param asin => 'B00OV3VGP0';

// Các phim chung được đánh giá cao: mỗi user-product chỉ đóng góp một sản phẩm.
MATCH (u:User {reviewerID:$user})-[r:REVIEWED]->(p:Product)
WITH u,p,avg(r.rating) AS meanRating WHERE meanRating>=4
MATCH (other:User)-[nr:REVIEWED]->(p) WHERE other<>u
WITH other,p,avg(nr.rating) AS otherRating WHERE otherRating>=4
RETURN other.reviewerID AS user,count(DISTINCT p) AS common ORDER BY common DESC LIMIT 20;

// Gợi ý mua/xem sản phẩm liên quan trong tối đa 2 bước.
MATCH path=(seed:Product {asin:$asin})-[:ALSO_BOUGHT|ALSO_VIEWED*1..2]->(candidate:Product)
WHERE seed<>candidate
RETURN candidate.asin,candidate.title,min(length(path)) AS hops,count(path) AS support
ORDER BY hops,support DESC LIMIT 10;

// CF đầy đủ (giống amazon_movies/recommend.py; λ = 32 chọn trên tập validation).
:param liked_limit => 100; :param min_common => 2; :param candidate_neighbors => 300;
:param neighbors => 30; :param shrink => 32.0; :param limit => 10;
MATCH (u:User {reviewerID:$user})
CALL (u) { MATCH (u)-[r:REVIEWED]->(p:Product)
       WITH p,avg(r.rating) AS rating,max(r.timestamp) AS lastReview WHERE rating>=4
       ORDER BY lastReview DESC,p.asin ASC LIMIT $liked_limit RETURN collect(p) AS liked }
UNWIND liked AS shared
MATCH (other:User)-[nr:REVIEWED]->(shared) WHERE other<>u
WITH u,liked,other,shared,avg(nr.rating) AS rating WHERE rating>=4
WITH u,liked,other,count(DISTINCT shared) AS common WHERE common >= $min_common
WITH u,liked,other,common ORDER BY common DESC,other.reviewerID LIMIT $candidate_neighbors
CALL (other) { MATCH (other)-[r:REVIEWED]->(p:Product)
       WITH p,avg(r.rating) AS rating WHERE rating>=4 RETURN count(p) AS degree }
WITH u,other,common,toFloat(common)/(size(liked)+degree-common) AS similarity
ORDER BY similarity DESC,other.reviewerID LIMIT $neighbors
MATCH (other)-[r:REVIEWED]->(candidate:Product)
WHERE NOT EXISTS { MATCH (u)-[:REVIEWED]->(candidate) }
WITH u,other,similarity,candidate,avg(r.rating) AS rating WHERE rating>=4
WITH u,candidate,sum(similarity*(rating-coalesce(other.avg_rating,3.0))) AS centered,
     sum(similarity) AS weight,count(DISTINCT other) AS support
RETURN candidate.asin AS asin,coalesce(u.avg_rating,3.0)+centered/(weight+$shrink) AS score,support
ORDER BY score DESC,support DESC,asin LIMIT $limit;

// Content-based và hybrid: xem amazon_movies/recommend.py (hybrid ghép 3 truy vấn + cảm xúc từ MongoDB).

// Người dùng tương đồng do GDS Node Similarity ghi.
MATCH (u:User {reviewerID:$user})-[s:SIMILAR_TO]->(v:User)
RETURN v.reviewerID AS user, s.score AS jaccard ORDER BY jaccard DESC LIMIT 10;

// Kiểm tra đồng bộ có lặp review_id hay không.
MATCH ()-[r:REVIEWED]->()
WITH r.review_id AS id,count(*) AS copies WHERE copies>1 RETURN id,copies LIMIT 20;

// ============================================================================
// BUỔI 4: BỘ 3 TRUY VẤN ĐỐI CHỨNG SO SÁNH NEO4J VS MONGODB & GRAPH ANALYTICS
// ============================================================================

// (a) Tìm người dùng tương đồng (Top 20 user có nhiều phim >= 4 sao chung nhất)
MATCH (u:User {reviewerID:$user})
CALL (u) {
  MATCH (u)-[r:REVIEWED]->(p:Product)
  WITH p, avg(r.rating) AS rating, max(r.timestamp) AS lastReview WHERE rating >= 4
  ORDER BY lastReview DESC, p.asin ASC LIMIT 100 RETURN collect(p) AS liked
}
UNWIND liked AS shared
MATCH (other:User)-[nr:REVIEWED]->(shared) WHERE other <> u
WITH other, shared, avg(nr.rating) AS rating WHERE rating >= 4
WITH other.reviewerID AS user, count(DISTINCT shared) AS common WHERE common >= 2
RETURN user, common ORDER BY common DESC, user ASC LIMIT 20;

// (b) Gợi ý mua/xem cùng 2 bước (2-hop ALSO_BOUGHT / ALSO_VIEWED)
MATCH path=(seed:Product {asin:$asin})-[:ALSO_BOUGHT|ALSO_VIEWED*1..2]->(candidate:Product)
WHERE candidate <> seed
WITH candidate, min(length(path)) AS hops, count(path) AS support
RETURN candidate.asin AS asin, toFloat(support)/hops AS score, support, hops
ORDER BY score DESC, asin ASC LIMIT 10;

// (c) Thống kê điểm đánh giá trung bình và tổng số review theo danh mục (Top 20 danh mục)
MATCH (p:Product)-[:IN_CATEGORY]->(c:Category)
WITH c.name AS category, collect(DISTINCT p) AS prods
UNWIND prods AS p
WITH category, count(p) AS product_count, sum(p.review_count) AS review_count,
     sum(p.review_count * p.avg_rating) AS weighted_sum
WHERE review_count > 0
RETURN category, product_count, review_count, round(weighted_sum / review_count, 4) AS avg_rating
ORDER BY review_count DESC, category ASC LIMIT 20;

// PageRank: Top 20 phim có tầm ảnh hưởng lớn nhất trong mạng mua/xem cùng
MATCH (p:Product)
RETURN p.asin AS asin, p.title AS title, round(p.pagerank, 6) AS pagerank, p.avg_rating AS avg_rating, p.review_count AS review_count, p.community AS community
ORDER BY p.pagerank DESC, p.review_count DESC LIMIT 20;

// Louvain: Top 10 cộng đồng phim thường được mua/xem cùng nhau
MATCH (p:Product)
WHERE EXISTS { (p)-[:ALSO_BOUGHT|ALSO_VIEWED]-() }
RETURN p.community AS community, count(p) AS size, round(avg(p.avg_rating), 3) AS avg_rating
ORDER BY size DESC LIMIT 10;
