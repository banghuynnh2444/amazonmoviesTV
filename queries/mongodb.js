// Huỳnh Công Bằng — buổi 1–3. Kết nối đúng MongoDB cổng 27028.
use('amazon_movies_tv');

// Tìm kiếm toàn văn; điểm liên quan của products và reviews là hai thang riêng.
db.products.find({active:true,$text:{$search:'star wars'}},{title:1,score:{$meta:'textScore'}}).sort({score:{$meta:'textScore'}}).limit(20);
db.reviews.find({$text:{$search:'wonderful'}},{asin:1,summary:1,score:{$meta:'textScore'}}).sort({score:{$meta:'textScore'}}).limit(20);

// Lịch sử và kế hoạch truy vấn trên user thực tế trong bộ 5-core.
db.reviews.find({reviewerID:'AP9WKJ5YFQWWB'}).sort({timestamp:-1}).limit(20).explain('executionStats');

// Phân bố sao, cảm xúc, đối chiếu sao × cảm xúc (VADER) và xu hướng bằng facet.
db.reviews.aggregate([{$facet:{
  stars:[{$group:{_id:'$overall',count:{$sum:1}}},{$sort:{_id:1}}],
  sentiment:[{$group:{_id:'$sentiment.label',count:{$sum:1}}}],
  sentiment_by_star:[{$group:{_id:{star:'$overall',sentiment:'$sentiment.label'},count:{$sum:1}}},{$sort:{'_id.star':1,'_id.sentiment':1}}],
  timeline:[{$group:{_id:{$dateToString:{format:'%Y-%m',date:'$review_date'}},count:{$sum:1}}},{$sort:{_id:1}}]
}}]);

// Lookup dùng cùng mã asin để kết hợp review với metadata.
db.reviews.aggregate([{$match:{overall:{$gte:4},is_demo:false}},{$limit:100},
 {$lookup:{from:'products',localField:'asin',foreignField:'asin',as:'product'}},
 {$project:{asin:1,overall:1,'product.title':1}}]);

// Phân bố khoảng giá: giá thiếu là null, không được coi là 0.
db.products.aggregate([{$match:{active:true,price:{$ne:null}}},
 {$bucket:{groupBy:'$price',boundaries:[0,5,10,20,50,100,1000],default:'other',output:{count:{$sum:1}}}}]);

// Kiểm tra hàng chờ; dùng moviesctl sync để đồng bộ, không sửa cờ bằng tay.
db.reviews.countDocuments({synced:false});
db.reviews.aggregate([{$group:{_id:{user:'$reviewerID',asin:'$asin'},events:{$sum:1}}},{$match:{events:{$gt:1}}},{$limit:20}]);

// ============================================================================
// BUỔI 4: BỘ 3 TRUY VẤN ĐỐI CHỨNG SO SÁNH MONGODB VS NEO4J
// ============================================================================

// (a) Tìm người dùng tương đồng (Top 20 user có nhiều phim >= 4 sao chung nhất với AP9WKJ5YFQWWB)
// "Thích" = điểm TB của người đó cho phim >= 4 (giống Cypher), nên kết quả hai CSDL trùng nhau.
db.reviews.aggregate([
  {$match:{reviewerID:'AP9WKJ5YFQWWB'}},
  {$group:{_id:'$asin',rating:{$avg:'$overall'},lastReview:{$max:'$timestamp'}}},
  {$match:{rating:{$gte:4}}},
  {$sort:{lastReview:-1,_id:1}},
  {$limit:100},
  {$lookup:{
    from:'reviews',
    let:{liked_asin:'$_id'},
    pipeline:[
      {$match:{$expr:{$eq:['$asin','$$liked_asin']},reviewerID:{$ne:'AP9WKJ5YFQWWB'}}},
      {$group:{_id:'$reviewerID',rating:{$avg:'$overall'}}},
      {$match:{rating:{$gte:4}}}
    ],
    as:'co'
  }},
  {$unwind:'$co'},
  {$group:{_id:'$co._id',common:{$sum:1}}},
  {$match:{common:{$gte:2}}},
  {$sort:{common:-1,_id:1}},
  {$limit:20},
  {$project:{_id:0,user:'$_id',common:1}}
]);

// (b) Gợi ý mua/xem cùng 2 bước (2-hop also_buy / also_view cho sản phẩm B00OV3VGP0 - John Wick)
db.products.aggregate([
  {$match:{asin:'B00OV3VGP0',active:true}},
  {$project:{seed:'$asin',hop1:{$concatArrays:[{$setUnion:[{$ifNull:['$also_buy',[]]}]},{$setUnion:[{$ifNull:['$also_view',[]]}]}]}}},
  {$unwind:'$hop1'},
  {$match:{$expr:{$ne:['$hop1','$seed']}}},
  {$lookup:{from:'products',localField:'hop1',foreignField:'asin',as:'p1'}},
  {$unwind:'$p1'},
  {$match:{'p1.active':true}},
  {$project:{seed:1,hop1_asin:'$p1.asin',hop2_list:{$concatArrays:[{$setUnion:[{$ifNull:['$p1.also_buy',[]]}]},{$setUnion:[{$ifNull:['$p1.also_view',[]]}]}]}}},
  {$facet:{
    step1:[{$project:{candidate:'$hop1_asin',hops:{$literal:1}}}],
    step2:[
      {$unwind:'$hop2_list'},
      {$match:{$expr:{$and:[{$ne:['$hop2_list','$seed']},{$ne:['$hop2_list','$hop1_asin']}]}}},
      {$lookup:{from:'products',localField:'hop2_list',foreignField:'asin',as:'p2'}},
      {$unwind:'$p2'},
      {$match:{'p2.active':true}},
      {$project:{candidate:'$p2.asin',hops:{$literal:2}}}
    ]
  }},
  {$project:{paths:{$concatArrays:['$step1','$step2']}}},
  {$unwind:'$paths'},
  {$group:{_id:'$paths.candidate',hops:{$min:'$paths.hops'},support:{$sum:1}}},
  {$project:{_id:0,asin:'$_id',hops:1,support:1,score:{$divide:['$support','$hops']}}},
  {$sort:{score:-1,asin:1}},
  {$limit:10}
]);

// (c) Thống kê điểm đánh giá trung bình và tổng số review theo danh mục (Top 20 danh mục)
db.products.aggregate([
  {$match:{active:true}},
  {$unwind:'$categories'},
  {$group:{
    _id:'$categories',
    product_count:{$sum:1},
    review_count:{$sum:'$stats.review_count'},
    weighted_rating_sum:{$sum:{$multiply:['$stats.review_count','$stats.avg_rating']}}
  }},
  {$match:{review_count:{$gt:0}}},
  {$project:{
    _id:0,
    category:'$_id',
    product_count:1,
    review_count:1,
    avg_rating:{$round:[{$divide:['$weighted_rating_sum','$review_count']},4]}
  }},
  {$sort:{review_count:-1,category:1}},
  {$limit:20}
]);
