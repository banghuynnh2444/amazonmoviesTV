"""Thuận: CF có chuẩn hóa điểm, mua/xem cùng, nội dung và gợi ý lai — ở mức tác phẩm.

Hằng số và công thức dùng chung với algorithms.py (bản Python dùng để đánh giá 80/20).
Review bản sao giữa các ấn bản (REVIEWED.copy = true) không được tính; mọi gợi ý là ấn bản đại diện
(Product.primary) và không gợi ý lại tác phẩm người dùng đã review ở bất kỳ ấn bản nào.
"""
from .graph import run
from .config import settings
from .mongo import public, LIST_PROJECTION
from .algorithms import (rank_hybrid, CF_LIKED_LIMIT, CF_MIN_COMMON, CF_CANDIDATE_NEIGHBORS, CF_NEIGHBORS,
                         CF_SHRINKAGE, CF_MIN_SUPPORT, CONTENT_SEEDS, CONTENT_POOL, RELATED_SEEDS, RELATED_PER_SEED,
                         CANDIDATE_LIMIT, BAYES_MIN_REVIEWS, BAYES_PRIOR)

__all__ = ['recommend', 'related', 'popular', 'top_rated', 'rank_hybrid', 'METHODS', 'seen_works']

METHODS = ['hybrid', 'collaborative', 'related', 'content', 'popular']

SEEN_WORKS = 'CALL (u) { MATCH (u)-[:REVIEWED]->(x:Product) RETURN collect(DISTINCT coalesce(x.work,x.asin)) AS seenWorks }'

# score = điểm TB của người dùng + Σ sim·(rating − điểm TB láng giềng) / (Σ sim + shrink)
CF = '''MATCH (u:User {reviewerID:$user})
CALL (u) { MATCH (u)-[r:REVIEWED]->(p:Product) WHERE NOT coalesce(r.copy,false)
       WITH coalesce(p.work,p.asin) AS w,avg(r.rating) AS rating,max(r.timestamp) AS lastReview WHERE rating>=4
       ORDER BY lastReview DESC,w ASC LIMIT $liked_limit RETURN collect(w) AS liked }
''' + SEEN_WORKS + '''
UNWIND liked AS w
MATCH (x:Product {work:w})<-[nr:REVIEWED]-(other:User) WHERE other<>u AND NOT coalesce(nr.copy,false)
WITH u,liked,seenWorks,other,w,avg(nr.rating) AS rating WHERE rating>=4
WITH u,liked,seenWorks,other,count(DISTINCT w) AS common WHERE common >= $min_common
WITH u,liked,seenWorks,other,common ORDER BY common DESC,other.reviewerID LIMIT $candidate_neighbors
CALL (other) { MATCH (other)-[r:REVIEWED]->(p:Product) WHERE NOT coalesce(r.copy,false)
       WITH coalesce(p.work,p.asin) AS w,avg(r.rating) AS rating WHERE rating>=4 RETURN count(w) AS degree }
WITH u,seenWorks,other,common,toFloat(common)/(size(liked)+degree-common) AS similarity
ORDER BY similarity DESC,other.reviewerID LIMIT $neighbors
MATCH (other)-[r:REVIEWED]->(c:Product) WHERE NOT coalesce(r.copy,false) AND NOT coalesce(c.work,c.asin) IN seenWorks
WITH u,other,similarity,coalesce(c.work,c.asin) AS candidate,avg(r.rating) AS rating WHERE rating>=4
WITH u,candidate,sum(similarity*(rating-coalesce(other.avg_rating,3.0))) AS centered,
     sum(similarity) AS weight,count(DISTINCT other) AS support
WHERE support >= $min_support
RETURN candidate AS asin,coalesce(u.avg_rating,3.0)+centered/(weight+$shrink) AS score,support,
       'collaborative' AS method
ORDER BY score DESC,support DESC,asin LIMIT $limit'''

CONTENT = '''MATCH (u:User {reviewerID:$user})
CALL (u) { MATCH (u)-[r:REVIEWED]->(p:Product) WHERE NOT coalesce(r.copy,false)
 WITH coalesce(p.work,p.asin) AS w,avg(r.rating) AS rating,max(r.timestamp) AS lastReview WHERE rating>=4
 ORDER BY lastReview DESC,w ASC LIMIT $content_seeds RETURN collect(w) AS seedWorks }
''' + SEEN_WORKS + '''
MATCH (seed:Product) WHERE seed.asin IN seedWorks
WITH seenWorks,collect(seed) AS seeds
CALL (seeds) { UNWIND seeds AS seed OPTIONAL MATCH (seed)-[:AVAILABLE_AS]->(f:Format) RETURN collect(DISTINCT f) AS prefFormats }
UNWIND seeds AS seed
MATCH (seed)-[:IN_CATEGORY|BY_BRAND]->(attribute)<-[:IN_CATEGORY|BY_BRAND]-(candidate:Product)
WHERE (NOT attribute:Category OR size(attribute.path)>2) AND coalesce(candidate.primary,true)
  AND NOT coalesce(candidate.work,candidate.asin) IN seenWorks
WITH candidate,prefFormats,count(DISTINCT seed) AS seeds,count(DISTINCT attribute) AS contentAttrs,min(seed.asin) AS via
ORDER BY seeds DESC,contentAttrs DESC,candidate.asin LIMIT $content_pool
WITH candidate,seeds,via,contentAttrs+COUNT { MATCH (candidate)-[:AVAILABLE_AS]->(f:Format) WHERE f IN prefFormats } AS attributes
RETURN candidate.asin AS asin,toFloat(seeds)+0.2*attributes AS score,seeds AS support,via,'content' AS method
ORDER BY score DESC,asin LIMIT $limit'''

# Gộp các ấn bản đích về tác phẩm; bỏ chính tác phẩm của phim gốc (các ấn bản khác của nó).
RELATED_1 = '''MATCH path=(seed:Product {asin:$asin})-[:ALSO_BOUGHT|ALSO_VIEWED*1]->(candidate:Product)
WHERE coalesce(candidate.work,candidate.asin) <> coalesce(seed.work,seed.asin)
WITH coalesce(candidate.work,candidate.asin) AS work,min(length(path)) AS hops,count(path) AS support
RETURN work AS asin,toFloat(support)/hops AS score,support,hops,'related' AS method
ORDER BY score DESC,asin LIMIT $limit'''
RELATED_2 = RELATED_1.replace('*1]', '*1..2]')


def related(driver, asin, steps=2, limit=RELATED_PER_SEED, config=settings):
    return run(driver, RELATED_2 if steps == 2 else RELATED_1, {'asin': asin, 'limit': limit}, config)


def seen_works(db, user):
    """Tác phẩm người dùng đã review ở bất kỳ ấn bản nào."""
    if not user:
        return set()
    asins = db.reviews.distinct('asin', {'reviewerID': user})
    works = set(db.products.distinct('work', {'asin': {'$in': asins}}))
    return works | set(asins)


def popular(db, user=None, limit=10):
    """Phổ biến = nhiều người thích nhất: số review từ 4 sao của tác phẩm (bỏ bản sao), bỏ tác phẩm đã xem."""
    seen = seen_works(db, user)
    cursor = db.products.find({'active': True, 'primary': {'$ne': False}, 'asin': {'$nin': list(seen)}, 'stats.work_positive': {'$gt': 0}},
                              {'asin': 1, 'stats.work_positive': 1, 'stats.work_reviews': 1})
    cursor = cursor.sort([('stats.work_positive', -1), ('stats.work_reviews', -1), ('asin', -1)]).limit(limit)
    return [{'asin': p['asin'], 'score': float(p['stats']['work_positive']), 'support': p['stats'].get('work_reviews', 0), 'method': 'popular'} for p in cursor]


def top_rated(db, limit=10):
    """Đánh giá cao: điểm Bayesian (n·TB + 10·TB chung)/(n + 10) theo tác phẩm, tác phẩm có ít nhất 5 review."""
    match = {'active': True, 'primary': {'$ne': False}, 'stats.work_reviews': {'$gte': BAYES_MIN_REVIEWS}}
    mean = list(db.products.aggregate([{'$match': match}, {'$group': {'_id': None, 'm': {'$avg': '$stats.work_avg'}}}]))
    mean = mean[0]['m'] if mean else 3.
    pipeline = [{'$match': match},
                {'$addFields': {'bayes': {'$divide': [{'$add': [{'$multiply': ['$stats.work_reviews', '$stats.work_avg']}, BAYES_PRIOR * mean]},
                                                      {'$add': ['$stats.work_reviews', BAYES_PRIOR]}]}}},
                {'$sort': {'bayes': -1, 'stats.work_reviews': -1, 'asin': 1}}, {'$limit': limit},
                {'$project': LIST_PROJECTION}]  # phép loại trừ: giữ lại trường bayes vừa thêm
    return list(db.products.aggregate(pipeline))


def cypher_params(user, limit, shrink=CF_SHRINKAGE, min_common=CF_MIN_COMMON, min_support=CF_MIN_SUPPORT):
    return {'user': user, 'limit': max(CANDIDATE_LIMIT, limit), 'liked_limit': CF_LIKED_LIMIT, 'min_common': min_common,
            'candidate_neighbors': CF_CANDIDATE_NEIGHBORS, 'neighbors': CF_NEIGHBORS, 'shrink': float(shrink),
            'min_support': int(min_support), 'content_seeds': CONTENT_SEEDS, 'content_pool': CONTENT_POOL}


def related_for_user(db, driver, user, config=settings):
    seeds = [r['asin'] for r in db.reviews.find({'reviewerID': user, 'overall': {'$gte': 4}, 'is_copy': {'$ne': True}}, {'asin': 1})
             .sort([('timestamp', -1), ('_id', -1)]).limit(RELATED_SEEDS)]
    seen = seen_works(db, user)
    scores = {}
    for asin in seeds:
        for row in related(driver, asin, 2, RELATED_PER_SEED, config):
            if row['asin'] not in seen:
                current = scores.setdefault(row['asin'], {**row, 'score': 0., 'via': asin, 'best': 0.})
                current['score'] += row['score']
                if row['score'] > current['best']:
                    current['best'], current['via'] = row['score'], asin
    for row in scores.values():
        row.pop('best', None)
    return sorted(scores.values(), key=lambda row: (-row['score'], row['asin']))


def candidates(db, driver, user, method='hybrid', limit=10, config=settings, shrink=CF_SHRINKAGE, min_common=CF_MIN_COMMON):
    """Danh sách (asin, score, ...) theo đúng thứ tự xếp hạng, chưa lấy chi tiết từ MongoDB."""
    params = cypher_params(user, limit, shrink, min_common)
    if method == 'popular':
        return popular(db, user, limit)
    if method == 'collaborative':
        return run(driver, CF, params, config)
    if method == 'content':
        return run(driver, CONTENT, params, config)
    if method == 'related':
        return related_for_user(db, driver, user, config)
    if method == 'hybrid':
        cf = run(driver, CF, params, config)
        content = run(driver, CONTENT, params, config)
        related_rows = related_for_user(db, driver, user, config)
        ids = {r['asin'] for r in cf + content + related_rows}
        sentiment_rows = []
        for p in db.products.find({'asin': {'$in': list(ids)}}, {'asin': 1, 'stats.work_sentiment': 1}):
            counts = p.get('stats', {}).get('work_sentiment', {})
            n = sum(counts.get(k, 0) for k in ['positive', 'negative', 'neutral'])
            if n:
                sentiment_rows.append({'asin': p['asin'], 'score': counts.get('positive', 0) / n})
        return rank_hybrid({'collaborative': cf, 'related': related_rows, 'content': content, 'sentiment': sentiment_rows})
    raise ValueError('Phương pháp phải là collaborative, related, content, hybrid hoặc popular')


def recommend(db, driver, user, method='hybrid', limit=10, min_common=CF_MIN_COMMON, config=settings, shrink=CF_SHRINKAGE):
    rows = candidates(db, driver, user, method, limit, config, shrink, min_common)
    fallback = not rows
    if fallback:
        rows = popular(db, user, limit)
    rows = rows[:limit]
    # Giữ thứ tự xếp hạng của Neo4j khi lấy chi tiết sản phẩm từ MongoDB.
    products = {p['asin']: public(p) for p in db.products.find({'asin': {'$in': [r['asin'] for r in rows]}}, LIST_PROJECTION)}
    return {'requested_method': method, 'fallback_to_popular': fallback,
            'items': [{**r, 'product': products[r['asin']]} for r in rows if r['asin'] in products]}
