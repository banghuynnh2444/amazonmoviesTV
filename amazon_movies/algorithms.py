"""Thuật toán gợi ý dùng chung cho website (Cypher) và đánh giá ngoại tuyến (Python).

Neo4j giữ toàn bộ lịch sử review nên không thể chạy thẳng Cypher trên riêng tập Train 80%
mà không sao chép đồ thị. Vì vậy mỗi hàm trong lớp Recommender là bản sao 1-1 của một truy
vấn trong recommend.py, dùng CÙNG hằng số và CÙNG công thức. session4.parity_check() chạy cả
hai bản trên dữ liệu đầy đủ để kiểm chứng chúng cho cùng danh sách gợi ý.

Từ buổi 6, mọi phương pháp làm việc ở mức TÁC PHẨM: các ấn bản (DVD, Blu-ray…) của cùng một phim
được gộp (editions.py), review bản sao giữa các ấn bản bị bỏ qua, gợi ý trả về ấn bản đại diện và
không gợi ý lại tác phẩm người dùng đã review ở bất kỳ ấn bản nào.
"""
from collections import Counter, defaultdict
import heapq

# Tham số dùng chung (recommend.py truyền các giá trị này vào Cypher).
CF_LIKED_LIMIT = 100        # số tác phẩm thích gần nhất của người dùng đích
CF_MIN_COMMON = 2           # số tác phẩm chung tối thiểu với láng giềng
CF_CANDIDATE_NEIGHBORS = 300  # số láng giềng xét theo số tác phẩm chung
CF_NEIGHBORS = 30           # số láng giềng giữ lại theo Jaccard
CF_SHRINKAGE = 16.0         # hệ số co λ; chọn trên tập validation (session4.evaluate_recommendations)
CF_MIN_SUPPORT = 2          # số láng giềng tối thiểu cùng thích một tác phẩm thì CF mới đề xuất; chọn cùng λ trên validation
CONTENT_SEEDS = 20
CONTENT_POOL = 200
RELATED_SEEDS = 5
RELATED_PER_SEED = 50
CANDIDATE_LIMIT = 50
BAYES_MIN_REVIEWS = 5       # danh sách "Đánh giá cao" (Bayesian) trên trang chủ
BAYES_PRIOR = 10
LIKE_THRESHOLD = 4.0
HYBRID_WEIGHTS = {'collaborative': .45, 'related': .25, 'content': .20, 'sentiment': .10}
HYBRID_NORMALIZATION = 'max'  # chọn trên tập validation (xem session4.evaluate_recommendations)


def normalize_scores(rows, method=None):
    """Đưa điểm của một phương pháp về [0, 1].

    'minmax': (s − min) / (max − min) — trải đều điểm trong danh sách, kể cả khi mọi ứng viên gần bằng nhau.
    'max': s / max — giữ tỉ lệ so với ứng viên tốt nhất. Điểm CF có cộng điểm TB người dùng (≈ 3–5) nên sau
           chuẩn hóa mọi ứng viên CF có thành phần CF ≈ 0,8–1: Hybrid ưu tiên phim được CF đề xuất rồi xếp
           tiếp theo mua cùng/nội dung. Cách này cho NDCG@10 cao hơn trên tập validation nên được chọn.
    """
    method = method or HYBRID_NORMALIZATION
    scores = [float(r['score']) for r in rows]
    if not scores:
        return []
    if method == 'max':
        top = max(max(scores), 0.)
        return [max(0., s) / top if top else 0. for s in scores]
    low, high = min(scores), max(scores)
    return [1. if high == low else (s - low) / (high - low) for s in scores]


def rank_hybrid(components, weights=None, normalization=None):
    """Chuẩn hóa điểm từng phương pháp về [0, 1] rồi cộng có trọng số; giữ lại phim gốc (via) để giải thích."""
    weights = weights or HYBRID_WEIGHTS
    merged = {}
    for method, candidates in components.items():
        for row, normalized in zip(candidates, normalize_scores(candidates, normalization)):
            item = merged.setdefault(row['asin'], {'asin': row['asin'], 'score': 0., 'components': {}, 'via': {}, 'support': {}, 'method': 'hybrid'})
            item['components'][method] = normalized
            item['score'] += weights.get(method, 0.) * normalized
            if row.get('via'):
                item['via'][method] = row['via']
            if row.get('support') is not None:
                item['support'][method] = row['support']
    return sorted(merged.values(), key=lambda row: (-row['score'], row['asin']))


def category_keys(paths):
    """Khóa của các nút Category có độ sâu > 2 (tương ứng size(c.path) > 2 trong Cypher)."""
    keys = set()
    for path in paths or []:
        for i in range(2, len(path)):
            keys.add('C:' + '\x1f'.join(path[:i + 1]))
    return keys


class Catalog:
    """Phần sản phẩm của đồ thị: ALSO_BOUGHT/ALSO_VIEWED, Category sâu, Brand, Format và tác phẩm."""

    def __init__(self, products):
        docs = list(products)
        active = {d['asin'] for d in docs}
        self.work = {d['asin']: d.get('work') or d['asin'] for d in docs}
        self.primary = {d['asin'] for d in docs if d.get('primary', True) is not False}
        self.out = {}
        self.formats = {}
        self.attrs = {}
        self.attr_products = defaultdict(list)
        for d in docs:
            asin = d['asin']
            edges = []
            for field in ('also_buy', 'also_view'):
                # Mỗi loại quan hệ là một cạnh riêng; MERGE trong Neo4j bỏ trùng trong cùng loại.
                for target in dict.fromkeys(d.get(field) or []):
                    if target != asin and target in active:
                        edges.append(target)
            self.out[asin] = edges
            self.formats[asin] = set(d.get('formats') or [])
            attrs = category_keys(d.get('category_paths'))
            if d.get('brand'):
                attrs.add('B:' + d['brand'])
            self.attrs[asin] = attrs
            if asin in self.primary:
                for attr in attrs:
                    self.attr_products[attr].append(asin)

    def work_of(self, asin):
        return self.work.get(asin, asin)

    def related_one(self, seed, limit=RELATED_PER_SEED):
        """(seed)-[:ALSO_BOUGHT|ALSO_VIEWED*1..2]->(c), gộp theo tác phẩm của c, bỏ tác phẩm của seed.

        support = số đường đi tới mọi ấn bản của tác phẩm, score = support / số bước ngắn nhất."""
        own = self.work_of(seed)
        support = Counter()
        hops = {}
        for middle in self.out.get(seed, ()):
            w = self.work_of(middle)
            support[w] += 1
            hops[w] = 1
            for candidate in self.out.get(middle, ()):
                if candidate != seed:
                    w2 = self.work_of(candidate)
                    support[w2] += 1
                    if w2 not in hops:
                        hops[w2] = 2
        rows = [{'asin': w, 'score': n / hops[w], 'support': n, 'hops': hops[w]} for w, n in support.items() if w != own]
        return heapq.nsmallest(limit, rows, key=lambda r: (-r['score'], r['asin']))


class Interactions:
    """Phần người dùng của đồ thị dựng từ review KHÔNG phải bản sao (toàn bộ hoặc chỉ tập Train).

    events: (reviewerID, asin, rating, timestamp, order_key, sentiment_label[, work]); thiếu work thì work = asin.
    """

    def __init__(self, events):
        items = defaultdict(dict)
        rating_sum = Counter()
        rating_count = Counter()
        high_rows = defaultdict(list)
        item_stats = defaultdict(lambda: [0, 0., 0, 0, 0, 0])  # count, sum, positive, neutral, negative, liked
        for event in events:
            uid, asin, rating, ts, order, label = event[:6]
            work = event[6] if len(event) > 6 and event[6] else asin
            entry = items[uid].get(work)
            if entry is None:
                items[uid][work] = [rating, 1, ts]
            else:
                entry[0] += rating
                entry[1] += 1
                if ts > entry[2]:
                    entry[2] = ts
            rating_sum[uid] += rating
            rating_count[uid] += 1
            if rating >= LIKE_THRESHOLD:
                high_rows[uid].append((ts, order, asin))
            stats = item_stats[work]
            stats[0] += 1
            stats[1] += rating
            if label == 'positive':
                stats[2] += 1
            elif label == 'neutral':
                stats[3] += 1
            elif label == 'negative':
                stats[4] += 1
            if rating >= LIKE_THRESHOLD:
                stats[5] += 1
        self.items = items
        self.mean = {u: rating_sum[u] / rating_count[u] for u in rating_count}
        self.liked = {}
        self.likers = defaultdict(list)
        for uid, works in items.items():
            liked = [(-v[2], w) for w, v in works.items() if v[0] / v[1] >= LIKE_THRESHOLD]
            liked.sort()
            self.liked[uid] = [w for _, w in liked]
            for _, w in liked:
                self.likers[w].append(uid)
        # Mongo: find(overall>=4, không phải bản sao).sort(timestamp desc, _id desc).limit(5) — ấn bản đã review.
        self.recent_high = {u: [a for _, _, a in sorted(rows, reverse=True)[:RELATED_SEEDS]] for u, rows in high_rows.items()}
        self.item_stats = dict(item_stats)
        # Phổ biến = số người thích (>= 4 sao) tác phẩm; hòa thì số review, rồi mã giảm dần (giống sort của MongoDB).
        self.popular_ranked = sorted(((s[5], s[0], w) for w, s in self.item_stats.items() if s[5] > 0), reverse=True)

    def avg(self, uid, work):
        entry = self.items[uid][work]
        return entry[0] / entry[1]


class Recommender:
    """Bản Python của từng truy vấn trong recommend.py (mức tác phẩm)."""

    def __init__(self, catalog, interactions):
        self.catalog = catalog
        self.data = interactions

    def seen(self, uid):
        """Tác phẩm người dùng đã review (ở bất kỳ ấn bản nào)."""
        return self.data.items.get(uid, {})

    def popular(self, uid, limit=10):
        seen = self.seen(uid)
        rows = []
        for liked, count, work in self.data.popular_ranked:
            if work not in seen and work in self.catalog.primary:
                rows.append({'asin': work, 'score': float(liked), 'support': count, 'method': 'popular'})
                if len(rows) >= limit:
                    break
        return rows

    def neighbors(self, uid):
        liked = self.data.liked.get(uid, [])[:CF_LIKED_LIMIT]
        if not liked:
            return []
        common = Counter()
        for work in liked:
            common.update(self.data.likers[work])
        common.pop(uid, None)
        pool = heapq.nsmallest(CF_CANDIDATE_NEIGHBORS, ((-c, v) for v, c in common.items() if c >= CF_MIN_COMMON))
        scored = []
        for negative_common, other in pool:
            shared = -negative_common
            similarity = shared / (len(liked) + len(self.data.liked[other]) - shared)
            scored.append((-similarity, other, similarity))
        scored.sort()
        return [(other, similarity) for _, other, similarity in scored[:CF_NEIGHBORS]]

    def collaborative(self, uid, limit=CANDIDATE_LIMIT, shrinkages=(CF_SHRINKAGE,), neighbors=None, min_support=CF_MIN_SUPPORT):
        """Trả về {shrinkage: rows}; láng giềng chỉ tính một lần cho nhiều hệ số.

        Chỉ giữ tác phẩm có ít nhất `min_support` láng giềng cùng thích (Cypher: WHERE support >= $min_support)."""
        neighbors = self.neighbors(uid) if neighbors is None else neighbors
        seen = self.seen(uid)
        centered = defaultdict(float)
        weight = defaultdict(float)
        support = Counter()
        for other, similarity in neighbors:
            other_mean = self.data.mean.get(other, 3.)
            for work in self.data.liked[other]:
                if work not in seen:
                    centered[work] += similarity * (self.data.avg(other, work) - other_mean)
                    weight[work] += similarity
                    support[work] += 1
        base = self.data.mean.get(uid, 3.)
        result = {}
        for shrink in shrinkages:
            rows = [{'asin': w, 'score': base + centered[w] / (wt + shrink), 'support': support[w], 'method': 'collaborative'}
                    for w, wt in weight.items() if wt + shrink > 0 and support[w] >= min_support]
            result[shrink] = heapq.nsmallest(limit, rows, key=lambda r: (-r['score'], -r['support'], r['asin']))
        return result

    def related(self, uid):
        seen = self.seen(uid)
        merged = {}
        for seed in self.data.recent_high.get(uid, []):
            for row in self.catalog.related_one(seed):
                if row['asin'] not in seen:
                    # via = phim gốc đóng góp điểm lớn nhất (giải thích "thường được mua cùng …"), như recommend.related_for_user.
                    current = merged.setdefault(row['asin'], {**row, 'score': 0., 'method': 'related', 'via': seed, '_best': 0.})
                    current['score'] += row['score']
                    if row['score'] > current['_best']:
                        current['_best'], current['via'] = row['score'], seed
        for row in merged.values():
            row.pop('_best', None)
        return sorted(merged.values(), key=lambda r: (-r['score'], r['asin']))

    def content(self, uid, limit=CANDIDATE_LIMIT):
        seeds = self.data.liked.get(uid, [])[:CONTENT_SEEDS]
        if not seeds:
            return []
        seen = self.seen(uid)
        preferred = set()
        seeds_by_attr = defaultdict(set)
        for seed in seeds:
            preferred |= self.catalog.formats.get(seed, set())
            for attr in self.catalog.attrs.get(seed, ()):
                seeds_by_attr[attr].add(seed)
        seed_hits = defaultdict(set)
        attr_hits = Counter()
        for attr, attr_seeds in seeds_by_attr.items():
            for candidate in self.catalog.attr_products.get(attr, ()):
                if self.catalog.work_of(candidate) not in seen:
                    seed_hits[candidate] |= attr_seeds
                    attr_hits[candidate] += 1
        pool = heapq.nsmallest(CONTENT_POOL, seed_hits, key=lambda a: (-len(seed_hits[a]), -attr_hits[a], a))
        rows = []
        for asin in pool:
            attributes = attr_hits[asin] + len(self.catalog.formats.get(asin, set()) & preferred)
            rows.append({'asin': asin, 'score': float(len(seed_hits[asin])) + .2 * attributes,
                         'support': len(seed_hits[asin]), 'method': 'content'})
        return heapq.nsmallest(limit, rows, key=lambda r: (-r['score'], r['asin']))

    def sentiment_rows(self, works):
        rows = []
        for work in works:
            stats = self.data.item_stats.get(work)
            if stats:
                available = stats[2] + stats[3] + stats[4]
                if available:
                    rows.append({'asin': work, 'score': stats[2] / available})
        return rows

    def hybrid(self, uid, cf_rows=None, related_rows=None, content_rows=None, normalization=None):
        cf_rows = self.collaborative(uid)[CF_SHRINKAGE] if cf_rows is None else cf_rows
        related_rows = self.related(uid) if related_rows is None else related_rows
        content_rows = self.content(uid) if content_rows is None else content_rows
        ids = {r['asin'] for r in cf_rows + related_rows + content_rows}
        return rank_hybrid({'collaborative': cf_rows, 'related': related_rows, 'content': content_rows,
                            'sentiment': self.sentiment_rows(ids)}, normalization=normalization)

    def recommend(self, uid, method, limit=10):
        if method == 'popular':
            rows = self.popular(uid, limit)
        elif method == 'collaborative':
            rows = self.collaborative(uid)[CF_SHRINKAGE]
        elif method == 'related':
            rows = self.related(uid)
        elif method == 'content':
            rows = self.content(uid)
        elif method == 'hybrid':
            rows = self.hybrid(uid)
        else:
            raise ValueError(method)
        fallback = not rows
        if fallback:
            rows = self.popular(uid, limit)
        return rows[:limit], fallback
