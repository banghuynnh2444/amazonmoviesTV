"""Bằng: schema, ETL, text search, computed/subset patterns và thống kê."""
from datetime import datetime, timezone
import time
from pymongo import MongoClient, UpdateOne, ASCENDING, DESCENDING, TEXT
from .config import settings
from .data import rows, batches, product, review, sentiment, write_json, normalize_review_batch

SENTIMENT_LABELS=['positive','neutral','negative','unavailable','unsupported_language','pending']

def connect(config=settings):
    client = MongoClient(config.mongo_uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    client.admin.command('ping')
    return client, client[config.mongo_database]

def initialize(db):
    schemas = {
        'products': {'bsonType':'object','required':['asin','title'], 'properties':{'asin':{'bsonType':'string'},'title':{'bsonType':'string'},'price':{'bsonType':['double','int','null']}}},
        'reviews': {'bsonType':'object','required':['review_id','reviewerID','asin','overall','timestamp','version'], 'properties':{'overall':{'bsonType':['double','int'],'minimum':1,'maximum':5},'timestamp':{'bsonType':['int','long']},'reviewText':{'bsonType':'string'},'synced':{'bsonType':'bool'}}},
        'users': {'bsonType':'object','required':['reviewerID'], 'properties':{'reviewerID':{'bsonType':'string'},'password_hash':{'bsonType':'string'}}},
    }
    for name, schema in schemas.items():
        if name not in db.list_collection_names(): db.create_collection(name, validator={'$jsonSchema':schema})
        else: db.command('collMod',name,validator={'$jsonSchema':schema},validationLevel='strict')
    db.products.create_index('asin',unique=True)
    db.products.create_index([('title',TEXT),('description',TEXT)],name='product_fulltext',default_language='english',weights={'title':5,'description':1})
    db.products.create_index([('categories',ASCENDING),('price',ASCENDING)])
    db.products.create_index([('stats.review_count',DESCENDING)])
    db.reviews.create_index('review_id',unique=True)
    db.reviews.create_index([('timestamp',DESCENDING),('_id',ASCENDING)],name='review_recent_global')
    db.reviews.create_index([('asin',ASCENDING),('timestamp',DESCENDING)])
    db.reviews.create_index([('reviewerID',ASCENDING),('timestamp',DESCENDING)])
    db.reviews.create_index([('asin',ASCENDING),('vote',DESCENDING)])
    db.reviews.create_index([('reviewText',TEXT),('summary',TEXT)],name='review_fulltext',default_language='english')
    db.reviews.create_index([('synced',ASCENDING),('_id',ASCENDING)])
    # Index một phần: đếm nhanh bản sao, review viết trên web và review đồng bộ lỗi (trang quản trị) mà không quét 3,3 triệu document.
    db.reviews.create_index([('is_copy',ASCENDING)],name='copy_rows',partialFilterExpression={'is_copy':True})
    db.reviews.create_index([('is_demo',ASCENDING)],name='demo_rows',partialFilterExpression={'is_demo':True})
    db.reviews.create_index([('sync_error',ASCENDING)],name='sync_error_rows',partialFilterExpression={'sync_error':{'$exists':True}})
    db.users.create_index('reviewerID',unique=True)
    db.users.create_index('username',unique=True,partialFilterExpression={'is_demo':True})
    db.helpful_votes.create_index([('review_id',ASCENDING),('reviewerID',ASCENDING)],unique=True)
    return {'collections':db.list_collection_names(),'indexes':{n:list(db[n].index_information()) for n in schemas}}

def import_data(db, config=settings, limit=0, batch_size=2000, with_sentiment=True, workers=1):
    started=time.time()
    if limit and db.reviews.count_documents({'source':'amazon_2018'})>limit:
        raise ValueError('CSDL hiện có nhiều review hơn giới hạn chạy thử. Dùng MONGO_DATABASE riêng cho tập thử.')
    db.reviews.update_many({'source_vote':{'$exists':False}},[{'$set':{'source_vote':'$vote','demo_vote_count':0}}])
    report={'review_limit':limit or None,'sentiment_in_import':with_sentiment,'metadata_raw_rows':0,'metadata_valid_rows':0,
            'review_raw_rows':0,'review_invalid':0,'review_without_metadata':0,'review_valid_source_rows':0}
    # Index construction after the bulk load is substantially cheaper than per-row text-index maintenance.
    for name in ['products','reviews']:
        for index_name in list(db[name].index_information()):
            if index_name not in ['_id_','asin_1','review_id_1']:
                db[name].drop_index(index_name)
    db.jobs.update_one({'_id':'etl'},{'$set':{'status':'running','started_at':datetime.now(timezone.utc),'limit':limit}},upsert=True)
    for group in batches(rows(config.raw('meta_Movies_and_TV.json.gz')),batch_size):
        operations=[]
        for _, raw in group:
            report['metadata_raw_rows']+=1
            doc=product(raw)
            if doc:
                report['metadata_valid_rows']+=1
                operations.append(UpdateOne({'_id':doc['_id']},{'$set':doc},upsert=True))
        if operations: db.products.bulk_write(operations,ordered=False)
        if report['metadata_raw_rows'] % 20000==0: print('MONGO metadata',report['metadata_raw_rows'],flush=True)
    available={p['_id'] for p in db.products.find({}, {'_id':1})}
    def eligible_groups():
        for group in batches(rows(config.raw('Movies_and_TV_5.json.gz'),limit),batch_size):
            report['review_raw_rows']+=len(group)
            eligible=[pair for pair in group if pair[1].get('asin') in available]
            report['review_without_metadata']+=len(group)-len(eligible)
            yield eligible
    def normalized_groups():
        if workers<=1:
            for group in eligible_groups(): yield normalize_review_batch(group,with_sentiment)
        else:
            from concurrent.futures import ProcessPoolExecutor
            from collections import deque
            with ProcessPoolExecutor(max_workers=workers) as pool:
                pending=deque()
                for group in eligible_groups():
                    pending.append(pool.submit(normalize_review_batch,group,with_sentiment))
                    if len(pending)>=workers*2: yield pending.popleft().result()
                while pending: yield pending.popleft().result()
    for docs, invalid in normalized_groups():
        operations=[]
        report['review_invalid']+=invalid
        for doc in docs:
            report['review_valid_source_rows']+=1
            operations.append(UpdateOne({'_id':doc['_id']},{'$setOnInsert':doc},upsert=True))
        if operations: db.reviews.bulk_write(operations,ordered=False)
        if report['review_raw_rows'] % 20000 == 0:
            print(f"MONGO reviews={report['review_raw_rows']:,}; elapsed={time.time()-started:.1f}s",flush=True)
            write_json(config.report_dir/'buoi2_import_progress.json',{**report,'elapsed_seconds':time.time()-started})
    rebuild_stats(db)
    # This application owns this database; remove unreferenced imported metadata only.
    report['unused_metadata_removed']=db.products.delete_many({'source':'amazon_2018','active':False}).deleted_count
    report['products']=db.products.count_documents({})
    report['reviews']=db.reviews.count_documents({'source':'amazon_2018'})
    report['users']=db.users.count_documents({'is_demo':False})
    report['exact_duplicate_source_rows']=report['review_valid_source_rows']-report['reviews']
    print('MONGO building search/history indexes',flush=True)
    initialize(db)
    report['seconds']=round(time.time()-started,2)
    db.jobs.update_one({'_id':'etl'},{'$set':{'status':'complete','completed_at':datetime.now(timezone.utc),'report':report}})
    write_json(config.report_dir/'buoi2_mongodb_import.json',report)
    return report

def rebuild_stats(db, asin=None, reviewer_id=None):
    product_match={'asin':asin} if asin else {}
    group={'_id':'$asin','review_count':{'$sum':1},'avg_rating':{'$avg':'$overall'},
           'all_formats':{'$addToSet':'$formats'},
           'top_reviews':{'$topN':{'n':5,'sortBy':{'vote':-1,'timestamp':-1,'_id':1},'output':{'review_id':'$review_id','summary':'$summary','excerpt':{'$substrCP':['$reviewText',0,250]},'overall':'$overall','vote':'$vote'}}}}
    for star in range(1,6): group[f'star_{star}']={'$sum':{'$cond':[{'$eq':['$overall',star]},1,0]}}
    for label in SENTIMENT_LABELS:
        group[label]={'$sum':{'$cond':[{'$eq':['$sentiment.label',label]},1,0]}}
    pipeline=[{'$match':product_match},{'$group':group},{'$project':{'asin':'$_id','active':{'$literal':True},'formats':{'$reduce':{'input':'$all_formats','initialValue':[],'in':{'$setUnion':['$$value','$$this']}}},
        'stats':{'review_count':'$review_count','avg_rating':'$avg_rating','stars':{str(i):f'$star_{i}' for i in range(1,6)},'sentiment':{k:f'${k}' for k in SENTIMENT_LABELS}},'top_reviews':1}},
        # Gộp vào stats hiện có: giữ pagerank/community do GDS ghi, chỉ thay các trường thống kê review.
        {'$merge':{'into':'products','on':'_id','whenNotMatched':'discard','whenMatched':[{'$set':{
            'active':'$$new.active','formats':'$$new.formats','top_reviews':'$$new.top_reviews',
            'stats':{'$mergeObjects':[{'$ifNull':['$stats',{}]},'$$new.stats']}}}]}}]
    list(db.reviews.aggregate(pipeline,allowDiskUse=True))
    if asin and not db.reviews.find_one({'asin':asin},{'_id':1}):
        # Review cuối cùng vừa bị xóa: $group không sinh dòng nào nên phải tự đưa thống kê về 0.
        db.products.update_one({'asin':asin},{'$set':{'stats.review_count':0,'stats.avg_rating':0.,'top_reviews':[],
            'stats.stars':{str(i):0 for i in range(1,6)},'stats.sentiment':{k:0 for k in SENTIMENT_LABELS}}})
    if asin:
        product=db.products.find_one({'asin':asin},{'work':1})
        rebuild_work_stats(db,(product or {}).get('work') or asin)
    else:
        rebuild_work_stats(db)
    rebuild_user_stats(db,reviewer_id)

def rebuild_work_stats(db, work=None):
    """Thống kê theo tác phẩm (gộp mọi ấn bản, bỏ review bản sao), ghi vào ấn bản đại diện."""
    match={'is_copy':{'$ne':True}}
    if work:
        match['$or']=[{'work':work},{'asin':work}]
        if not db.reviews.find_one(match,{'_id':1}):
            db.products.update_one({'asin':work},{'$set':{'stats.work_reviews':0,'stats.work_positive':0,'stats.work_avg':0.,
                'stats.work_stars':{str(i):0 for i in range(1,6)},'stats.work_sentiment':{}}})
            return
    list(db.reviews.aggregate([{'$match':match},
        {'$group':{'_id':{'$ifNull':['$work','$asin']},'n':{'$sum':1},'positive':{'$sum':{'$cond':[{'$gte':['$overall',4]},1,0]}},'avg':{'$avg':'$overall'},
                   **{f's_{k}':{'$sum':{'$cond':[{'$eq':['$sentiment.label',k]},1,0]}} for k in ['positive','neutral','negative','unavailable','unsupported_language']},
                   **{f'star_{i}':{'$sum':{'$cond':[{'$eq':['$overall',i]},1,0]}} for i in range(1,6)}}},
        {'$project':{'stats':{'work_reviews':'$n','work_positive':'$positive','work_avg':'$avg',
                              'work_stars':{str(i):f'$star_{i}' for i in range(1,6)},
                              'work_sentiment':{k:f'$s_{k}' for k in ['positive','neutral','negative','unavailable','unsupported_language']}}}},
        {'$merge':{'into':'products','on':'_id','whenNotMatched':'discard','whenMatched':[{'$set':{
            'stats':{'$mergeObjects':[{'$ifNull':['$stats',{}]},'$$new.stats']}}}]}}],allowDiskUse=True))

def rebuild_user_stats(db, reviewer_id=None):
    """Số review và điểm TB của người dùng, không đếm review bản sao ở ấn bản khác."""
    match={'is_copy':{'$ne':True}}
    if reviewer_id:
        match['reviewerID']=reviewer_id
        if not db.reviews.find_one(match,{'_id':1}):
            db.users.update_one({'reviewerID':reviewer_id},{'$set':{'stats.review_count':0,'stats.avg_rating':0.}})
            return
    # Preserve demo password hashes and usernames by merging calculated fields only.
    list(db.reviews.aggregate([{'$match':match},
         {'$group':{'_id':'$reviewerID','review_count':{'$sum':1},'avg_rating':{'$avg':'$overall'},'display_name':{'$last':'$reviewerName'},'is_demo':{'$max':'$is_demo'}}},
         {'$project':{'reviewerID':'$_id','display_name':1,'is_demo':1,'stats':{'review_count':'$review_count','avg_rating':'$avg_rating'}}},
         {'$merge':{'into':'users','on':'_id','whenNotMatched':'insert','whenMatched':[{'$set':{
             'reviewerID':'$$new.reviewerID','is_demo':'$$new.is_demo',
             'display_name':{'$ifNull':['$display_name','$$new.display_name']},
             'stats':{'$mergeObjects':[{'$ifNull':['$stats',{}]},'$$new.stats']}}}]}}],allowDiskUse=True))

def sentiment_backfill(db, limit=0, batch_size=500):
    cursor=db.reviews.find({'sentiment.label':'pending'},no_cursor_timeout=True)
    if limit: cursor=cursor.limit(limit)
    processed=0; started=time.time()
    try:
        for group in batches(cursor,batch_size):
            operations=[UpdateOne({'_id':r['_id']},{'$set':{'sentiment':sentiment(r['reviewText']),'synced':False},'$inc':{'version':1}}) for r in group]
            db.reviews.bulk_write(operations,ordered=False); processed+=len(group)
            if processed % 10000==0: print('SENTIMENT',processed,round(time.time()-started,1),flush=True)
    finally: cursor.close()
    rebuild_stats(db)
    return {'processed':processed,'seconds':round(time.time()-started,2)}

def public(doc):
    if not doc: return doc
    result={k:v for k,v in doc.items() if k not in ['_id','password_hash','sync_error','synced_version']}
    return result

LIST_PROJECTION={'description':0,'also_buy':0,'also_view':0,'feature':0,'top_reviews':0,'images':0}
SORTS={'reviews':[('stats.work_reviews',-1),('_id',1)],'rating':[('stats.work_avg',-1),('stats.work_reviews',-1),('_id',1)],
       'pagerank':[('stats.pagerank',-1),('_id',1)],'price_asc':[('price_any',1),('_id',1)],'price_desc':[('price_any',-1),('_id',1)]}
# Nút điều hướng của Amazon, không phải thể loại: không đưa vào bộ lọc cho người dùng.
NAVIGATION_CATEGORIES={'Movies & TV','Genre for Featured Categories','Featured Categories','Studio Specials','All Titles','All',
                       'Fully Loaded DVDs','Characters & Series','Widescreen','Blu-ray','Boxed Sets'}

GENRE_ROOTS={'Science Fiction & Fantasy','Musicals & Performing Arts','Art House & International','Classics','Holidays & Seasonal'}

def search_products(db, q='', category=None, format_name=None, min_price=None, max_price=None, page=1, limit=20, sort=None):
    """Mỗi tác phẩm hiện một lần (ấn bản đại diện); giá lọc theo ấn bản rẻ nhất có giá."""
    match={'active':True,'primary':{'$ne':False}}
    if q: match['$text']={'$search':q}
    if category: match['categories']=category
    if format_name: match['formats']=format_name
    if min_price is not None or max_price is not None or sort in ('price_asc','price_desc'):
        match['price_any']={'$ne':None}
        if min_price is not None: match['price_any']['$gte']=min_price
        if max_price is not None: match['price_any']['$lte']=max_price
    projection=dict(LIST_PROJECTION)
    if q: projection['score']={'$meta':'textScore'}
    if sort not in SORTS: sort='relevance' if q else 'reviews'
    order=[('score',{'$meta':'textScore'}),('stats.work_reviews',-1)] if sort=='relevance' else SORTS[sort]
    cursor=db.products.find(match,projection).sort(order)
    items=[public(d) for d in cursor.skip((page-1)*limit).limit(limit)]
    return {'items':items,'page':page,'limit':limit,'sort':sort,'total':db.products.count_documents(match)}

def facets(db):
    """Thể loại và định dạng lấy trực tiếp từ dữ liệu (ấn bản đại diện), kèm số phim; bỏ nút điều hướng."""
    base={'active':True,'primary':{'$ne':False}}
    categories=list(db.products.aggregate([{'$match':base},{'$unwind':'$categories'},
        {'$group':{'_id':'$categories','count':{'$sum':1}}},{'$match':{'count':{'$gte':30},'_id':{'$nin':sorted(NAVIGATION_CATEGORIES)}}},{'$sort':{'count':-1,'_id':1}}]))
    formats=list(db.products.aggregate([{'$match':base},{'$unwind':'$formats'},
        {'$group':{'_id':'$formats','count':{'$sum':1}}},{'$match':{'count':{'$gte':10}}},{'$sort':{'count':-1,'_id':1}}]))
    prices=list(db.products.aggregate([{'$match':{**base,'price_any':{'$ne':None}}},
        {'$group':{'_id':None,'min':{'$min':'$price_any'},'max':{'$max':'$price_any'},'count':{'$sum':1}}}]))
    # Thể loại cho người dùng: con của "Genre for Featured Categories" và vài nhánh thể loại cấp 1;
    # bỏ nhánh hãng phim (Studio Specials, Warner Home Video…) và nhánh định dạng (Blu-ray, Boxed Sets…).
    second={'$arrayElemAt':['$category_paths',1]}
    genre_names={g['_id'] for g in db.products.aggregate([{'$match':base},{'$unwind':'$category_paths'},
        {'$project':{'g':{'$cond':[{'$eq':[second,'Genre for Featured Categories']},{'$arrayElemAt':['$category_paths',2]},
                                   {'$cond':[{'$in':[second,sorted(GENRE_ROOTS)]},second,None]}]}}},
        {'$match':{'g':{'$ne':None}}},{'$group':{'_id':'$g'}}])}
    return {'categories':[{'name':c['_id'],'count':c['count']} for c in categories],
            'genres':[{'name':c['_id'],'count':c['count']} for c in categories if c['_id'] in genre_names],
            'formats':[{'name':f['_id'],'count':f['count']} for f in formats],
            'price':{k:prices[0][k] for k in ['min','max','count']} if prices else None,
            'works':db.products.count_documents(base)}

def counts(db):
    """Số liệu tổng: dòng review lưu trữ, review khác nhau (bỏ bản sao), phim theo ấn bản và theo tác phẩm."""
    rows=db.reviews.estimated_document_count()
    copies=db.reviews.count_documents({'is_copy':True})
    return {'products':db.products.count_documents({'active':True}),'works':db.products.count_documents({'active':True,'primary':{'$ne':False}}),
            'reviews':rows-copies,'review_rows':rows,'copy_rows':copies,'users':db.users.estimated_document_count()}

def dashboard(db, config=settings, refresh=False):
    import json
    cache_path=config.report_dir/'dashboard_cache.json'
    is_main=(db.name==config.mongo_database)
    if is_main and not refresh and cache_path.exists():
        try:
            cached=json.loads(cache_path.read_text(encoding='utf-8'))
            cached['counts']=counts(db)
            return cached
        except Exception:
            pass
    # One facet invocation demonstrates independent aggregation views of the same review population.
    # Thống kê trên review khác nhau: bỏ bản sao của cùng một review ở ấn bản khác.
    result=list(db.reviews.aggregate([{'$match':{'is_copy':{'$ne':True}}},{'$facet':{
        'stars':[{'$group':{'_id':'$overall','count':{'$sum':1}}},{'$sort':{'_id':1}}],
        'sentiment':[{'$group':{'_id':'$sentiment.label','count':{'$sum':1}}}],
        'sentiment_by_star':[{'$group':{'_id':{'star':'$overall','sentiment':'$sentiment.label'},'count':{'$sum':1}}},{'$sort':{'_id.star':1,'_id.sentiment':1}}],
        'timeline':[{'$group':{'_id':{'$dateToString':{'format':'%Y-%m','date':'$review_date'}},'count':{'$sum':1}}},{'$sort':{'_id':1}}],
        'rating_buckets':[{'$bucket':{'groupBy':'$overall','boundaries':[1,2,3,4,5.1],'default':'other','output':{'count':{'$sum':1}}}}]
    }}],allowDiskUse=True))[0]
    high_pos=high_total=low_neg=low_nonpos=low_total=0
    for row in result['sentiment_by_star']:
        star,label,n=row['_id'].get('star'),row['_id'].get('sentiment'),row['count']
        if label not in ['positive','neutral','negative'] or star is None: continue
        if star>=4:
            high_total+=n
            if label=='positive': high_pos+=n
        elif star<=2:
            low_total+=n
            if label=='negative': low_neg+=n
            if label!='positive': low_nonpos+=n
    result['sentiment_alignment']={
        'high_star_positive_rate':round(high_pos/high_total,4) if high_total else 0.,
        'low_star_negative_rate':round(low_neg/low_total,4) if low_total else 0.,
        'low_star_non_positive_rate':round(low_nonpos/low_total,4) if low_total else 0.,
        'polarity_agreement_rate':round((high_pos+low_neg)/(high_total+low_total),4) if (high_total+low_total) else 0.,
    }
    result['counts']=counts(db)
    result['categories']=list(db.products.aggregate([{'$match':{'active':True,'primary':{'$ne':False}}},{'$unwind':'$categories'},
        {'$match':{'categories':{'$nin':sorted(NAVIGATION_CATEGORIES)}}},{'$group':{'_id':'$categories','count':{'$sum':1}}},{'$sort':{'count':-1}},{'$limit':20}]))
    result['formats']=list(db.reviews.aggregate([{'$match':{'is_copy':{'$ne':True}}},{'$unwind':'$formats'},{'$group':{'_id':'$formats','count':{'$sum':1}}},{'$sort':{'count':-1}}],allowDiskUse=True))
    if is_main: write_json(cache_path,result)
    return result
