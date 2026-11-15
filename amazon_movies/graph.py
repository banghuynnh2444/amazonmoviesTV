"""Thuận: mô hình 5 nhãn, nhập theo lô, 8 loại quan hệ và GDS."""
import hashlib, time
from neo4j import GraphDatabase
from pymongo import UpdateOne
from .config import settings
from .data import batches, write_json

SCHEMA = [
    'CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.reviewerID IS UNIQUE',
    'CREATE CONSTRAINT product_asin IF NOT EXISTS FOR (p:Product) REQUIRE p.asin IS UNIQUE',
    'CREATE CONSTRAINT category_key IF NOT EXISTS FOR (c:Category) REQUIRE c.key IS UNIQUE',
    'CREATE CONSTRAINT brand_name IF NOT EXISTS FOR (b:Brand) REQUIRE b.name IS UNIQUE',
    'CREATE CONSTRAINT format_name IF NOT EXISTS FOR (f:Format) REQUIRE f.name IS UNIQUE',
    'CREATE INDEX reviewed_id IF NOT EXISTS FOR ()-[r:REVIEWED]-() ON (r.review_id)',
    'CREATE INDEX product_rating IF NOT EXISTS FOR (p:Product) ON (p.avg_rating)',
    'CREATE INDEX product_work IF NOT EXISTS FOR (p:Product) ON (p.work)',
]
PRODUCTS = '''UNWIND $rows AS row
MERGE (p:Product {asin:row.asin}) SET p.title=row.title, p.avg_rating=row.avg_rating, p.review_count=row.review_count,
 p.sentiment_score=row.sentiment_score, p.price=row.price, p.work=row.work, p.primary=row.primary,
 p.work_reviews=row.work_reviews, p.work_avg=row.work_avg
FOREACH (c IN row.categories | MERGE (cat:Category {key:c.key}) SET cat.name=c.name, cat.path=c.path MERGE (p)-[:IN_CATEGORY]->(cat))
FOREACH (pair IN row.parents | MERGE (child:Category {key:pair.child}) MERGE (parent:Category {key:pair.parent}) MERGE (child)-[:SUBCATEGORY_OF]->(parent))
FOREACH (name IN CASE WHEN row.brand = '' THEN [] ELSE [row.brand] END | MERGE (b:Brand {name:name}) MERGE (p)-[:BY_BRAND]->(b))
FOREACH (name IN row.formats | MERGE (f:Format {name:name}) MERGE (p)-[:AVAILABLE_AS]->(f))'''
USERS = '''UNWIND $rows AS row MERGE (u:User {reviewerID:row.reviewerID})
SET u.name=row.name, u.avg_rating=row.avg_rating, u.review_count=row.review_count, u.is_demo=row.is_demo'''
REVIEWS = '''UNWIND $rows AS row
MERGE (u:User {reviewerID:row.reviewerID}) MERGE (p:Product {asin:row.asin})
MERGE (u)-[r:REVIEWED {review_id:row.review_id}]->(p)
SET r._sync_lock=true
FOREACH (_ IN CASE WHEN coalesce(r.version,0)<=row.version THEN [1] ELSE [] END |
 SET r.rating=row.rating,r.timestamp=row.timestamp,r.helpful=row.vote,r.verified=row.verified,
     r.sentiment=row.sentiment,r.version=row.version,r.is_demo=row.is_demo,r.copy=row.copy)
REMOVE r._sync_lock'''
LINKS = '''UNWIND $rows AS row MATCH (p:Product {asin:row.asin})
CALL (p,row) { UNWIND row.also_buy AS asin MATCH (q:Product {asin:asin}) MERGE (p)-[:ALSO_BOUGHT]->(q) }
CALL (p,row) { UNWIND row.also_view AS asin MATCH (q:Product {asin:asin}) MERGE (p)-[:ALSO_VIEWED]->(q) }'''

def connect(config=settings):
    if not config.neo4j_password: raise ValueError('Thiếu NEO4J_PASSWORD trong .env')
    driver=GraphDatabase.driver(config.neo4j_uri,auth=(config.neo4j_user,config.neo4j_password),connection_timeout=10)
    driver.verify_connectivity()
    return driver

def run(driver, query, params=None, config=settings):
    with driver.session(database=config.neo4j_database) as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, params or {})])

def initialize(driver, config=settings):
    for query in SCHEMA: run(driver,query,config=config)
    return run(driver,'RETURN gds.version() AS gds_version',config=config)[0]

def product_row(doc):
    categories, parents = {}, []
    for path in doc.get('category_paths',[]):
        previous=None
        for i,name in enumerate(path):
            prefix=path[:i+1]; key=hashlib.sha256('\x1f'.join(prefix).encode()).hexdigest()
            categories[key]={'key':key,'name':name,'path':prefix}
            if previous: parents.append({'child':key,'parent':previous})
            previous=key
    stats=doc.get('stats',{}); scores=stats.get('sentiment',{})
    available=sum(scores.get(k,0) for k in ['positive','negative','neutral'])
    return {'asin':doc['asin'],'title':doc['title'],'avg_rating':float(stats.get('avg_rating',0)),
            'review_count':int(stats.get('review_count',0)), 'sentiment_score':(scores.get('positive',0)-scores.get('negative',0))/available if available else 0.,
            'price':doc.get('price'),'brand':doc.get('brand',''),'formats':doc.get('formats',[]),'categories':list(categories.values()),'parents':parents,
            'work':doc.get('work') or doc['asin'],'primary':doc.get('primary',True) is not False,
            'work_reviews':int(stats.get('work_reviews',0)),'work_avg':float(stats.get('work_avg') or 0.)}

def user_row(doc):
    return {'reviewerID':doc['reviewerID'],'name':doc.get('display_name') or doc.get('username') or '','avg_rating':float(doc.get('stats',{}).get('avg_rating',0)),
            'review_count':int(doc.get('stats',{}).get('review_count',0)),'is_demo':bool(doc.get('is_demo'))}

def review_row(doc):
    return {'review_id':doc['review_id'],'reviewerID':doc['reviewerID'],'asin':doc['asin'],'rating':float(doc['overall']),
            'timestamp':int(doc['timestamp']),'vote':int(doc.get('vote',0)),'verified':bool(doc.get('verified')),
            'sentiment':doc.get('sentiment',{}).get('compound'),'version':int(doc.get('version',1)),'is_demo':bool(doc.get('is_demo')),
            'copy':bool(doc.get('is_copy'))}

def acknowledge(db, docs):
    operations=[UpdateOne({'_id':d['_id'],'version':d['version']},{'$set':{'synced':True,'synced_version':d['version']},'$unset':{'sync_error':''}}) for d in docs]
    if operations: db.reviews.bulk_write(operations,ordered=False)

def import_graph(db, driver, config=settings, batch_size=2000):
    started=time.time(); counts={}
    initialize(driver,config)
    for collection, query, convert, predicate in [('products',PRODUCTS,product_row,{'active':True}),('users',USERS,user_row,{})]:
        count=0
        for docs in batches(db[collection].find(predicate),batch_size):
            run(driver,query,{'rows':[convert(d) for d in docs]},config); count+=len(docs)
        counts[collection]=count
    count=0
    for docs in batches(db.products.find({'active':True},{'asin':1,'also_buy':1,'also_view':1}),500):
        run(driver,LINKS,{'rows':[{'asin':d['asin'],'also_buy':[v for v in d.get('also_buy',[]) if v != d['asin']],'also_view':[v for v in d.get('also_view',[]) if v != d['asin']]} for d in docs]},config)
    cursor=db.reviews.find({},no_cursor_timeout=True)
    try:
        for docs in batches(cursor,batch_size):
            run(driver,REVIEWS,{'rows':[review_row(d) for d in docs]},config)
            acknowledge(db,docs); count+=len(docs)
            if count % 20000==0: print('NEO4J REVIEWED',count,'seconds',round(time.time()-started,1),flush=True)
    finally: cursor.close()
    counts['reviews']=count; counts['seconds']=round(time.time()-started,2)
    write_json(config.report_dir/'buoi2_neo4j_import.json',counts)
    return counts

def sync_pending(db, driver, config=settings, limit=0, batch_size=500):
    count=0
    for users in batches(db.users.find({'synced':False}),batch_size):
        run(driver,USERS,{'rows':[user_row(u) for u in users]},config)
        db.users.update_many({'_id':{'$in':[u['_id'] for u in users]}},{'$set':{'synced':True}})
    cursor=db.reviews.find({'synced':False}).sort('_id',1)
    if limit: cursor=cursor.limit(limit)
    for docs in batches(cursor,batch_size):
        try:
            # Rebuild current endpoint snapshots first; this also creates new demo users.
            # Gồm cả ấn bản đại diện của tác phẩm: thống kê tác phẩm được ghi trên nút đó.
            asins={r['asin'] for r in docs}|{r.get('work') or r['asin'] for r in docs}; users={r['reviewerID'] for r in docs}
            run(driver,PRODUCTS,{'rows':[product_row(p) for p in db.products.find({'asin':{'$in':list(asins)}})]},config)
            run(driver,USERS,{'rows':[user_row(u) for u in db.users.find({'reviewerID':{'$in':list(users)}})]},config)
            run(driver,REVIEWS,{'rows':[review_row(d) for d in docs]},config)
            acknowledge(db,docs); count+=len(docs)
        except Exception as exc:
            db.reviews.update_many({'_id':{'$in':[d['_id'] for d in docs]}},{'$set':{'sync_error':type(exc).__name__}})
            raise
    return {'synced':count,'remaining':db.reviews.count_documents({'synced':False})}

def verify(db, driver, config=settings, exhaustive=False):
    mongo={'Product':db.products.count_documents({'active':True}),'User':db.users.count_documents({}),'REVIEWED':db.reviews.count_documents({})}
    graph={row['label']:row['count'] for row in run(driver,'MATCH (n) UNWIND labels(n) AS label RETURN label,count(*) AS count',config=config)}
    rels={row['type']:row['count'] for row in run(driver,'MATCH ()-[r]->() RETURN type(r) AS type,count(*) AS count',config=config)}
    checks={label:mongo[label]==(rels.get(label,0) if label=='REVIEWED' else graph.get(label,0)) for label in mongo}
    duplicates=run(driver,'MATCH ()-[r:REVIEWED]->() WITH r.review_id AS id,count(*) AS n WHERE n>1 RETURN count(*) AS duplicates',config=config)[0]['duplicates']
    checks['no_duplicate_review_ids']=duplicates==0
    checks['all_reviews_synced']=db.reviews.count_documents({'synced':False})==0
    if exhaustive:
        # Every review is checked in bounded batches; counts alone would miss substituted IDs.
        missing=0
        for docs in batches(db.reviews.find({}, {'_id':1}),2000):
            found=run(driver,'UNWIND $ids AS id MATCH ()-[r:REVIEWED]->() WHERE r.review_id=id RETURN count(r) AS n',{'ids':[d['_id'] for d in docs]},config)[0]['n']
            missing+=len(docs)-found
        checks['all_review_keys_present']=missing==0
    result={'mongo':mongo,'neo4j_nodes':graph,'neo4j_relationships':rels,'checks':checks,'ok':all(checks.values())}
    write_json(config.report_dir/'buoi2_reconciliation.json',result)
    return result

def gds_similarity(driver, config=settings, top_k=20, min_reviews=5, degree_cutoff=3, memory_limit_gib=4.):
    """GDS Node Similarity (Jaccard) trên đồ thị User–Product chỉ gồm cạnh thích (>= 4 sao) → ghi SIMILAR_TO.

    Chỉ chiếu người dùng có >= min_reviews review để giới hạn chi phí all-pairs; người dùng còn lại
    được website tính láng giềng trực tiếp bằng Cypher khi cần.
    """
    name='movies_positive_users'
    def drop():
        if run(driver,'CALL gds.graph.exists($name) YIELD exists RETURN exists',{'name':name},config)[0]['exists']:
            run(driver,'CALL gds.graph.drop($name) YIELD graphName RETURN graphName',{'name':name},config)
    drop()
    started=time.time()
    total_users=run(driver,'MATCH (u:User) RETURN count(u) AS n',config=config)[0]['n']
    node_query='MATCH (n) WHERE (n:User AND coalesce(n.review_count,0)>=$min_reviews) OR n:Product RETURN id(n) AS id'
    # Cạnh thích theo tác phẩm: bỏ review bản sao, mọi ấn bản quy về ấn bản đại diện.
    rel_query=('MATCH (u:User)-[r:REVIEWED]->(p:Product) WHERE coalesce(u.review_count,0)>=$min_reviews AND NOT coalesce(r.copy,false) '
               'WITH u,coalesce(p.work,p.asin) AS w,avg(r.rating) AS rating WHERE rating>=4 '
               'MATCH (q:Product {asin:w}) RETURN id(u) AS source,id(q) AS target')
    projected=run(driver,'CALL gds.graph.project.cypher($name,$node_query,$rel_query,{parameters:{min_reviews:$min_reviews}}) '
                  'YIELD nodeCount,relationshipCount RETURN nodeCount,relationshipCount',
                  {'name':name,'node_query':node_query,'rel_query':rel_query,'min_reviews':min_reviews},config)[0]
    options={'writeRelationshipType':'SIMILAR_TO','writeProperty':'score','topK':top_k,'degreeCutoff':degree_cutoff,'similarityCutoff':0.05}
    try:
        estimate=run(driver,'CALL gds.nodeSimilarity.write.estimate($name,$options) YIELD bytesMin,bytesMax RETURN bytesMin,bytesMax',{'name':name,'options':options},config)[0]
        if estimate['bytesMax'] > memory_limit_gib*1024**3:
            return {'status':'memory_estimate_exceeds_limit','estimate':estimate,'limit_gib':memory_limit_gib}
        with driver.session(database=config.neo4j_database) as session:
            session.run('MATCH ()-[r:SIMILAR_TO]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 50000 ROWS').consume()
        result=run(driver,'CALL gds.nodeSimilarity.write($name,$options) YIELD nodesCompared,relationshipsWritten RETURN nodesCompared,relationshipsWritten',
                   {'name':name,'options':options},config)[0]
        covered=run(driver,'MATCH (u:User) WHERE EXISTS { (u)-[:SIMILAR_TO]-() } RETURN count(u) AS n',config=config)[0]['n']
        report={'total_users':total_users,'min_reviews_filter':min_reviews,'degreeCutoff':degree_cutoff,'topK':top_k,
                'similarityCutoff':options['similarityCutoff'],'projected':projected,'estimate':estimate,**result,
                'users_with_similar_to':covered,'coverage':round(covered/total_users,4) if total_users else 0.,
                'seconds':round(time.time()-started,2)}
        write_json(config.report_dir/'buoi3_gds_similarity.json',report)
        return report
    finally:
        drop()

GENERIC_NAMES = {'amazon customer', 'kindle customer', 'a customer', 'customer'}

def user_label(name, reviewer_id, width=18):
    """Nhãn hiển thị: tên công khai trên Amazon; tên chung chung hoặc trống thì kèm 6 ký tự cuối mã để phân biệt."""
    name = (name or '').strip()
    if not name or name.lower() in GENERIC_NAMES:
        return f"{name or 'Người dùng'} ·{reviewer_id[-6:]}"
    return name if len(name) <= width else name[:width - 1] + '…'

def ego_graph(driver, asin=None, user=None, limit=25, config=settings):
    """Trích xuất đồ thị con xung quanh một Product (asin) hoặc một User (reviewerID) để hiển thị trên vis-network."""
    nodes = {}
    edges = []
    seen_edges = set()

    def add_node(nid, label, group, **props):
        if nid not in nodes:
            nodes[nid] = {'id': nid, 'label': label, 'group': group, **props}

    def add_edge(src, dst, rel_type, **props):
        key = (src, dst, rel_type)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({'from': src, 'to': dst, 'label': rel_type, **props})

    if asin:
        prod_rows = run(
            driver,
            '''MATCH (p:Product {asin:$asin})
            RETURN p.asin AS asin, p.title AS title, p.avg_rating AS avg_rating,
                   p.review_count AS review_count, coalesce(p.pagerank, 0.0) AS pagerank,
                   coalesce(p.community, -1) AS community, p.price AS price''',
            {'asin': asin},
            config,
        )
        if not prod_rows:
            return {'center': {'type': 'Product', 'id': asin}, 'nodes': [], 'edges': []}
        p = prod_rows[0]
        center_id = f"P:{p['asin']}"
        short_title = (p['title'][:32] + '…') if len(p['title']) > 32 else p['title']
        add_node(center_id, short_title, 'CenterProduct', full_title=p['title'], asin=p['asin'],
                 avg_rating=p['avg_rating'], review_count=p['review_count'], pagerank=p['pagerank'], community=p['community'])

        # Danh mục, Thương hiệu, Định dạng
        attr_rows = run(
            driver,
            '''MATCH (p:Product {asin:$asin})
            OPTIONAL MATCH (p)-[:BY_BRAND]->(b:Brand)
            OPTIONAL MATCH (p)-[:AVAILABLE_AS]->(f:Format)
            OPTIONAL MATCH (p)-[:IN_CATEGORY]->(c:Category)
            RETURN collect(DISTINCT b.name) AS brands,
                   collect(DISTINCT f.name) AS formats,
                   collect(DISTINCT {key: c.key, name: c.name, depth: size(c.path)}) AS categories''',
            {'asin': asin},
            config,
        )[0]
        for bname in attr_rows.get('brands', []):
            if bname:
                bid = f'B:{bname}'
                add_node(bid, bname[:24], 'Brand', full_title=bname)
                add_edge(center_id, bid, 'BY_BRAND')
        for fname in attr_rows.get('formats', [])[:6]:
            if fname:
                fid = f'F:{fname}'
                add_node(fid, fname, 'Format', full_title=fname)
                add_edge(center_id, fid, 'AVAILABLE_AS')
        for cat in sorted(attr_rows.get('categories', []), key=lambda x: x.get('depth') or 0)[-5:]:
            if cat and cat.get('key'):
                cid = f"C:{cat['key'][:12]}"
                add_node(cid, cat['name'][:24], 'Category', full_title=cat['name'], depth=cat.get('depth'))
                add_edge(center_id, cid, 'IN_CATEGORY')

        # Phim mua cùng / xem cùng
        rel_rows = run(
            driver,
            '''MATCH (p:Product {asin:$asin})-[r:ALSO_BOUGHT|ALSO_VIEWED]->(q:Product)
            RETURN q.asin AS asin, q.title AS title, q.avg_rating AS avg_rating,
                   coalesce(q.pagerank, 0.0) AS pagerank, type(r) AS rel_type
            ORDER BY q.pagerank DESC, q.review_count DESC LIMIT $limit''',
            {'asin': asin, 'limit': min(15, limit)},
            config,
        )
        for r in rel_rows:
            qid = f"P:{r['asin']}"
            q_short = (r['title'][:26] + '…') if len(r['title']) > 26 else r['title']
            add_node(qid, q_short, 'Product', full_title=r['title'], asin=r['asin'], avg_rating=r['avg_rating'], pagerank=r['pagerank'])
            add_edge(center_id, qid, r['rel_type'])

        # Người dùng đánh giá tiêu biểu
        rev_rows = run(
            driver,
            '''MATCH (u:User)-[r:REVIEWED]->(p:Product {asin:$asin})
            RETURN u.reviewerID AS user, coalesce(u.name,'') AS name, u.review_count AS review_count,
                   r.rating AS rating, r.helpful AS helpful, r.sentiment AS sentiment
            ORDER BY r.helpful DESC, r.timestamp DESC, u.reviewerID LIMIT 10''',
            {'asin': asin},
            config,
        )
        for r in rev_rows:
            uid = f"U:{r['user']}"
            add_node(uid, user_label(r['name'], r['user']), 'User', reviewerID=r['user'], name=r['name'], review_count=r['review_count'])
            add_edge(uid, center_id, 'REVIEWED', rating=r['rating'], sentiment=r['sentiment'])

        return {
            'center': {'type': 'Product', 'id': asin, 'title': p['title']},
            'nodes': list(nodes.values()),
            'edges': edges,
        }

    if user:
        u_rows = run(
            driver,
            'MATCH (u:User {reviewerID:$user}) RETURN u.reviewerID AS user, coalesce(u.name,\'\') AS name, u.avg_rating AS avg_rating, u.review_count AS review_count, u.is_demo AS is_demo',
            {'user': user},
            config,
        )
        if not u_rows:
            return {'center': {'type': 'User', 'id': user}, 'nodes': [], 'edges': []}
        u = u_rows[0]
        center_id = f"U:{u['user']}"
        add_node(center_id, user_label(u['name'], u['user'], 40), 'CenterUser', reviewerID=u['user'], name=u['name'],
                 avg_rating=u['avg_rating'], review_count=u['review_count'])

        # Các phim người dùng đã đánh giá (bỏ bản sao của cùng review ở ấn bản khác)
        liked_rows = run(
            driver,
            '''MATCH (u:User {reviewerID:$user})-[r:REVIEWED]->(p:Product) WHERE NOT coalesce(r.copy,false)
            RETURN p.asin AS asin, p.title AS title, p.avg_rating AS avg_rating,
                   r.rating AS rating, r.timestamp AS ts
            ORDER BY r.rating DESC, r.timestamp DESC, p.asin LIMIT $limit''',
            {'user': user, 'limit': min(15, limit)},
            config,
        )
        for r in liked_rows:
            pid = f"P:{r['asin']}"
            p_short = (r['title'][:26] + '…') if len(r['title']) > 26 else r['title']
            add_node(pid, p_short, 'Product', full_title=r['title'], asin=r['asin'], avg_rating=r['avg_rating'])
            add_edge(center_id, pid, 'REVIEWED', rating=r['rating'])

        # Người dùng tương đồng (SIMILAR_TO hoặc cùng thích chung phim)
        sim_rows = run(
            driver,
            '''MATCH (u:User {reviewerID:$user})-[s:SIMILAR_TO]-(other:User)
            RETURN other.reviewerID AS other_user, coalesce(other.name,'') AS name, max(s.score) AS score
            ORDER BY score DESC, other_user LIMIT 8''',
            {'user': user},
            config,
        )
        for r in sim_rows:
            oid = f"U:{r['other_user']}"
            add_node(oid, user_label(r['name'], r['other_user']), 'User', reviewerID=r['other_user'], name=r['name'])
            add_edge(center_id, oid, 'SIMILAR_TO', score=round(float(r['score']), 3))

        # Người dùng cùng đánh giá cao các phim đã xem và phim gợi ý liên kết
        co_rows = run(
            driver,
            '''MATCH (u:User {reviewerID:$user})-[r1:REVIEWED]->(p:Product)<-[r2:REVIEWED]-(other:User)
            WHERE r1.rating >= 4 AND r2.rating >= 4 AND other <> u
              AND NOT coalesce(r1.copy,false) AND NOT coalesce(r2.copy,false)
            WITH other, collect(DISTINCT p)[0..3] AS shared_prods, count(DISTINCT coalesce(p.work,p.asin)) AS common
            WHERE common >= 2
            ORDER BY common DESC, other.reviewerID ASC LIMIT 6
            UNWIND shared_prods AS sp
            RETURN other.reviewerID AS other_user, coalesce(other.name,'') AS name, sp.asin AS asin, sp.title AS title, common''',
            {'user': user},
            config,
        )
        for r in co_rows:
            oid = f"U:{r['other_user']}"
            pid = f"P:{r['asin']}"
            p_short = (r['title'][:26] + '…') if len(r['title']) > 26 else r['title']
            add_node(oid, user_label(r['name'], r['other_user']), 'User', reviewerID=r['other_user'], name=r['name'], common=r['common'])
            add_node(pid, p_short, 'Product', full_title=r['title'], asin=r['asin'])
            add_edge(oid, pid, 'REVIEWED')

        return {
            'center': {'type': 'User', 'id': user},
            'nodes': list(nodes.values()),
            'edges': edges,
        }

    return {'nodes': [], 'edges': []}
