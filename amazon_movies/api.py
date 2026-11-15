"""REST API (Flask).

Hai khu tách biệt:
- Người dùng (công khai hoặc cần đăng nhập tài khoản thường): trang chủ, tìm phim, chi tiết phim, review, gợi ý cho tôi.
- Quản trị (cần đăng nhập tài khoản quản trị, cấu hình trong .env): tình trạng CSDL, đối soát, thống kê,
  phân tích gợi ý của bất kỳ người dùng nào, đồ thị Neo4j, thực nghiệm.
"""
from collections import OrderedDict
from datetime import datetime, timezone
from functools import wraps
from math import isfinite
import hmac, json, re, threading, time, uuid
from flask import Flask, request, jsonify, g, render_template
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash, check_password_hash
from .config import settings
from . import mongo, graph, algorithms
from .data import sentiment
from .keywords import KeywordIndex
from .recommend import recommend, related, popular, top_rated, METHODS

TEXT_RANK_CAP = 30000  # số review khớp tối đa còn xếp hạng theo độ liên quan (xem /api/reviews)
MIN_RATINGS_FOR_PERSONAL = 3  # dưới mức này trang "Gợi ý cho bạn" mời chấm nhanh vài phim

# Láng giềng ở mức tác phẩm, bỏ review bản sao — đúng bước chọn láng giềng của CF trong recommend.py.
SIMILAR_USERS = '''MATCH (u:User {reviewerID:$user})
CALL (u) { MATCH (u)-[r:REVIEWED]->(p:Product) WHERE NOT coalesce(r.copy,false)
       WITH coalesce(p.work,p.asin) AS w,avg(r.rating) AS rating,max(r.timestamp) AS lastReview WHERE rating>=4
       ORDER BY lastReview DESC,w ASC LIMIT $liked_limit RETURN collect(w) AS liked }
UNWIND liked AS w
MATCH (:Product {work:w})<-[nr:REVIEWED]-(other:User) WHERE other<>u AND NOT coalesce(nr.copy,false)
WITH liked,other,w,avg(nr.rating) AS rating WHERE rating>=4
WITH liked,other,count(DISTINCT w) AS common WHERE common >= $min_common
WITH liked,other,common ORDER BY common DESC,other.reviewerID LIMIT $candidate_neighbors
CALL (other) { MATCH (other)-[r:REVIEWED]->(p:Product) WHERE NOT coalesce(r.copy,false)
       WITH coalesce(p.work,p.asin) AS w,avg(r.rating) AS rating WHERE rating>=4 RETURN count(w) AS degree }
RETURN other.reviewerID AS reviewerID, coalesce(other.name,'') AS name, common,
       toFloat(common)/(size(liked)+degree-common) AS score, other.review_count AS review_count
ORDER BY score DESC, reviewerID LIMIT $limit'''


class TTLCache:
    def __init__(self, size=256, ttl=900):
        self.size, self.ttl, self.data, self.lock = size, ttl, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            item = self.data.get(key)
            if not item or item[0] < time.time():
                self.data.pop(key, None)
                return None
            self.data.move_to_end(key)
            return item[1]

    def set(self, key, value):
        with self.lock:
            self.data[key] = (time.time() + self.ttl, value)
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)

    def drop(self, predicate):
        with self.lock:
            for key in [k for k in self.data if predicate(k)]:
                self.data.pop(key, None)


def int_arg(name, default, low, high):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f'Tham số {name} phải là số nguyên')
    return min(high, max(low, value))


def display_name(name, reviewer_id):
    """Tên hiển thị cho người dùng cuối: tên chung chung của Amazon kèm 6 ký tự cuối mã để phân biệt."""
    return graph.user_label(name, reviewer_id, width=60)


def create_app(db=None, driver=None, config=settings, warmup=False):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 128 * 1024
    app.json.sort_keys = False
    if not config.app_secret: raise ValueError('Thiếu APP_SECRET trong .env')
    if db is None: app.mongo_client, db = mongo.connect(config)
    if driver is None: driver = graph.connect(config)
    signer = URLSafeTimedSerializer(config.app_secret, salt='movies-demo-v1')
    rec_cache = TTLCache(512, 900)
    shared = TTLCache(256, 600)
    keyword_index = {'value': None}

    def keywords_index():
        if keyword_index['value'] is None:
            keyword_index['value'] = KeywordIndex(db)
        return keyword_index['value']

    def cached(key, factory):
        value = shared.get(key)
        if value is None:
            value = factory()
            shared.set(key, value)
        return value

    def report(name):
        path = config.report_dir / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    @app.errorhandler(ValueError)
    def bad_request(exc): return jsonify(error=str(exc)), 400

    @app.errorhandler(404)
    def missing(exc): return jsonify(error='Không tìm thấy'), 404

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict): raise ValueError('Nội dung phải là JSON object')
        return data

    def token_data():
        value = request.headers.get('Authorization', '')
        if not value.startswith('Bearer '): return None
        try: return signer.loads(value[7:], max_age=86400)
        except (BadSignature, SignatureExpired): return False

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            data = token_data()
            if data is None: return jsonify(error='Cần đăng nhập'), 401
            if not data or 'user' not in data: return jsonify(error='Phiên đăng nhập không hợp lệ hoặc đã hết hạn'), 401
            g.user = db.users.find_one({'reviewerID': data['user'], 'is_demo': True})
            if not g.user: return jsonify(error='Tài khoản không tồn tại'), 401
            return fn(*args, **kwargs)
        return wrapped

    def admin_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            data = token_data()
            if data is None: return jsonify(error='Cần đăng nhập tài khoản quản trị'), 401
            if not data or not config.admin_password or data.get('admin') != config.admin_username:
                return jsonify(error='Chỉ tài khoản quản trị được xem mục này'), 403
            return fn(*args, **kwargs)
        return wrapped

    def synchronize(asin, uid):
        mongo.rebuild_stats(db, asin, uid)
        rec_cache.drop(lambda key: key[0] == uid)
        shared.drop(lambda key: key[0] == 'home' if isinstance(key, tuple) else False)
        try:
            # Ghi demo chỉ đồng bộ review của chính cặp người dùng–phim, không quét hàng chờ lịch sử.
            pending = list(db.reviews.find({'asin': asin, 'reviewerID': uid, 'synced': False}))
            product = db.products.find_one({'asin': asin})
            rows = [graph.product_row(product)]
            if product.get('work') and product['work'] != asin:
                rows.append(graph.product_row(db.products.find_one({'asin': product['work']})))
            graph.run(driver, graph.PRODUCTS, {'rows': rows}, config)
            graph.run(driver, graph.USERS, {'rows': [graph.user_row(db.users.find_one({'reviewerID': uid}))]}, config)
            graph.run(driver, graph.REVIEWS, {'rows': [graph.review_row(d) for d in pending]}, config)
            graph.acknowledge(db, pending)
            return True
        except Exception as exc:
            app.logger.warning('Đồng bộ chờ thử lại: %s', type(exc).__name__)
            return False

    def titles(asins):
        return {p['asin']: p.get('title', p['asin']) for p in db.products.find({'asin': {'$in': list(set(asins))}}, {'asin': 1, 'title': 1})}

    def product_list(cursor):
        return [mongo.public(d) for d in cursor]

    def with_names(items, key='reviewerID', name='reviewerName'):
        for r in items:
            r['display_name'] = display_name(r.get(name), r[key])
        return items

    # ------------------------------------------------------------------ hệ thống
    @app.get('/api/health')
    def health():
        status = {}
        try: db.command('ping'); status['mongodb'] = 'ok'
        except Exception: status['mongodb'] = 'unavailable'
        try: driver.verify_connectivity(); status['neo4j'] = 'ok'
        except Exception: status['neo4j'] = 'unavailable'
        return jsonify(status), 200 if all(v == 'ok' for v in status.values()) else 503

    # ------------------------------------------------------------------ tài khoản
    @app.post('/api/auth/register')
    def register():
        data = body(); username = str(data.get('username', '')).strip().lower(); password = data.get('password', '')
        if not re.fullmatch(r'[a-z0-9_]{3,32}', username): raise ValueError('Tên tài khoản gồm 3–32 chữ thường, số hoặc dấu gạch dưới')
        if username == config.admin_username: return jsonify(error='Tên tài khoản đã tồn tại'), 409
        if not isinstance(password, str) or not 10 <= len(password) <= 128: raise ValueError('Mật khẩu cần 10–128 ký tự')
        uid = 'DEMO_' + uuid.uuid4().hex
        display = str(data.get('display_name') or username).strip()[:100] or username
        try: db.users.insert_one({'_id': uid, 'reviewerID': uid, 'username': username, 'display_name': display,
                                  'password_hash': generate_password_hash(password), 'is_demo': True, 'synced': False,
                                  'stats': {'review_count': 0, 'avg_rating': 0.}})
        except DuplicateKeyError: return jsonify(error='Tên tài khoản đã tồn tại'), 409
        try:
            graph.run(driver, graph.USERS, {'rows': [graph.user_row(db.users.find_one({'reviewerID': uid}))]}, config)
            db.users.update_one({'_id': uid}, {'$set': {'synced': True}})
        except Exception:
            app.logger.warning('Tài khoản mới chờ đồng bộ đồ thị')
        return jsonify(role='user', reviewerID=uid, username=username, display_name=display, token=signer.dumps({'user': uid})), 201

    @app.post('/api/auth/login')
    def login():
        data = body(); username = str(data.get('username', '')).strip().lower(); password = data.get('password')
        if config.admin_password and username == config.admin_username:
            if isinstance(password, str) and hmac.compare_digest(password.encode(), config.admin_password.encode()):
                return jsonify(role='admin', username=username, display_name='Quản trị', token=signer.dumps({'admin': username}))
            return jsonify(error='Sai tài khoản hoặc mật khẩu'), 401
        user = db.users.find_one({'username': username, 'is_demo': True})
        if not user or not isinstance(password, str) or not check_password_hash(user['password_hash'], password):
            return jsonify(error='Sai tài khoản hoặc mật khẩu'), 401
        return jsonify(role='user', reviewerID=user['reviewerID'], username=user['username'], display_name=user.get('display_name'),
                       token=signer.dumps({'user': user['reviewerID']}))

    @app.get('/api/auth/me')
    @authenticated
    def me():
        return jsonify(mongo.public(g.user))

    # ------------------------------------------------------------------ khu người dùng: trang chủ, tìm kiếm, phim
    @app.get('/api/home')
    def home_data():
        limit = int_arg('limit', 12, 4, 24)

        def compute():
            pop = popular(db, None, limit)
            prods = {p['asin']: mongo.public(p) for p in db.products.find({'asin': {'$in': [r['asin'] for r in pop]}}, mongo.LIST_PROJECTION)}
            genres = cached('facets', lambda: mongo.facets(db))['genres'][:18]
            counts = mongo.counts(db)
            return {
                'popular': [prods[r['asin']] for r in pop if r['asin'] in prods],
                'top_rated': [mongo.public(p) for p in top_rated(db, limit)],
                'genres': genres,
                'counts': {'works': counts['works'], 'reviews': counts['reviews'],
                           'users': db.users.count_documents({'is_demo': {'$ne': True}})},
            }
        return jsonify(cached(('home', limit), compute))

    @app.get('/api/facets')
    def facets():
        return jsonify(cached('facets', lambda: mongo.facets(db)))

    @app.get('/api/products')
    def products():
        page = int_arg('page', 1, 1, 10000); limit = int_arg('limit', 20, 1, 100)
        try:
            low = float(request.args['min_price']) if request.args.get('min_price') else None
            high = float(request.args['max_price']) if request.args.get('max_price') else None
        except ValueError:
            raise ValueError('Giá phải là số')
        if any(value is not None and (not isfinite(value) or value < 0) for value in [low, high]): raise ValueError('Giá phải là số hữu hạn không âm')
        if low is not None and high is not None and low > high: raise ValueError('Khoảng giá không hợp lệ')
        return jsonify(mongo.search_products(db, request.args.get('q', '').strip(), request.args.get('category') or None,
                                             request.args.get('format') or None, low, high, page, limit, request.args.get('sort')))

    @app.get('/api/products/<asin>')
    def detail(asin):
        doc = db.products.find_one({'asin': asin, 'active': True}, {'also_buy': 0, 'also_view': 0})
        if not doc: return jsonify(error='Sản phẩm không tồn tại'), 404
        work = doc.get('work') or asin
        primary = doc if work == asin else (db.products.find_one({'asin': work}, {'also_buy': 0, 'also_view': 0}) or doc)
        result = mongo.public(doc)
        stats = primary.get('stats', {})
        result.update(work=work, work_title=primary['title'], editions=primary.get('editions') or [],
                      price_any=primary.get('price_any', doc.get('price')),
                      work_stats={'reviews': stats.get('work_reviews', stats.get('review_count', 0)),
                                  'avg_rating': stats.get('work_avg', stats.get('avg_rating')),
                                  'stars': stats.get('work_stars', stats.get('stars', {})),
                                  'sentiment': stats.get('work_sentiment', stats.get('sentiment', {}))})
        return jsonify(result)

    @app.get('/api/products/<asin>/related')
    def product_related(asin):
        depth = int_arg('steps', 2, 1, 2)
        doc = db.products.find_one({'asin': asin}, {'work': 1})
        seed = (doc or {}).get('work') or asin
        rows = related(driver, seed, depth, int_arg('limit', 12, 1, 50), config)
        prods = {p['asin']: mongo.public(p) for p in db.products.find({'asin': {'$in': [r['asin'] for r in rows]}}, mongo.LIST_PROJECTION)}
        return jsonify(steps=depth, seed=seed, items=[{**r, 'product': prods.get(r['asin'])} for r in rows])

    @app.get('/api/products/<asin>/keywords')
    def keywords(asin):
        return jsonify(keywords_index().for_product(db, asin, int_arg('limit', 12, 3, 30)))

    # ------------------------------------------------------------------ review
    @app.get('/api/reviews')
    def reviews():
        query = {}; q = request.args.get('q', '').strip()
        if q: query['$text'] = {'$search': q}
        for key in ['asin', 'reviewerID']:
            if request.args.get(key): query[key] = request.args[key]
        if request.args.get('work'):
            # Mọi ấn bản của một tác phẩm, mỗi review chỉ một lần (bỏ bản sao).
            query['work'] = request.args['work']
            query['is_copy'] = {'$ne': True}
        elif request.args.get('unique') == '1' or q:
            query['is_copy'] = {'$ne': True}
        if request.args.get('sentiment') in ('positive', 'neutral', 'negative'): query['sentiment.label'] = request.args['sentiment']
        limit = int_arg('limit', 20, 1, 100); page = int_arg('page', 1, 1, 10000)
        sort = request.args.get('sort', 'relevance' if q else 'recent')
        order = [('vote', -1), ('timestamp', -1), ('_id', 1)] if sort == 'helpful' else [('timestamp', -1), ('_id', 1)]
        total_capped = False
        if q:
            # Xếp hạng toàn văn phải chấm điểm mọi review khớp. Với từ quá phổ biến ("good": 867.000 review) việc đó
            # mất hàng chục giây, nên khi số review khớp vượt TEXT_RANK_CAP thì trả kết quả chưa xếp hạng và báo rõ.
            total = db.reviews.count_documents(query, limit=TEXT_RANK_CAP + 1)
            total_capped = total > TEXT_RANK_CAP
            if total_capped:
                total, sort = TEXT_RANK_CAP, 'unranked'
                cursor = db.reviews.find(query)
            elif sort == 'relevance':
                cursor = db.reviews.find(query, {'text_score': {'$meta': 'textScore'}}).sort([('text_score', {'$meta': 'textScore'})])
            else:
                cursor = db.reviews.find(query).sort(order)
        else:
            cursor = db.reviews.find(query).sort(order)
            total = db.reviews.count_documents(query) if query else db.reviews.estimated_document_count()
        items = with_names([mongo.public(r) for r in cursor.skip((page - 1) * limit).limit(limit)])
        names = titles(r['asin'] for r in items)
        for r in items: r['product_title'] = names.get(r['asin'], r['asin'])
        return jsonify(items=items, total=total, total_capped=total_capped, page=page, limit=limit, sort=sort)

    def review_input(data, current=None):
        current = current or {}
        rating = data.get('overall', current.get('overall'))
        content = data.get('reviewText', current.get('reviewText', ''))
        summary = data.get('summary', current.get('summary', ''))
        if isinstance(rating, bool) or not isinstance(rating, (int, float)) or rating not in [1, 2, 3, 4, 5]: raise ValueError('Số sao phải là số nguyên từ 1 đến 5')
        if not isinstance(content, str) or len(content) > 20000 or not isinstance(summary, str) or len(summary) > 500: raise ValueError('Nội dung hoặc tiêu đề review không hợp lệ')
        return float(rating), content.strip(), summary.strip()

    @app.post('/api/reviews')
    @authenticated
    def write_review():
        data = body(); asin = str(data.get('asin', ''))
        product = db.products.find_one({'asin': asin, 'active': True}, {'_id': 1, 'work': 1, 'title': 1})
        if not product: return jsonify(error='Sản phẩm không tồn tại'), 404
        rating, content, summary = review_input(data)
        work = product.get('work') or asin
        existing = db.reviews.find_one({'reviewerID': g.user['reviewerID'], 'work': work, 'is_copy': {'$ne': True}}, {'_id': 1})
        if existing:
            return jsonify(error='Bạn đã đánh giá phim này. Hãy sửa đánh giá cũ thay vì viết thêm.', review_id=existing['_id']), 409
        now = datetime.now(timezone.utc); rid = 'DEMO_REVIEW_' + uuid.uuid4().hex
        doc = {'_id': rid, 'review_id': rid, 'reviewerID': g.user['reviewerID'], 'reviewerName': g.user['display_name'], 'asin': asin,
               'work': work, 'overall': rating, 'summary': summary, 'reviewText': content, 'vote': 0, 'source_vote': 0, 'demo_vote_count': 0,
               'verified': False, 'style': {}, 'formats': [], 'timestamp': int(now.timestamp()), 'review_date': now, 'sentiment': sentiment(content),
               'source': 'demo', 'is_demo': True, 'is_copy': False, 'version': 1, 'synced': False, 'synced_version': 0}
        db.reviews.insert_one(doc)
        synced = synchronize(asin, g.user['reviewerID'])
        return jsonify(review_id=rid, synced=synced, sentiment=doc['sentiment']), 201 if synced else 202

    @app.put('/api/reviews/<rid>')
    @authenticated
    def edit_review(rid):
        doc = db.reviews.find_one({'_id': rid, 'reviewerID': g.user['reviewerID'], 'is_demo': True})
        if not doc: return jsonify(error='Không tìm thấy review thuộc tài khoản này'), 404
        rating, content, summary = review_input(body(), doc)
        value = sentiment(content)
        db.reviews.update_one({'_id': rid}, {'$set': {'overall': rating, 'reviewText': content, 'summary': summary, 'sentiment': value, 'synced': False}, '$inc': {'version': 1}})
        synced = synchronize(doc['asin'], doc['reviewerID'])
        return jsonify(review_id=rid, synced=synced, sentiment=value), 200 if synced else 202

    @app.delete('/api/reviews/<rid>')
    @authenticated
    def delete_review(rid):
        doc = db.reviews.find_one({'_id': rid, 'reviewerID': g.user['reviewerID'], 'is_demo': True})
        if not doc: return jsonify(error='Không tìm thấy review thuộc tài khoản này'), 404
        try:
            # Xóa bên Neo4j trước: nếu Neo4j lỗi thì giữ nguyên MongoDB để hai CSDL không lệch nhau.
            graph.run(driver, 'MATCH ()-[r:REVIEWED {review_id:$id}]->() DELETE r', {'id': rid}, config)
        except Exception:
            return jsonify(error='Chưa xóa được vì CSDL đồ thị tạm thời không phản hồi. Hãy thử lại sau.'), 503
        db.reviews.delete_one({'_id': rid})
        db.helpful_votes.delete_many({'review_id': rid})
        synced = synchronize(doc['asin'], doc['reviewerID'])
        return jsonify(deleted=rid, synced=synced)

    @app.post('/api/reviews/<rid>/helpful')
    @authenticated
    def helpful(rid):
        doc = db.reviews.find_one({'_id': rid})
        if not doc: return jsonify(error='Review không tồn tại'), 404
        if doc['reviewerID'] == g.user['reviewerID']: return jsonify(error='Không thể bình chọn review của chính mình'), 400
        try: db.helpful_votes.insert_one({'review_id': rid, 'reviewerID': g.user['reviewerID']})
        except DuplicateKeyError: return jsonify(error='Bạn đã bình chọn review này'), 409
        db.reviews.update_one({'_id': rid}, {'$inc': {'vote': 1, 'demo_vote_count': 1, 'version': 1}, '$set': {'synced': False}})
        return jsonify(synced=synchronize(doc['asin'], doc['reviewerID']), vote=doc.get('vote', 0) + 1)

    # ------------------------------------------------------------------ người đánh giá (công khai)
    @app.get('/api/users/<uid>/profile')
    def user_profile(uid):
        user = db.users.find_one({'reviewerID': uid})
        if not user: return jsonify(error='Người dùng không tồn tại'), 404
        limit = int_arg('limit', 20, 1, 100); page = int_arg('page', 1, 1, 10000)
        query = {'reviewerID': uid, 'is_copy': {'$ne': True}}
        revs = with_names([mongo.public(r) for r in db.reviews.find(query).sort([('timestamp', -1), ('_id', 1)]).skip((page - 1) * limit).limit(limit)])
        names = titles(r['asin'] for r in revs)
        for r in revs: r['product_title'] = names.get(r['asin'], r['asin'])
        public_user = {k: v for k, v in mongo.public(user).items() if k not in ('synced', 'username')}
        public_user['display_name'] = display_name(user.get('display_name'), uid)
        return jsonify(user=public_user, reviews=revs, page=page, limit=limit, total_reviews=db.reviews.count_documents(query))

    # ------------------------------------------------------------------ gợi ý cho người dùng đang đăng nhập
    def reasons_for(item, via_titles):
        """Lý do bằng lời cho một phim được gợi ý, sắp theo mức đóng góp vào điểm lai."""
        parts = []
        weights = algorithms.HYBRID_WEIGHTS
        components = item.get('components') or {item.get('method'): 1.}
        for method, value in sorted(components.items(), key=lambda kv: -weights.get(kv[0], 0) * kv[1]):
            via = (item.get('via') or {}).get(method) if isinstance(item.get('via'), dict) else item.get('via')
            support = (item.get('support') or {}).get(method) if isinstance(item.get('support'), dict) else item.get('support')
            if method == 'collaborative':
                parts.append(f'{support} người có gu giống bạn đã chấm phim này từ 4 sao' if support else 'Người có gu giống bạn chấm phim này cao')
            elif method == 'related' and via:
                parts.append(f'Thường được mua/xem cùng “{via_titles.get(via, via)}”')
            elif method == 'content' and via:
                parts.append(f'Cùng thể loại hoặc diễn viên với “{via_titles.get(via, via)}” bạn đã thích')
        return parts[:2]

    @app.get('/api/me/recommendations')
    @authenticated
    def my_recommendations():
        uid = g.user['reviewerID']
        limit = int_arg('limit', 12, 1, 30)
        rated = db.reviews.count_documents({'reviewerID': uid})
        key = (uid, 'for-you', limit)
        result = rec_cache.get(key)
        if result is None:
            data = recommend(db, driver, uid, 'hybrid', limit, config=config)
            via = set()
            for r in data['items']:
                values = r.get('via')
                via.update(values.values() if isinstance(values, dict) else ([values] if values else []))
            via_titles = titles(via)
            items = [{'product': r['product'], 'reasons': [] if data['fallback_to_popular'] else reasons_for(r, via_titles)} for r in data['items']]
            result = {'items': items, 'fallback_to_popular': data['fallback_to_popular']}
            rec_cache.set(key, result)
        return jsonify({**result, 'rated': rated, 'needs_more_ratings': rated < MIN_RATINGS_FOR_PERSONAL,
                        'min_ratings': MIN_RATINGS_FOR_PERSONAL})

    @app.get('/api/me/to-rate')
    @authenticated
    def to_rate():
        rows = popular(db, g.user['reviewerID'], int_arg('limit', 12, 4, 30))
        prods = {p['asin']: mongo.public(p) for p in db.products.find({'asin': {'$in': [r['asin'] for r in rows]}}, mongo.LIST_PROJECTION)}
        return jsonify(items=[prods[r['asin']] for r in rows if r['asin'] in prods])

    # ------------------------------------------------------------------ khu quản trị
    @app.get('/api/admin/overview')
    @admin_required
    def admin_overview():
        status = {}
        try: db.command('ping'); status['mongodb'] = 'ok'
        except Exception: status['mongodb'] = 'unavailable'
        neo = {}
        try:
            driver.verify_connectivity(); status['neo4j'] = 'ok'
            # Đếm bằng count store của Neo4j (không quét đồ thị).
            for name, query in [('Product', 'MATCH (n:Product) RETURN count(n) AS n'), ('User', 'MATCH (n:User) RETURN count(n) AS n'),
                                ('REVIEWED', 'MATCH ()-[r:REVIEWED]->() RETURN count(r) AS n'),
                                ('SIMILAR_TO', 'MATCH ()-[r:SIMILAR_TO]->() RETURN count(r) AS n'),
                                ('ALSO_BOUGHT', 'MATCH ()-[r:ALSO_BOUGHT]->() RETURN count(r) AS n'),
                                ('ALSO_VIEWED', 'MATCH ()-[r:ALSO_VIEWED]->() RETURN count(r) AS n')]:
                neo[name] = graph.run(driver, query, config=config)[0]['n']
        except Exception:
            status['neo4j'] = 'unavailable'
        counts = mongo.counts(db)
        mongo_live = {'Product': counts['products'], 'User': db.users.count_documents({}), 'REVIEWED': counts['review_rows']}
        editions = report('buoi6_editions.json') or {}
        reports = {}
        for path in sorted(config.report_dir.glob('*.json')):
            reports[path.name] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        return jsonify(
            health=status,
            counts={**counts, 'real_users': db.users.count_documents({'is_demo': {'$ne': True}}),
                    'demo_users': db.users.count_documents({'is_demo': True}), 'demo_reviews': db.reviews.count_documents({'is_demo': True})},
            live_reconciliation={'mongodb': mongo_live, 'neo4j': neo,
                                 'match': {k: mongo_live[k] == neo.get(k) for k in mongo_live} if neo else {}},
            sync={'pending_reviews': db.reviews.count_documents({'synced': False}),
                  'reviews_with_error': db.reviews.count_documents({'sync_error': {'$exists': True}}),
                  'pending_users': db.users.count_documents({'synced': False})},
            reconciliation=report('buoi2_reconciliation.json'),
            editions={k: editions.get(k) for k in ['rule', 'works_total', 'works_with_several_editions', 'products_in_those_works', 'review_rows',
                                                   'copy_rows', 'unique_reviews', 'identical_rows_across_works', 'identical_rows_note', 'largest_works']},
            settings={'cf_shrinkage': algorithms.CF_SHRINKAGE, 'cf_min_support': algorithms.CF_MIN_SUPPORT,
                      'hybrid_normalization': algorithms.HYBRID_NORMALIZATION,
                      'hybrid_weights': algorithms.HYBRID_WEIGHTS, 'like_threshold': algorithms.LIKE_THRESHOLD,
                      'cf_neighbors': algorithms.CF_NEIGHBORS, 'cf_min_common': algorithms.CF_MIN_COMMON},
            reports=reports,
        )

    @app.post('/api/admin/verify')
    @admin_required
    def admin_verify():
        started = time.perf_counter()
        result = graph.verify(db, driver, config)
        return jsonify({**result, 'seconds': round(time.perf_counter() - started, 2)})

    @app.get('/api/recommendations/<user>')
    @admin_required
    def recommendations(user):
        method = request.args.get('method', 'hybrid')
        if method not in METHODS: raise ValueError('Phương pháp phải là một trong: ' + ', '.join(METHODS))
        limit = int_arg('limit', 10, 1, 50)
        key = (user, method, limit)
        result = rec_cache.get(key)
        if result is None:
            started = time.perf_counter()
            result = recommend(db, driver, user, method, limit, config=config)
            result['elapsed_ms'] = round((time.perf_counter() - started) * 1000)
            rec_cache.set(key, result)
            result = {**result, 'cached': False}
        else:
            result = {**result, 'cached': True}
        return jsonify(result)

    @app.get('/api/users/<uid>/similar')
    @admin_required
    def similar_users(uid):
        def compute():
            rows = graph.run(driver, '''MATCH (u:User {reviewerID:$uid})-[s:SIMILAR_TO]->(v:User)
                RETURN v.reviewerID AS reviewerID, coalesce(v.name,'') AS name, s.score AS score, v.review_count AS review_count
                ORDER BY s.score DESC, v.reviewerID LIMIT 10''', {'uid': uid}, config)
            if rows:
                source = 'SIMILAR_TO (GDS Node Similarity, Jaccard trên tác phẩm >= 4 sao)'
            else:
                rows = graph.run(driver, SIMILAR_USERS, {'user': uid, 'liked_limit': algorithms.CF_LIKED_LIMIT, 'min_common': algorithms.CF_MIN_COMMON,
                                                         'candidate_neighbors': algorithms.CF_CANDIDATE_NEIGHBORS, 'limit': 10}, config)
                source = 'Tính trực tiếp bằng Cypher (Jaccard trên tác phẩm >= 4 sao, như bước chọn láng giềng của CF)'
            for r in rows:
                r['display_name'] = display_name(r.pop('name', ''), r['reviewerID'])
            return {'source': source, 'items': rows}
        return jsonify(cached(('similar', uid), compute))

    @app.get('/api/users/sample')
    @admin_required
    def sample_users():
        def compute():
            rows = list(db.users.find({'is_demo': {'$ne': True}, 'stats.review_count': {'$gte': 30, '$lte': 120}},
                                      {'reviewerID': 1, 'display_name': 1, 'stats': 1}).sort([('stats.review_count', -1), ('_id', 1)]).limit(8))
            for r in rows:
                r['display_name'] = display_name(r.get('display_name'), r['reviewerID'])
            return [mongo.public(r) for r in rows]
        return jsonify(items=cached('sample_users', compute))

    @app.get('/api/statistics')
    @admin_required
    def statistics():
        return jsonify(mongo.dashboard(db, config=config, refresh=request.args.get('refresh') == '1'))

    @app.get('/api/graph/ego')
    @admin_required
    def graph_ego():
        asin = request.args.get('asin', '').strip() or None
        user = (request.args.get('user', '') or request.args.get('reviewerID', '')).strip() or None
        if not asin and not user: raise ValueError('Cần cung cấp tham số asin hoặc user')
        return jsonify(graph.ego_graph(driver, asin=asin, user=user, limit=int_arg('limit', 25, 5, 50), config=config))

    @app.get('/api/analytics/communities')
    @admin_required
    def analytics_communities():
        if 'community' in request.args:
            cid = int_arg('community', 0, -1, 10**12)
            cursor = db.products.find({'active': True, 'stats.community': cid}, mongo.LIST_PROJECTION).sort([('stats.pagerank', -1), ('stats.review_count', -1)]).limit(int_arg('limit', 20, 1, 100))
            return jsonify(community=cid, size=db.products.count_documents({'active': True, 'stats.community': cid}), items=product_list(cursor))
        data = report('buoi4_graph_analytics.json')
        return (jsonify(data), 200) if data else (jsonify(error='Chưa chạy phân tích đồ thị'), 404)

    @app.get('/api/experiments')
    @admin_required
    def experiments():
        return jsonify({key: report(name) for key, name in [('graph_analytics', 'buoi4_graph_analytics.json'), ('evaluation', 'buoi4_evaluation.json'),
                                                            ('index_benchmark', 'buoi4_index_benchmark.json'), ('db_comparison', 'buoi4_db_comparison.json'),
                                                            ('similarity', 'buoi3_gds_similarity.json'), ('reconciliation', 'buoi2_reconciliation.json'),
                                                            ('import', 'buoi2_mongodb_import.json'), ('editions', 'buoi6_editions.json')]})

    @app.get('/')
    def root():
        if request.args.get('format') == 'json':
            return jsonify(project='Amazon Movies & TV', health='/api/health', products='/api/products', home='/api/home')
        return render_template('index.html')

    if warmup:
        def warm():
            # Nạp trước dữ liệu đồ thị vào page cache để lần gợi ý đầu tiên khi demo không chậm.
            try:
                graph.run(driver, 'MATCH ()-[r:REVIEWED]->() RETURN count(r.rating) AS n', config=config)
                users = [u['reviewerID'] for u in db.users.find({'is_demo': {'$ne': True}, 'stats.review_count': {'$gte': 30, '$lte': 120}}, {'reviewerID': 1}).sort([('stats.review_count', -1), ('_id', 1)]).limit(2)]
                for uid in users:
                    recommend(db, driver, uid, 'hybrid', 10, config=config)
                mongo.dashboard(db, config=config)
                keywords_index()
                # Nạp trước Text Index của reviews và products để lần tìm kiếm đầu tiên không phải đọc đĩa.
                for words in ['good great movie', 'masterpiece boring story']:
                    db.reviews.count_documents({'$text': {'$search': words}}, limit=TEXT_RANK_CAP + 1)
                db.products.count_documents({'active': True, '$text': {'$search': 'star wars season'}})
                app.logger.info('Đã làm nóng bộ nhớ đệm')
            except Exception as exc:
                app.logger.warning('Không làm nóng được: %s', type(exc).__name__)
        threading.Thread(target=warm, daemon=True).start()

    return app
