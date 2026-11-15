"""Buổi 4: PageRank, Louvain, đánh giá Precision@10/Recall@10/NDCG@10, đo hiệu năng Index (10%/50%/100%)
và so sánh MongoDB vs Neo4j. Mọi con số trong báo cáo được sinh từ các hàm dưới đây."""
from collections import Counter, defaultdict
import math, random, re, statistics, time
from pymongo import ASCENDING, DESCENDING, UpdateOne
from .config import settings
from .data import batches, write_json
from . import graph, algorithms
from .algorithms import Catalog, Interactions, Recommender

GENERIC_CATEGORIES = {'Movies & TV', 'Movies', 'TV', 'Genre for Featured Categories', 'Featured Categories',
                      'Studio Specials', 'All Titles', 'All', 'Boxed Sets', 'Independently Distributed', 'Blu-ray',
                      'Widescreen', 'Fully Loaded DVDs', 'Characters & Series'}


# ============================================================================
# 1. GRAPH ANALYTICS: PAGERANK & LOUVAIN (Lê Minh Thuận)
# ============================================================================

def run_graph_analytics(db, driver, config=settings, top_n=20):
    """GDS PageRank và Louvain trên mạng mua/xem cùng; ghi kết quả về Neo4j và MongoDB."""
    started = time.time()
    pr_graph, lv_graph = 'movies_copurchase_directed', 'movies_copurchase_undirected'

    def drop(name):
        if graph.run(driver, 'CALL gds.graph.exists($name) YIELD exists RETURN exists', {'name': name}, config)[0]['exists']:
            graph.run(driver, 'CALL gds.graph.drop($name) YIELD graphName RETURN graphName', {'name': name}, config)

    for name in [pr_graph, lv_graph]:
        drop(name)
    try:
        pr_proj = graph.run(driver, "CALL gds.graph.project($name, 'Product', {ALSO_BOUGHT: {orientation: 'NATURAL'}, ALSO_VIEWED: {orientation: 'NATURAL'}}) "
                                    "YIELD nodeCount, relationshipCount RETURN nodeCount, relationshipCount", {'name': pr_graph}, config)[0]
        pr_params = {'maxIterations': 200, 'tolerance': 1e-7, 'dampingFactor': 0.85}
        pr_write = graph.run(driver, "CALL gds.pageRank.write($name, $params) "
                                     "YIELD nodePropertiesWritten, ranIterations, didConverge, centralityDistribution "
                                     "RETURN nodePropertiesWritten, ranIterations, didConverge, centralityDistribution",
                             {'name': pr_graph, 'params': {**pr_params, 'writeProperty': 'pagerank'}}, config)[0]
        lv_proj = graph.run(driver, "CALL gds.graph.project($name, 'Product', {ALSO_BOUGHT: {orientation: 'UNDIRECTED'}, ALSO_VIEWED: {orientation: 'UNDIRECTED'}}) "
                                    "YIELD nodeCount, relationshipCount RETURN nodeCount, relationshipCount", {'name': lv_graph}, config)[0]
        # concurrency=1 để kết quả Louvain lặp lại được giữa các lần chạy.
        lv_params = {'maxLevels': 10, 'concurrency': 1}
        lv_write = graph.run(driver, "CALL gds.louvain.write($name, $params) "
                                     "YIELD communityCount, modularity, modularities, ranLevels "
                                     "RETURN communityCount, modularity, modularities, ranLevels",
                             {'name': lv_graph, 'params': {**lv_params, 'writeProperty': 'community'}}, config)[0]
    finally:
        for name in [pr_graph, lv_graph]:
            drop(name)

    graph.run(driver, 'CREATE INDEX product_pagerank IF NOT EXISTS FOR (p:Product) ON (p.pagerank)', config=config)
    graph.run(driver, 'CREATE INDEX product_community IF NOT EXISTS FOR (p:Product) ON (p.community)', config=config)
    rows = graph.run(driver, '''MATCH (p:Product)
        RETURN p.asin AS asin, coalesce(p.pagerank, 0.0) AS pagerank, coalesce(p.community, -1) AS community,
               COUNT { (p)-[:ALSO_BOUGHT|ALSO_VIEWED]-() } AS degree''', config=config)
    for group in batches(rows, 2000):
        db.products.bulk_write([UpdateOne({'_id': r['asin']}, {'$set': {'stats.pagerank': float(r['pagerank']), 'stats.community': int(r['community']),
                                                                         'stats.copurchase_degree': int(r['degree'])}}) for r in group], ordered=False)
    db.products.create_index([('stats.pagerank', DESCENDING)])
    db.products.create_index([('stats.community', ASCENDING), ('stats.pagerank', DESCENDING)])

    top_pagerank = graph.run(driver, '''MATCH (p:Product)
        WITH p ORDER BY p.pagerank DESC, p.review_count DESC, p.asin ASC LIMIT $limit
        RETURN p.asin AS asin, p.title AS title, round(p.pagerank, 4) AS pagerank, p.avg_rating AS avg_rating,
               p.review_count AS review_count, p.community AS community,
               COUNT { (p)-[:ALSO_BOUGHT|ALSO_VIEWED]-() } AS degree''', {'limit': top_n}, config)

    # Cộng đồng chỉ có ý nghĩa với phim có liên kết mua/xem cùng; phim cô lập là cộng đồng 1 phần tử.
    connected = [r for r in rows if r['degree'] > 0]
    sizes = Counter(r['community'] for r in connected)
    isolated = len(rows) - len(connected)
    products = {d['asin']: d for d in db.products.find({'active': True}, {'asin': 1, 'title': 1, 'category_paths': 1, 'stats.avg_rating': 1,
                                                                           'stats.review_count': 1, 'stats.pagerank': 1, 'stats.community': 1})}

    def specific_categories(doc):
        names = set()
        for path in doc.get('category_paths', []):
            names.update(name for name in path[2:] if name not in GENERIC_CATEGORIES)
        return names

    global_counts = Counter()
    for doc in products.values():
        global_counts.update(specific_categories(doc))
    total_products = len(products)
    members = defaultdict(list)
    for r in connected:
        members[r['community']].append(r['asin'])
    top_communities = []
    for community, size in sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
        docs = [products[a] for a in members[community] if a in products]
        counts = Counter()
        for doc in docs:
            counts.update(specific_categories(doc))
        minimum = max(5, int(.05 * size))
        # Danh mục đặc trưng: tỉ lệ trong cộng đồng / tỉ lệ toàn bộ (lift), có ngưỡng tối thiểu.
        distinctive = sorted(((c / size) / (global_counts[name] / total_products), name, c) for name, c in counts.items() if c >= minimum)
        distinctive = [{'category': name, 'products': c, 'lift': round(lift, 2)} for lift, name, c in reversed(distinctive[-3:])]
        ratings = [d['stats']['avg_rating'] for d in docs if d.get('stats', {}).get('avg_rating') is not None]
        samples = sorted(docs, key=lambda d: (-d.get('stats', {}).get('pagerank', 0), -d.get('stats', {}).get('review_count', 0)))[:5]
        top_communities.append({'community': community, 'size': size, 'avg_rating': round(sum(ratings) / len(ratings), 3) if ratings else None,
                                'distinctive_categories': distinctive,
                                'sample_products': [{'asin': d['asin'], 'title': d['title'], 'pagerank': round(d['stats'].get('pagerank', 0), 4)} for d in samples]})

    report = {
        'pagerank': {'parameters': pr_params, 'projection': pr_proj, 'ranIterations': pr_write['ranIterations'],
                     'didConverge': pr_write['didConverge'], 'centralityDistribution': pr_write['centralityDistribution'],
                     'top_products': top_pagerank},
        'louvain': {'parameters': lv_params, 'projection': lv_proj, 'communityCount': lv_write['communityCount'],
                    'modularity': round(float(lv_write['modularity']), 6), 'ranLevels': lv_write['ranLevels'],
                    'connected_products': len(connected), 'isolated_products': isolated,
                    'communities_with_5_or_more': sum(1 for s in sizes.values() if s >= 5),
                    'top10_share_of_connected': round(sum(c['size'] for c in top_communities) / len(connected), 4) if connected else 0.,
                    'top_communities': top_communities},
        'seconds': round(time.time() - started, 2),
    }
    write_json(config.report_dir / 'buoi4_graph_analytics.json', report)
    return report


# ============================================================================
# 2. ĐÁNH GIÁ THUẬT TOÁN GỢI Ý: PRECISION@10, RECALL@10, NDCG@10 (Lê Minh Thuận)
# ============================================================================

def compute_ranking_metrics(recommended_asins, relevant_set, k=10):
    """Tính Precision@K, Recall@K, NDCG@K và Hit@K cho một người dùng."""
    if not relevant_set or k <= 0:
        return {'precision': 0.0, 'recall': 0.0, 'ndcg': 0.0, 'hit': 0.0}
    hits = 0
    dcg = 0.0
    for idx, asin in enumerate(recommended_asins[:k]):
        if asin in relevant_set:
            hits += 1
            dcg += 1.0 / math.log2(idx + 2)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant_set))))
    return {'precision': hits / float(k), 'recall': hits / float(len(relevant_set)),
            'ndcg': (dcg / idcg) if idcg > 0 else 0.0, 'hit': 1.0 if hits > 0 else 0.0}


def _load_events(db, include_demo=False):
    """(timestamp, _id, asin, rating, sentiment, work, dup_group) của các review không phải bản sao giữa các ấn bản."""
    query = {'is_copy': {'$ne': True}}
    if not include_demo:
        query['is_demo'] = False
    per_user = defaultdict(list)
    for d in db.reviews.find(query, {'reviewerID': 1, 'asin': 1, 'overall': 1, 'timestamp': 1, 'sentiment.label': 1, 'work': 1, 'dup_group': 1}):
        per_user[d['reviewerID']].append((int(d['timestamp']), d['_id'], d['asin'], float(d['overall']),
                                          d.get('sentiment', {}).get('label'), d.get('work') or d['asin'], d.get('dup_group')))
    return per_user


def _split(events):
    """Train = 80% review cũ nhất, Test = phần còn lại. Review giống hệt nhau của cùng người ở hai tác phẩm khác nhau
    (cùng dup_group, cùng thời điểm) là một lần viết: nếu một dòng nằm trong Train thì các dòng còn lại cũng vào Train."""
    split = _split_point(len(events))
    train, test = events[:split], events[split:]
    groups = {e[6] for e in train if e[6]}
    if groups and any(e[6] in groups for e in test):
        train = sorted(train + [e for e in test if e[6] in groups], key=lambda e: (e[0], e[1]))
        test = [e for e in test if e[6] not in groups]
    return train, test


def _event_rows(uid, events):
    return [(uid, e[2], e[3], e[0], e[1], e[4], e[5]) for e in events]


def _split_point(n):
    """Số review đưa vào Train: 80% cũ nhất, luôn để lại ít nhất 1 review cho Test (người có >= 5 review)."""
    return n if n < 5 else min(n - 1, max(1, int(n * .8)))


def _catalog(db):
    return Catalog(db.products.find({'active': True}, {'asin': 1, 'category_paths': 1, 'brand': 1, 'formats': 1, 'also_buy': 1,
                                                       'also_view': 1, 'work': 1, 'primary': 1}))


def _copy_key(doc):
    return (doc['timestamp'], doc['overall'], doc.get('summary') or '', (doc.get('reviewText') or '')[:200])


def residual_copy_leakage(db, per_user, users, relevant):
    """Kiểm tra lại rò rỉ sau khi gộp ấn bản: review phù hợp trong Test giống hệt một review Train của chính người đó
    (cùng ngày, số sao, tiêu đề, 200 ký tự đầu) — tức bản sao mà quy tắc gộp chưa bắt được."""
    leaked = total = 0
    for uid in users:
        train_ids = {e[1] for e in _split(per_user[uid])[0]}
        docs = list(db.reviews.find({'reviewerID': uid, 'is_copy': {'$ne': True}, 'is_demo': False},
                                    {'timestamp': 1, 'overall': 1, 'summary': 1, 'reviewText': 1, 'asin': 1, 'work': 1}))
        train_keys = {_copy_key(d) for d in docs if d['_id'] in train_ids}
        for d in docs:
            if d['_id'] not in train_ids and (d.get('work') or d['asin']) in relevant[uid]:
                total += 1
                leaked += _copy_key(d) in train_keys
    return {'relevant_test_reviews': total, 'identical_to_a_train_review': leaked,
            'rate': round(leaked / total, 4) if total else 0.}


def _average(rows, k):
    n = max(1, len(rows))
    keys = ['precision', 'recall', 'ndcg', 'hit']
    names = {'precision': f'precision@{k}', 'recall': f'recall@{k}', 'ndcg': f'ndcg@{k}', 'hit': f'hit_rate@{k}'}
    return {names[key]: round(sum(r[key] for r in rows) / n, 4) for key in keys}


def evaluate_recommendations(db, config=settings, sample_users=1200, validation_users=600, k=10, seed=42,
                             shrinkage_grid=(0., .5, 1., 2., 4., 8., 16., 32., 64., 128.), support_grid=(1, 2, 3, 4, 5),
                             driver=None, parity_users=0):
    """Chia theo thời gian từng người dùng: 80% review cũ (Train) / 20% mới (Test).

    Thuật toán chạy là bản Python 1-1 của Cypher (algorithms.py). Hệ số co CF được chọn trên tập
    validation tách rời tập test; nếu có driver và parity_users>0 thì kiểm chứng trùng khớp với Cypher.
    """
    started = time.time()
    catalog = _catalog(db)
    per_user = _load_events(db)
    train_events, relevant, profile = [], {}, {}
    kept_together = 0
    for uid, events in per_user.items():
        events.sort(key=lambda e: (e[0], e[1]))
        n = len(events)
        train, test = _split(events)
        kept_together += len(train) - _split_point(n)
        train_events.extend(_event_rows(uid, train))
        # Mức tác phẩm: tác phẩm đã có trong Train (ở bất kỳ ấn bản nào) không được tính là phù hợp trong Test.
        seen = {e[5] for e in train}
        ratings = defaultdict(list)
        for e in test:
            if e[5] not in seen:
                ratings[e[5]].append(e[3])
        rel = {w for w, values in ratings.items() if sum(values) / len(values) >= algorithms.LIKE_THRESHOLD}
        if n >= 5 and rel:
            relevant[uid] = rel
            profile[uid] = n
    interactions = Interactions(train_events)
    del train_events
    rec = Recommender(catalog, interactions)

    eligible = sorted(relevant)
    rng = random.Random(seed)
    rng.shuffle(eligible)
    test_users = eligible[:sample_users]
    valid_users = eligible[sample_users:sample_users + validation_users]

    # 2.1 Chọn cùng lúc hệ số co λ và số láng giềng tối thiểu của CF trên tập validation (không dùng tập test).
    joint = {(m, s): [] for m in support_grid for s in shrinkage_grid}
    for uid in valid_users:
        neighbors = rec.neighbors(uid)
        fallback = [r['asin'] for r in rec.popular(uid, k)]
        for m in support_grid:
            for s, rows in rec.collaborative(uid, shrinkages=shrinkage_grid, neighbors=neighbors, min_support=m).items():
                joint[(m, s)].append(compute_ranking_metrics([r['asin'] for r in rows][:k] or fallback, relevant[uid], k))
    joint_ndcg = {key: sum(r['ndcg'] for r in rows) / max(1, len(rows)) for key, rows in joint.items()}
    # Cặp "nhẹ tay" nhất (ít lọc nhất, rồi co ít nhất) đạt >= 99% NDCG tốt nhất: tránh chọn giá trị cực đoan khi đường đã đi ngang.
    best_support, best = min(key for key, v in joint_ndcg.items() if v >= .99 * max(joint_ndcg.values()))
    validation = {s: joint[(best_support, s)] for s in shrinkage_grid}
    validation_summary = {str(s): _average(rows, k) for s, rows in validation.items()}
    support_summary = {str(m): _average(joint[(m, best)], k) for m in support_grid}

    # 2.1b Chọn cách chuẩn hóa điểm của Hybrid (với hệ số co vừa chọn), cũng trên tập validation.
    normalization_rows = {'max': [], 'minmax': []}
    for uid in valid_users:
        cf_rows = rec.collaborative(uid, shrinkages=(best,), min_support=best_support)[best]
        related_rows, content_rows = rec.related(uid), rec.content(uid)
        fallback = [r['asin'] for r in rec.popular(uid, k)]
        for name in normalization_rows:
            rows = rec.hybrid(uid, cf_rows, related_rows, content_rows, normalization=name)
            normalization_rows[name].append(compute_ranking_metrics([r['asin'] for r in rows][:k] or fallback, relevant[uid], k))
    normalization_summary = {name: _average(rows, k) for name, rows in normalization_rows.items()}
    best_normalization = max(normalization_rows, key=lambda n: (round(sum(r['ndcg'] for r in normalization_rows[n]), 9), n == 'minmax'))

    # 2.2 Đánh giá trên tập test với hệ số đã chọn.
    methods = ['popular', 'collaborative', 'related', 'content', 'hybrid']
    results = {m: [] for m in methods}
    personalized = Counter()
    for uid in test_users:
        cf_rows = rec.collaborative(uid, shrinkages=(best,), min_support=best_support)[best]
        related_rows = rec.related(uid)
        content_rows = rec.content(uid)
        popular_rows = rec.popular(uid, k)
        hybrid_rows = rec.hybrid(uid, cf_rows, related_rows, content_rows, normalization=best_normalization)
        for method, rows in [('popular', popular_rows), ('collaborative', cf_rows), ('related', related_rows),
                             ('content', content_rows), ('hybrid', hybrid_rows)]:
            if rows and method != 'popular':
                personalized[method] += 1
            asins = [r['asin'] for r in rows][:k] or [r['asin'] for r in popular_rows]
            results[method].append(compute_ranking_metrics(asins, relevant[uid], k))
    test_sizes = [len(relevant[u]) for u in test_users]
    leakage = residual_copy_leakage(db, per_user, test_users, relevant)
    report = {
        'protocol': {
            'unit': 'Tác phẩm: các ấn bản (DVD, Blu-ray…) của cùng phim được gộp; review bản sao giữa các ấn bản bị bỏ trước khi chia.',
            'split': 'Mỗi người dùng: 80% review cũ nhất là Train, 20% mới nhất là Test (sắp theo thời gian). '
                     'Review giống hệt nhau của cùng người ở hai tác phẩm khác nhau không bị tách: nếu một dòng ở Train thì cả nhóm ở Train.',
            'identical_rows_moved_to_train': kept_together,
            'relevance': 'Tác phẩm trong Test có điểm TB của người dùng >= 4 sao và chưa xuất hiện trong Train ở bất kỳ ấn bản nào.',
            'eligible_users': 'Người dùng có >= 5 review (không tính bản sao) và >= 1 tác phẩm phù hợp trong Test; chọn ngẫu nhiên đều.',
            'implementation': 'Bản Python 1-1 của truy vấn Cypher trong recommend.py (algorithms.py), chạy trên đồ thị chỉ gồm Train.',
            'popular_baseline': 'Popular = tác phẩm có nhiều review >= 4 sao nhất trong Train, bỏ tác phẩm người dùng đã xem.',
            'fallback': 'Phương pháp không trả kết quả thì dùng Popular, giống website.',
            'k': k, 'seed': seed, 'total_eligible_users': len(eligible), 'test_users': len(test_users),
            'validation_users': len(valid_users), 'avg_relevant_items_per_test_user': round(sum(test_sizes) / max(1, len(test_sizes)), 2),
            'products': len(catalog.out), 'works': len(catalog.primary),
        },
        'residual_copy_leakage': leakage,
        'cf_shrinkage': {'grid': list(shrinkage_grid), 'selected': best,
                         'selected_by': f'chọn cùng số láng giềng tối thiểu: cặp ít lọc nhất rồi λ nhỏ nhất đạt ít nhất 99% NDCG@{k} tốt nhất trên tập validation; '
                                        f'bảng dưới là đường λ ở số láng giềng tối thiểu = {best_support}',
                         'production_value': algorithms.CF_SHRINKAGE, 'production_matches': best == algorithms.CF_SHRINKAGE,
                         'validation': validation_summary},
        'cf_min_support': {'grid': list(support_grid), 'selected': best_support,
                           'meaning': 'CF chỉ đề xuất tác phẩm có ít nhất N láng giềng cùng thích; N = 1 là không lọc. '
                                      'Không lọc thì láng giềng có rất ít phim thích (Jaccard cao) kéo vào phim lạc đề.',
                           'production_value': algorithms.CF_MIN_SUPPORT, 'production_matches': best_support == algorithms.CF_MIN_SUPPORT,
                           'validation': support_summary,
                           'joint_ndcg': {f'{m}|{s}': round(v, 4) for (m, s), v in joint_ndcg.items()}},
        'hybrid_normalization': {'selected': best_normalization, 'production_value': algorithms.HYBRID_NORMALIZATION,
                                 'production_matches': best_normalization == algorithms.HYBRID_NORMALIZATION,
                                 'selected_by': f'NDCG@{k} cao nhất trên tập validation (với λ và số láng giềng tối thiểu đã chọn)',
                                 'options': {'max': 'điểm / điểm lớn nhất', 'minmax': '(điểm − nhỏ nhất) / (lớn nhất − nhỏ nhất)'},
                                 'validation': normalization_summary},
        'metrics': {m: _average(results[m], k) for m in methods},
        'personalized_coverage': {m: round(personalized[m] / max(1, len(test_users)), 4) for m in methods if m != 'popular'},
        'limitations': [
            'Gộp ấn bản theo quy tắc chung >= 80% review: các phần/mùa khác nhau của một series vẫn là tác phẩm riêng. Review giống hệt nhau '
            'của cùng người ở các tác phẩm đó được giữ (người dùng tự dán lại) nhưng không bị chia giữa Train và Test; residual_copy_leakage kiểm tra lại điều này.',
            'Người dùng mới chỉ chấm vài phim: CF dựa trên rất ít láng giềng (có khi chỉ 1 người chung 2 phim) nên gợi ý dễ lệch gu; '
            'các số đo trên được tính cho người dùng có >= 5 review.',
            'also_buy/also_view là ảnh chụp metadata năm 2018 của Amazon, không chia theo thời gian, nên Related/Hybrid có thể hưởng lợi từ thông tin mua cùng phát sinh sau thời điểm chia.',
            'Chia 80/20 theo từng người dùng: tập Train của người này có thể chứa review mới hơn tập Test của người khác.',
            'Catalog dùng metadata đầy đủ; formats được tổng hợp từ cả review Train và Test. Content/Hybrid chưa phải đánh giá thời gian hoàn toàn độc lập.',
            'Chỉ các review giữ lại được dùng làm nhãn phù hợp. Sản phẩm chưa được review không có nhãn sở thích; các số đo là proxy ngoại tuyến, không phải độ chính xác hay cận dưới được bảo đảm cho mức hài lòng thực tế.',
        ],
    }
    del per_user, interactions, rec
    if driver is not None and parity_users:
        report['parity_check'] = parity_check(db, driver, config, parity_users, k)
    report['seconds'] = round(time.time() - started, 2)
    write_json(config.report_dir / 'buoi4_evaluation.json', report)
    return report


def parity_check(db, driver, config=settings, users=20, k=10, seed=99):
    """Chạy cùng người dùng qua Cypher (website) và bản Python trên dữ liệu đầy đủ, so sánh Top-K."""
    from . import recommend as live
    started = time.time()
    per_user = _load_events(db, include_demo=True)
    events = [row for uid, rows in per_user.items() for row in _event_rows(uid, rows)]
    interactions = Interactions(events)
    del events, per_user
    rec = Recommender(_catalog(db), interactions)
    candidates = sorted(u for u, liked in interactions.liked.items() if len(liked) >= 5 and not u.startswith('DEMO_'))
    sample = random.Random(seed).sample(candidates, min(users, len(candidates)))
    methods = ['popular', 'collaborative', 'related', 'content', 'hybrid']
    rows = {m: {'exact': 0, 'overlap': 0., 'seconds': 0.} for m in methods}
    for uid in sample:
        for method in methods:
            t0 = time.perf_counter()
            cypher = [r['asin'] for r in live.recommend(db, driver, uid, method, k, config=config)['items']]
            rows[method]['seconds'] += time.perf_counter() - t0
            python, _ = rec.recommend(uid, method, k)
            python = [r['asin'] for r in python]
            rows[method]['exact'] += cypher == python
            rows[method]['overlap'] += len(set(cypher) & set(python)) / max(1, len(set(cypher) | set(python)))
    n = max(1, len(sample))
    return {'users': len(sample), 'seed': seed, 'k': k,
            'methods': {m: {'identical_top_k_rate': round(v['exact'] / n, 4), 'mean_jaccard_top_k': round(v['overlap'] / n, 4),
                            'avg_cypher_seconds': round(v['seconds'] / n, 3)} for m, v in rows.items()},
            'note': 'Đã cố định thứ tự khi trùng timestamp bằng asin hoặc review_id. Chỉ kiểm tra Top-K trên mẫu người dùng; không chứng minh hai bản tương đương trên mọi dữ liệu hoặc điểm số.',
            'seconds': round(time.time() - started, 2)}


# ============================================================================
# 3. ĐO HIỆU NĂNG TRƯỚC & SAU INDEX Ở 3 MỨC DỮ LIỆU: 10%, 50%, 100%
# ============================================================================

def _plan_stages(plan):
    stages = []
    if isinstance(plan, dict):
        if 'stage' in plan:
            stages.append(plan['stage'])
        for key, value in plan.items():
            if key in ('inputStage', 'queryPlan', 'winningPlan'):
                stages.extend(_plan_stages(value))
            elif key == 'inputStages':
                for child in value:
                    stages.extend(_plan_stages(child))
    return stages


def _mongo_explain(cursor_factory, runs=3):
    measures = []
    for _ in range(runs + 1):
        explained = cursor_factory().explain()
        measures.append(explained)
    measures = measures[1:]  # bỏ lần đầu (nạp bộ nhớ đệm)
    stats = [m['executionStats'] for m in measures]
    return {'ms': statistics.median(s['executionTimeMillis'] for s in stats), 'docs_examined': stats[0]['totalDocsExamined'],
            'keys_examined': stats[0]['totalKeysExamined'], 'returned': stats[0]['nReturned'],
            'plan': ' > '.join(reversed(_plan_stages(measures[0]['queryPlanner']['winningPlan'])))}


def _neo4j_profile(driver, config, query, params, runs=3):
    def operators(plan):
        found = [str(plan.get('operatorType', '')).split('@')[0]]
        for child in plan.get('children', []):
            found.extend(operators(child))
        return found

    def db_hits(plan):
        return plan.get('dbHits', 0) + sum(db_hits(c) for c in plan.get('children', []))

    samples = []
    for _ in range(runs + 1):
        with driver.session(database=config.neo4j_database) as session:
            t0 = time.perf_counter()
            result = session.run('PROFILE ' + query, params)
            rows = list(result)
            summary = result.consume()
            client_ms = (time.perf_counter() - t0) * 1000
            # Thời gian phía server (lập kế hoạch + thực thi + trả kết quả), không gồm độ trễ mạng của driver.
            server_ms = (summary.result_available_after or 0) + (summary.result_consumed_after or 0)
            samples.append((server_ms, client_ms, len(rows), summary.profile or {}))
    samples = samples[1:]
    profile = samples[0][3]
    return {'ms': statistics.median(s[0] for s in samples), 'client_ms': round(statistics.median(s[1] for s in samples), 2),
            'db_hits': db_hits(profile), 'returned': samples[0][2], 'plan': ' > '.join(reversed([o for o in operators(profile) if o]))}


def _auto(driver, config, query, params=None):
    with driver.session(database=config.neo4j_database) as session:
        return session.run(query, params or {}).data()


def _speedup(before, after):
    # Cả hai CSDL báo thời gian theo mili giây nguyên: 0 ms nghĩa là < 1 ms, nên mẫu số tối thiểu là 1.
    return round(max(before, 1) / max(after, 1), 1)


def benchmark_indexes(db, driver, config=settings, scales=(.10, .50, 1.0)):
    """MongoDB explain() và Neo4j PROFILE trên CÙNG truy vấn trước/sau khi tạo index, ở 3 tập con theo thời gian."""
    started = time.time()
    order = [('timestamp', ASCENDING), ('_id', DESCENDING)]
    total = db.reviews.count_documents({'is_demo': False})
    cutoffs = []
    for ratio in scales:
        n = int(total * ratio)
        if ratio < 1:
            doc = next(db.reviews.find({'is_demo': False}, {'timestamp': 1}).sort(order).skip(n - 1).limit(1))
            cutoffs.append((ratio, n, doc['timestamp'], doc['_id']))
        else:
            cutoffs.append((ratio, n, None, None))

    # Chọn người dùng và phim có nhiều review nhất trong tập 10% để truy vấn có kết quả ở mọi mức.
    first_ratio, first_n, first_ts, first_id = cutoffs[0]
    subset = [{'$match': {'is_demo': False}}, {'$sort': dict(order)}, {'$limit': first_n}]
    target_user = list(db.reviews.aggregate(subset + [{'$group': {'_id': '$reviewerID', 'n': {'$sum': 1}}}, {'$sort': {'n': -1, '_id': 1}}, {'$limit': 1}], allowDiskUse=True))[0]['_id']
    target_asin = list(db.reviews.aggregate(subset + [{'$group': {'_id': '$asin', 'n': {'$sum': 1}}}, {'$sort': {'n': -1, '_id': 1}}, {'$limit': 1}], allowDiskUse=True))[0]['_id']
    target_review = next(db.reviews.find({'is_demo': False}, {'_id': 1}).sort(order).limit(1))['_id']

    mongo_results = []
    bench = db['_bench_reviews_scale']
    queries = {
        'user_review_history': ('Lịch sử review của một người dùng, mới nhất trước',
                                lambda c: c.find({'reviewerID': target_user}).sort('timestamp', DESCENDING).limit(20),
                                [('reviewerID', ASCENDING), ('timestamp', DESCENDING)]),
        'product_top_helpful_reviews': ('20 review hữu ích nhất của một phim',
                                        lambda c: c.find({'asin': target_asin}).sort('vote', DESCENDING).limit(20),
                                        [('asin', ASCENDING), ('vote', DESCENDING)]),
    }
    try:
        for ratio, n, ts, rid in cutoffs:
            if ratio < 1:
                bench.drop()
                list(db.reviews.aggregate([{'$match': {'is_demo': False}}, {'$sort': dict(order)}, {'$limit': n}, {'$out': bench.name}], allowDiskUse=True))
                collection = bench
            else:
                collection = db.reviews
            entry = {'scale': f'{int(ratio * 100)}%', 'documents': collection.count_documents({}), 'queries': {}}
            for name, (label, make, keys) in queries.items():
                if ratio < 1:
                    before = _mongo_explain(lambda: make(collection))
                    collection.create_index(keys)
                    after = _mongo_explain(lambda: make(collection))
                else:
                    # Toàn bộ dữ liệu: index đang phục vụ website, nên ép COLLSCAN bằng hint thay vì xóa index.
                    before = _mongo_explain(lambda: make(collection).hint([('$natural', 1)]))
                    after = _mongo_explain(lambda: make(collection))
                entry['queries'][name] = {'description': label, 'index': '{' + ', '.join(f'{k}: {v}' for k, v in keys) + '}',
                                          'before': before, 'after': after, 'speedup': _speedup(before['ms'], after['ms'])}
            mongo_results.append(entry)
    finally:
        bench.drop()

    # Neo4j: dựng tập con thật bằng quan hệ BENCH_REVIEWED (sao chép REVIEWED theo thời gian) và nhãn BenchProduct.
    neo_queries = {
        'lookup_review_by_id': ('Tìm một review theo review_id trên quan hệ',
                                'MATCH ()-[r:BENCH_REVIEWED {review_id:$rid}]->() RETURN r.review_id AS id', {'rid': target_review},
                                'CREATE INDEX bench_review_id IF NOT EXISTS FOR ()-[r:BENCH_REVIEWED]-() ON (r.review_id)', 'bench_review_id'),
        'high_rated_products': ('Lọc phim điểm TB >= 4.8 và >= 50 review',
                                'MATCH (p:BenchProduct) WHERE p.avg_rating >= 4.8 AND p.review_count >= 50 RETURN p.asin AS asin', {},
                                'CREATE INDEX bench_product_rating IF NOT EXISTS FOR (p:BenchProduct) ON (p.avg_rating)', 'bench_product_rating'),
    }

    def cleanup():
        _auto(driver, config, 'DROP INDEX bench_review_id IF EXISTS')
        _auto(driver, config, 'DROP INDEX bench_product_rating IF EXISTS')
        _auto(driver, config, 'MATCH ()-[r:BENCH_REVIEWED]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 50000 ROWS')
        _auto(driver, config, 'MATCH (p:BenchProduct) CALL (p) { REMOVE p:BenchProduct } IN TRANSACTIONS OF 20000 ROWS')

    neo4j_results = []
    cleanup()
    try:
        # Duyệt review theo đúng thứ tự (timestamp, _id) của MongoDB và sao chép REVIEWED theo lô qua index review_id,
        # nên tập con Neo4j trùng tuyệt đối với tập con MongoDB ở cùng mức.
        stream = db.reviews.find({'is_demo': False}, {'_id': 1, 'asin': 1}).sort(order).batch_size(20000)
        copied, batch, asins = 0, [], set()

        def flush():
            nonlocal batch
            if batch:
                graph.run(driver, 'UNWIND $ids AS id MATCH (u:User)-[r:REVIEWED {review_id:id}]->(p:Product) '
                                  'CREATE (u)-[:BENCH_REVIEWED {review_id:id}]->(p)', {'ids': batch}, config)
                batch = []

        for ratio, n, ts, rid in cutoffs:
            new_asins = set()
            while copied < n:
                doc = next(stream, None)
                if doc is None:
                    break
                batch.append(doc['_id'])
                copied += 1
                if doc['asin'] not in asins:
                    asins.add(doc['asin'])
                    new_asins.add(doc['asin'])
                if len(batch) >= 10000:
                    flush()
            flush()
            new_list = sorted(new_asins)
            for i in range(0, len(new_list), 10000):
                graph.run(driver, 'UNWIND $asins AS a MATCH (p:Product {asin:a}) SET p:BenchProduct', {'asins': new_list[i:i + 10000]}, config)
            relationships = _auto(driver, config, 'MATCH ()-[r:BENCH_REVIEWED]->() RETURN count(r) AS n')[0]['n']
            products = _auto(driver, config, 'MATCH (p:BenchProduct) RETURN count(p) AS n')[0]['n']
            entry = {'scale': f'{int(ratio * 100)}%', 'relationships': relationships, 'products': products, 'queries': {}}
            for name, (label, query, qparams, create, index_name) in neo_queries.items():
                _auto(driver, config, f'DROP INDEX {index_name} IF EXISTS')
                before = _neo4j_profile(driver, config, query, qparams)
                _auto(driver, config, create)
                _auto(driver, config, 'CALL db.awaitIndexes(600)')
                after = _neo4j_profile(driver, config, query, qparams)
                entry['queries'][name] = {'description': label, 'query': query, 'index': create, 'before': before, 'after': after,
                                          'speedup': _speedup(before['ms'], after['ms'])}
            neo4j_results.append(entry)
    finally:
        cleanup()

    report = {
        'method': {
            'subsets': '10%, 50% là các review cũ nhất theo (timestamp, _id); 100% là toàn bộ. MongoDB: $out sang collection tạm. '
                       'Neo4j: sao chép đúng các review đó từ REVIEWED thành BENCH_REVIEWED và gắn nhãn BenchProduct cho phim có review trong tập con; '
                       'dữ liệu tạm bị xóa sau khi đo.',
            'measurement': 'Cùng một truy vấn trước và sau khi tạo index; bỏ lần chạy đầu, lấy trung vị 3 lần. '
                           'MongoDB: executionTimeMillis của explain; Neo4j: thời gian phía server (available + consumed) của PROFILE. '
                           'Cả hai có độ phân giải 1 ms, "0 ms" nghĩa là dưới 1 ms; hệ số nhanh hơn lấy mẫu số tối thiểu 1 ms.',
            'targets': {'reviewerID': target_user, 'asin': target_asin, 'review_id': target_review},
        },
        'mongodb_explain': mongo_results,
        'neo4j_profile': neo4j_results,
        'seconds': round(time.time() - started, 2),
    }
    write_json(config.report_dir / 'buoi4_index_benchmark.json', report)
    return report


# ============================================================================
# 4. SO SÁNH HAI CSDL TRÊN 3 BÀI TOÁN ĐỐI CHỨNG (Huỳnh Công Bằng)
# ============================================================================

CYPHER_CLAUSES = re.compile(r'\b(OPTIONAL MATCH|MATCH|WHERE|WITH|UNWIND|CALL|RETURN|ORDER BY|LIMIT|SKIP)\b')


def cypher_clause_count(query):
    return len(CYPHER_CLAUSES.findall(query))


def mongo_stage_count(pipeline):
    """(số stage cấp ngoài, tổng số stage kể cả pipeline lồng trong $lookup/$facet)."""
    total = 0
    for stage in pipeline:
        total += 1
        for name, spec in stage.items():
            if name == '$lookup' and isinstance(spec, dict) and 'pipeline' in spec:
                total += mongo_stage_count(spec['pipeline'])[1]
            elif name == '$facet':
                total += sum(mongo_stage_count(branch)[1] for branch in spec.values())
    return len(pipeline), total


def compare_databases(db, driver, config=settings, user='AP9WKJ5YFQWWB', asin='B00OV3VGP0', runs=5):
    """Cùng bài toán, cùng kết quả mong đợi: MongoDB (Aggregation/$lookup) và Neo4j (Cypher)."""
    started = time.time()
    product = db.products.find_one({'asin': asin, 'active': True})
    if not product or not (product.get('also_buy') or product.get('also_view')):
        asin = db.products.find_one({'active': True, 'also_buy.5': {'$exists': True}})['asin']

    def measure(fn):
        fn()  # khởi động
        times, out = [], None
        for _ in range(runs):
            t0 = time.perf_counter()
            out = fn()
            times.append((time.perf_counter() - t0) * 1000.0)
        return {'median_ms': round(statistics.median(times), 2), 'min_ms': round(min(times), 2)}, out

    # (a) Mức tác phẩm, bỏ review bản sao giữa các ấn bản. reviews.work luôn có (mặc định = asin) và có index.
    similar_pipeline = [
        {'$match': {'reviewerID': user, 'is_copy': {'$ne': True}}},
        {'$group': {'_id': '$work', 'rating': {'$avg': '$overall'}, 'lastReview': {'$max': '$timestamp'}}},
        {'$match': {'rating': {'$gte': 4}}},
        {'$sort': {'lastReview': -1, '_id': 1}},
        {'$limit': 100},
        {'$lookup': {'from': 'reviews', 'localField': '_id', 'foreignField': 'work', 'pipeline': [
            {'$match': {'reviewerID': {'$ne': user}, 'is_copy': {'$ne': True}}},
            {'$group': {'_id': '$reviewerID', 'rating': {'$avg': '$overall'}}},
            {'$match': {'rating': {'$gte': 4}}},
        ], 'as': 'co'}},
        {'$unwind': '$co'},
        {'$group': {'_id': '$co._id', 'common': {'$sum': 1}}},
        {'$match': {'common': {'$gte': 2}}},
        {'$sort': {'common': -1, '_id': 1}},
        {'$limit': 20},
        {'$project': {'_id': 0, 'user': '$_id', 'common': 1}},
    ]
    similar_cypher = '''MATCH (u:User {reviewerID:$user})
CALL (u) {
  MATCH (u)-[r:REVIEWED]->(p:Product) WHERE NOT coalesce(r.copy, false)
  WITH p.work AS w, avg(r.rating) AS rating, max(r.timestamp) AS lastReview WHERE rating >= 4
  ORDER BY lastReview DESC, w ASC LIMIT 100 RETURN collect(w) AS liked
}
UNWIND liked AS w
MATCH (:Product {work:w})<-[nr:REVIEWED]-(other:User) WHERE other <> u AND NOT coalesce(nr.copy, false)
WITH other, w, avg(nr.rating) AS rating WHERE rating >= 4
WITH other.reviewerID AS user, count(DISTINCT w) AS common WHERE common >= 2
RETURN user, common ORDER BY common DESC, user ASC LIMIT 20'''

    # (b) Đường đi 1–2 bước, gộp đích theo tác phẩm và bỏ chính tác phẩm của phim gốc (giống website).
    related_pipeline = [
        {'$match': {'asin': asin, 'active': True}},
        {'$project': {'seed': '$asin', 'seed_work': '$work', 'hop1': {'$concatArrays': [
            {'$setUnion': [{'$ifNull': ['$also_buy', []]}]}, {'$setUnion': [{'$ifNull': ['$also_view', []]}]}]}}},
        {'$unwind': '$hop1'},
        {'$match': {'$expr': {'$ne': ['$hop1', '$seed']}}},
        {'$lookup': {'from': 'products', 'localField': 'hop1', 'foreignField': 'asin', 'as': 'p1'}},
        {'$unwind': '$p1'},
        {'$match': {'p1.active': True}},
        {'$project': {'seed_work': 1, 'hop1_asin': '$p1.asin', 'hop1_work': '$p1.work', 'hop2_list': {'$concatArrays': [
            {'$setUnion': [{'$ifNull': ['$p1.also_buy', []]}]}, {'$setUnion': [{'$ifNull': ['$p1.also_view', []]}]}]}}},
        {'$facet': {
            'step1': [{'$project': {'candidate': '$hop1_work', 'seed_work': 1, 'hops': {'$literal': 1}}}],
            'step2': [{'$unwind': '$hop2_list'},
                      {'$match': {'$expr': {'$ne': ['$hop2_list', '$hop1_asin']}}},
                      {'$lookup': {'from': 'products', 'localField': 'hop2_list', 'foreignField': 'asin', 'as': 'p2'}},
                      {'$unwind': '$p2'}, {'$match': {'p2.active': True}},
                      {'$project': {'candidate': '$p2.work', 'seed_work': 1, 'hops': {'$literal': 2}}}],
        }},
        {'$project': {'paths': {'$concatArrays': ['$step1', '$step2']}}},
        {'$unwind': '$paths'},
        {'$match': {'$expr': {'$ne': ['$paths.candidate', '$paths.seed_work']}}},
        {'$group': {'_id': '$paths.candidate', 'hops': {'$min': '$paths.hops'}, 'support': {'$sum': 1}}},
        {'$project': {'_id': 0, 'asin': '$_id', 'hops': 1, 'support': 1, 'score': {'$divide': ['$support', '$hops']}}},
        {'$sort': {'score': -1, 'asin': 1}},
        {'$limit': 10},
    ]
    related_cypher = '''MATCH path=(seed:Product {asin:$asin})-[:ALSO_BOUGHT|ALSO_VIEWED*1..2]->(candidate:Product)
WHERE candidate.work <> seed.work
WITH candidate.work AS work, min(length(path)) AS hops, count(path) AS support
RETURN work AS asin, toFloat(support)/hops AS score, support, hops
ORDER BY score DESC, asin ASC LIMIT 10'''

    # (c) Theo tác phẩm (ấn bản đại diện, số review không tính bản sao), bỏ các nút điều hướng của Amazon.
    from .mongo import NAVIGATION_CATEGORIES
    navigation = sorted(NAVIGATION_CATEGORIES)
    category_pipeline = [
        {'$match': {'active': True, 'primary': True}},
        {'$unwind': '$categories'},
        {'$match': {'categories': {'$nin': navigation}}},
        {'$group': {'_id': '$categories', 'work_count': {'$sum': 1}, 'review_count': {'$sum': '$stats.work_reviews'},
                    'weighted': {'$sum': {'$multiply': ['$stats.work_reviews', '$stats.work_avg']}}}},
        {'$match': {'review_count': {'$gt': 0}}},
        {'$project': {'_id': 0, 'category': '$_id', 'work_count': 1, 'review_count': 1,
                      'avg_rating': {'$round': [{'$divide': ['$weighted', '$review_count']}, 4]}}},
        {'$sort': {'review_count': -1, 'category': 1}},
        {'$limit': 20},
    ]
    category_cypher = '''MATCH (p:Product {primary:true})-[:IN_CATEGORY]->(c:Category)
WHERE NOT c.name IN $navigation
WITH c.name AS category, collect(DISTINCT p) AS works
UNWIND works AS p
WITH category, count(p) AS work_count, sum(p.work_reviews) AS review_count,
     sum(p.work_reviews * p.work_avg) AS weighted
WHERE review_count > 0
RETURN category, work_count, review_count, round(weighted / review_count, 4) AS avg_rating
ORDER BY review_count DESC, category ASC LIMIT 20'''

    tasks = {
        'a_similar_users': ('Top 20 người dùng có nhiều tác phẩm cùng thích (>= 4 sao) nhất với một người dùng',
                            'reviews', similar_pipeline, similar_cypher, {'user': user}, lambda r: (r['user'], r['common'])),
        'b_copurchase_2hop': ('Tác phẩm mua/xem cùng trong 1–2 bước (ALSO_BOUGHT / ALSO_VIEWED), gộp ấn bản',
                              'products', related_pipeline, related_cypher, {'asin': asin}, lambda r: (r['asin'], r['support'], r['hops'], round(r['score'],8))),
        'c_category_avg_rating': ('Điểm trung bình và số review theo thể loại (tác phẩm, không tính bản sao)',
                                  'products', category_pipeline, category_cypher, {'navigation': navigation},
                                  lambda r: (r['category'], r['work_count'], r['review_count'], round(r['avg_rating'],4))),
    }
    report_tasks = {}
    for key, (description, collection, pipeline, cypher, params, signature) in tasks.items():
        mongo_time, mongo_out = measure(lambda: list(db[collection].aggregate(pipeline, allowDiskUse=True)))
        neo_time, neo_out = measure(lambda: graph.run(driver, cypher, params, config))
        top, nested = mongo_stage_count(pipeline)
        faster = 'Neo4j' if neo_time['median_ms'] < mongo_time['median_ms'] else 'MongoDB'
        report_tasks[key] = {
            'description': description,
            'mongodb': {**mongo_time, 'stages_top_level': top, 'stages_total': nested, 'pipeline': pipeline, 'top_3': mongo_out[:3]},
            'neo4j': {**neo_time, 'cypher_clauses': cypher_clause_count(cypher), 'cypher': cypher, 'top_3': neo_out[:3]},
            'results_match': [signature(r) for r in mongo_out] == [signature(r) for r in neo_out],
            'rows': len(mongo_out),
            'faster_engine': faster,
            'speedup_ratio': round(max(mongo_time['median_ms'], neo_time['median_ms']) / max(.01, min(mongo_time['median_ms'], neo_time['median_ms'])), 2),
        }
    report = {'parameters': {'user': user, 'asin': asin, 'runs_per_query': runs, 'timing': 'trung vị sau 1 lần khởi động'},
              'tasks': report_tasks, 'seconds': round(time.time() - started, 2)}
    write_json(config.report_dir / 'buoi4_db_comparison.json', report)
    return report
