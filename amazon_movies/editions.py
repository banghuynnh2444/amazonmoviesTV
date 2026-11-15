"""Buổi 6: gom các ấn bản (DVD, Blu-ray, Region Free…) của cùng một phim thành một tác phẩm.

Amazon hiển thị chung review cho mọi ấn bản trong một trang sản phẩm, nên bộ dữ liệu chứa cùng một review
(cùng người, cùng ngày, cùng số sao, cùng nội dung) ở nhiều mã asin. Hai mã được coi là ấn bản của cùng một
tác phẩm khi chung ít nhất `min_share` (80%) review của mã ít review hơn và ít nhất `min_common` review.
Ngưỡng này tách được các mùa khác nhau của một series (chỉ chung khoảng 20% review do người dùng tự chép).

Trong mỗi nhóm review trùng thuộc cùng một tác phẩm, giữ một dòng gốc (ở ấn bản đại diện nếu có) và đánh
dấu các dòng còn lại `is_copy = true`. Dữ liệu gốc không bị xóa: trang của từng ấn bản vẫn hiện đủ review.
"""
from collections import Counter, defaultdict
import time
from pymongo import UpdateOne
from .config import settings
from .data import batches, write_json, brand_name, strip_html
from . import graph

COPY_KEY = {'u': '$reviewerID', 't': '$timestamp', 'o': '$overall', 's': '$summary', 'h': {'$substrCP': ['$reviewText', 0, 200]}}


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def clean_existing(db, driver, config=settings):
    """Áp dụng quy tắc làm sạch mới (Brand rác, thẻ HTML) cho dữ liệu đã nạp; giữ giá trị gốc ở *_raw."""
    changed_brand, changed_title, junk_names = [], [], set()
    for p in db.products.find({}, {'asin': 1, 'brand': 1, 'title': 1, 'main_cat': 1, 'description': 1}):
        update = {}
        cleaned = brand_name(p.get('brand', ''))
        if cleaned != p.get('brand', ''):
            update.update(brand=cleaned, brand_raw=p.get('brand', ''))
            junk_names.add(p.get('brand', ''))
            changed_brand.append(p['asin'])
        title = strip_html(p.get('title', ''))
        if title != p.get('title', ''):
            if not title:
                description = strip_html(p.get('description') or '')
                title = description[:80].rsplit(' ', 1)[0] if description else f'Phim chưa rõ tên ({p["asin"]})'
            update.update(title=title, title_raw=p['title'])
            changed_title.append(p['asin'])
        main_cat = strip_html(p.get('main_cat') or '')
        if main_cat != (p.get('main_cat') or ''):
            update.update(main_cat=main_cat)
        if update:
            db.products.update_one({'_id': p['_id']}, {'$set': update})
    if junk_names:
        graph.run(driver, 'MATCH (b:Brand) WHERE b.name IN $names DETACH DELETE b', {'names': sorted(junk_names)}, config)
    relinked = relink_brands(db, driver, config)
    for doc in db.products.find({'asin': {'$in': changed_title}}, {'asin': 1, 'title': 1}):
        graph.run(driver, 'MATCH (p:Product {asin:$asin}) SET p.title=$title', {'asin': doc['asin'], 'title': doc['title']}, config)
    return {'brand_changed': len(changed_brand), 'brand_relinked': relinked, 'junk_brand_values': sorted(junk_names),
            'titles_fixed': len(changed_title)}


def relink_brands(db, driver, config=settings):
    """Brand chỉ đổi cách viết (khoảng trắng, tiền tố 'by'): nối lại vào nút Brand có tên đã chuẩn hóa."""
    rows = [{'asin': p['asin'], 'brand': p['brand']} for p in db.products.find(
        {'brand_raw': {'$exists': True}, 'brand': {'$ne': ''}, 'active': True}, {'asin': 1, 'brand': 1})]
    for chunk in batches(rows, 2000):
        graph.run(driver, 'UNWIND $rows AS row MATCH (p:Product {asin:row.asin}) MERGE (b:Brand {name:row.brand}) MERGE (p)-[:BY_BRAND]->(b)',
                  {'rows': chunk}, config)
    return len(rows)


def push_work_properties(db, driver, config=settings):
    """Ghi tác phẩm, ấn bản đại diện và thống kê tác phẩm lên nút Product; nút không có trong MongoDB thì work = asin."""
    rows = [{'asin': p['asin'], 'work': p.get('work') or p['asin'], 'primary': p.get('primary', True) is not False,
             'work_reviews': int(p.get('stats', {}).get('work_reviews', 0)), 'work_avg': float(p.get('stats', {}).get('work_avg') or 0.)}
            for p in db.products.find({}, {'asin': 1, 'work': 1, 'primary': 1, 'stats.work_reviews': 1, 'stats.work_avg': 1})]
    for chunk in batches(rows, 5000):
        graph.run(driver, 'UNWIND $rows AS row MATCH (p:Product {asin:row.asin}) '
                          'SET p.work=row.work, p.primary=row.primary, p.work_reviews=row.work_reviews, p.work_avg=row.work_avg',
                  {'rows': chunk}, config)
    graph.run(driver, 'MATCH (p:Product) WHERE p.work IS NULL SET p.work = p.asin, p.primary = true', config=config)
    return len(rows)


def duplicate_groups(db):
    """Các nhóm review giống hệt nhau (cùng người, ngày, số sao, tiêu đề, 200 ký tự đầu) có từ 2 dòng trở lên."""
    return [g['rows'] for g in db.reviews.aggregate([
        {'$match': {'is_demo': False}},
        {'$group': {'_id': COPY_KEY, 'rows': {'$push': {'id': '$_id', 'asin': '$asin'}}, 'n': {'$sum': 1}}},
        {'$match': {'n': {'$gt': 1}}},
        {'$project': {'_id': 0, 'rows': 1}}], allowDiskUse=True)]


def mark_duplicate_groups(db, groups=None):
    """Ghi dup_group (mã dòng nhỏ nhất của nhóm) lên mọi dòng thuộc một nhóm review giống hệt nhau.

    Bản sao trong cùng tác phẩm đã bị đánh dấu is_copy; các dòng giống hệt nhau còn lại nằm ở những tác phẩm khác
    nhau (ví dụ các mùa của một series). Đánh giá dùng dup_group để không chia một review giữa Train và Test."""
    groups = duplicate_groups(db) if groups is None else groups
    db.reviews.update_many({'dup_group': {'$exists': True}}, {'$unset': {'dup_group': ''}})
    operations = [UpdateOne({'_id': r['id']}, {'$set': {'dup_group': min(x['id'] for x in rows)}}) for rows in groups for r in rows]
    for chunk in batches(operations, 5000):
        db.reviews.bulk_write(chunk, ordered=False)
    return {'groups': len(groups), 'rows': len(operations)}


def sync_work_fields(db, driver, config=settings):
    """Chạy lại an toàn: bổ sung reviews.work còn thiếu, tạo index, đẩy thuộc tính tác phẩm và Brand sang Neo4j."""
    filled = db.reviews.update_many({'work': {'$exists': False}}, [{'$set': {'work': '$asin'}}]).modified_count
    products = db.products.update_many({'work': {'$exists': False}}, [{'$set': {'work': '$asin', 'primary': True, 'work_size': 1}}]).modified_count
    db.reviews.create_index([('work', 1), ('is_copy', 1)])
    db.products.create_index([('work', 1)])
    db.reviews.create_index([('is_copy', 1)], name='copy_rows', partialFilterExpression={'is_copy': True})
    db.reviews.create_index([('is_demo', 1)], name='demo_rows', partialFilterExpression={'is_demo': True})
    db.reviews.create_index([('sync_error', 1)], name='sync_error_rows', partialFilterExpression={'sync_error': {'$exists': True}})
    graph.run(driver, 'CREATE INDEX product_work IF NOT EXISTS FOR (p:Product) ON (p.work)', config=config)
    return {'reviews_work_filled': filled, 'products_work_filled': products,
            'products_pushed': push_work_properties(db, driver, config), 'brand_relinked': relink_brands(db, driver, config)}


def build_works(db, driver, config=settings, min_share=.8, min_common=3):
    started = time.time()
    counts = {p['asin']: p['stats']['review_count'] for p in db.products.find({'active': True}, {'asin': 1, 'stats.review_count': 1})}
    groups = duplicate_groups(db)

    # 1. Số review chung của từng cặp mã → gom thành tác phẩm theo ngưỡng.
    shared = Counter()
    for rows in groups:
        asins = sorted({r['asin'] for r in rows if r['asin'] in counts})
        for i in range(len(asins)):
            for j in range(i + 1, len(asins)):
                shared[(asins[i], asins[j])] += 1
    uf = UnionFind()
    linked = 0
    for (a, b), n in shared.items():
        if n >= min_common and n >= min_share * min(counts[a], counts[b]):
            uf.union(a, b)
            linked += 1
    members = defaultdict(list)
    for asin in list(uf.parent):
        members[uf.find(asin)].append(asin)
    clusters = [sorted(v) for v in members.values() if len(v) > 1]

    # 2. Ấn bản đại diện: nhiều review nhất, rồi có giá, rồi tên ngắn nhất, rồi mã nhỏ nhất.
    info = {p['asin']: p for p in db.products.find({'asin': {'$in': [a for c in clusters for a in c]}},
                                                  {'asin': 1, 'title': 1, 'price': 1, 'formats': 1, 'stats.review_count': 1})}
    rep_of = {}
    reps = {}
    for c in clusters:
        rep = min(c, key=lambda a: (-counts[a], info[a].get('price') is None, len(info[a]['title']), a))
        reps[rep] = c
        for a in c:
            rep_of[a] = rep

    # 3. Đánh dấu bản sao: trong mỗi nhóm review trùng, các dòng thuộc cùng một tác phẩm (kể cả hai dòng của cùng
    #    một mã chỉ khác số lượt hữu ích) chỉ giữ một dòng gốc, ưu tiên dòng ở ấn bản đại diện.
    copies = []
    for rows in groups:
        by_work = defaultdict(list)
        for r in rows:
            by_work[rep_of.get(r['asin'], r['asin'])].append(r)
        for rep, rs in by_work.items():
            if len(rs) < 2:
                continue
            primary = min(rs, key=lambda r: (r['asin'] != rep, r['asin'], r['id']))
            copies.extend((r['id'], primary['id']) for r in rs if r is not primary)

    # Mọi review mang mã tác phẩm (mặc định = asin) để tra cứu theo index reviews.work.
    db.reviews.update_many({}, [{'$set': {'is_copy': False, 'work': '$asin'}}, {'$unset': 'copy_of'}])
    for chunk in batches(copies, 5000):
        db.reviews.bulk_write([UpdateOne({'_id': rid}, {'$set': {'is_copy': True, 'copy_of': pid}}) for rid, pid in chunk], ordered=False)
    for rep, c in reps.items():
        db.reviews.update_many({'asin': {'$in': c}}, {'$set': {'work': rep}})
    duplicates = mark_duplicate_groups(db, groups)
    db.reviews.create_index([('work', 1), ('is_copy', 1)])
    db.products.create_index([('work', 1)])

    # 4. Sản phẩm: tác phẩm, ấn bản đại diện, danh sách ấn bản, giá thấp nhất trong các ấn bản.
    db.products.update_many({}, [{'$set': {'work': '$asin', 'primary': True, 'work_size': 1, 'editions': [], 'price_any': '$price'}}])
    operations = []
    for rep, c in reps.items():
        editions = sorted(({'asin': a, 'title': info[a]['title'], 'formats': info[a].get('formats', []), 'price': info[a].get('price'),
                            'review_count': counts[a]} for a in c), key=lambda e: (e['asin'] != rep, e['price'] is None, e['price'] or 0, e['asin']))
        prices = [e['price'] for e in editions if e['price'] is not None]
        for a in c:
            update = {'work': rep, 'primary': a == rep, 'work_size': len(c)}
            if a == rep:
                update.update(editions=editions, price_any=min(prices) if prices else None)
            operations.append(UpdateOne({'_id': a}, {'$set': update}))
    for chunk in batches(operations, 2000):
        db.products.bulk_write(chunk, ordered=False)
    db.products.create_index([('primary', 1), ('stats.work_positive', -1)])
    db.reviews.create_index([('reviewerID', 1), ('is_copy', 1)])
    from .mongo import rebuild_work_stats, rebuild_user_stats
    rebuild_work_stats(db)
    rebuild_user_stats(db)

    # 5. Neo4j: tác phẩm và ấn bản đại diện trên Product, cờ bản sao trên REVIEWED, tên và thống kê User.
    graph.run(driver, 'CREATE INDEX product_work IF NOT EXISTS FOR (p:Product) ON (p.work)', config=config)
    push_work_properties(db, driver, config)
    with driver.session(database=config.neo4j_database) as session:
        session.run('MATCH ()-[r:REVIEWED]->() WHERE r.copy = true CALL (r) { SET r.copy = false } IN TRANSACTIONS OF 50000 ROWS').consume()
    for chunk in batches([rid for rid, _ in copies], 10000):
        graph.run(driver, 'UNWIND $ids AS id MATCH ()-[r:REVIEWED {review_id:id}]->() SET r.copy = true', {'ids': chunk}, config)
    for chunk in batches(db.users.find({}, {'reviewerID': 1, 'display_name': 1, 'username': 1, 'stats': 1, 'is_demo': 1}), 5000):
        graph.run(driver, graph.USERS, {'rows': [graph.user_row(u) for u in chunk]}, config)

    total = db.reviews.count_documents({'is_demo': False})
    copy_count = db.reviews.count_documents({'is_demo': False, 'is_copy': True})
    biggest = sorted(reps.items(), key=lambda kv: -sum(counts[a] for a in kv[1]))[:10]
    copied = {rid for rid, _ in copies}
    cross_work = sum(max(0, sum(r['id'] not in copied for r in rows) - 1) for rows in groups)
    report = {
        'rule': f'Hai mã là ấn bản của cùng tác phẩm khi chung >= {min_share:.0%} review của mã ít review hơn và >= {min_common} review; '
                'review trùng = cùng người, cùng ngày, cùng số sao, cùng tiêu đề và 200 ký tự đầu nội dung.',
        'duplicate_review_groups': len(groups), 'product_pairs_sharing_reviews': len(shared), 'pairs_linked': linked,
        'works_with_several_editions': len(clusters), 'products_in_those_works': sum(len(c) for c in clusters),
        'works_total': db.products.count_documents({'active': True, 'primary': True}),
        'review_rows': total, 'copy_rows': copy_count, 'unique_reviews': total - copy_count,
        'identical_rows_across_works': cross_work,
        'identical_rows_note': 'Dòng giống hệt một review khác của cùng người nhưng ở tác phẩm khác (chung < 80%, ví dụ các mùa của series): '
                               'giữ lại vì là hai tác phẩm khác nhau; đánh giá gợi ý không chia các dòng này giữa Train và Test (dup_group).',
        'duplicate_groups_marked': duplicates,
        'largest_works': [{'title': info[rep]['title'], 'editions': [{'asin': a, 'title': info[a]['title'], 'reviews': counts[a]} for a in c]} for rep, c in biggest],
        'seconds': round(time.time() - started, 2),
    }
    write_json(config.report_dir / 'buoi6_editions.json', report)
    return report
