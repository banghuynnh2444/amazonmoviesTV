"""Kiểm thử CSDL thật; bật bằng MOVIES_INTEGRATION=1. Chỉ ghi bộ TEST riêng."""
from dataclasses import replace
import os, secrets, uuid
import pytest
from amazon_movies.config import settings
from amazon_movies import mongo,graph
from amazon_movies.api import create_app

pytestmark=pytest.mark.skipif(os.getenv('MOVIES_INTEGRATION')!='1',reason='Cần hai CSDL thật và MOVIES_INTEGRATION=1')

@pytest.fixture()
def live():
    # A unique database per test avoids removing another run's fixtures.
    tag='TEST_'+uuid.uuid4().hex
    # Mật khẩu quản trị chỉ dùng trong lần chạy thử này.
    config=replace(settings,mongo_database='amazon_movies_tv_test_'+tag[5:],admin_username='admin',admin_password=secrets.token_urlsafe(16))
    client,db=mongo.connect(config); driver=graph.connect(config)
    mongo.initialize(db); graph.initialize(driver,config)
    asin=tag+'_product'
    db.products.insert_one({'_id':asin,'asin':asin,'title':'Integration test film','active':True,'formats':[],'category_paths':[['TEST']], 'categories':['TEST'],'brand':'','price':None,'stats':{'review_count':0,'avg_rating':0,'pagerank':1.5,'community':7}})
    graph.run(driver,graph.PRODUCTS,{'rows':[graph.product_row(db.products.find_one({'asin':asin}))]},config)
    app=create_app(db,driver,config); app.config['TESTING']=True
    yield db,driver,config,app.test_client(),asin
    user_ids=list(db.users.distinct('reviewerID',{'is_demo':True}))
    product_ids=list(db.products.distinct('asin'))
    try:
        graph.run(driver,'MATCH (n) WHERE (n:Product AND n.asin IN $asins) OR (n:User AND n.reviewerID IN $users) DETACH DELETE n',{'asins':product_ids,'users':user_ids},config)
        graph.run(driver,"MATCH (c:Category {name:'TEST'}) WHERE NOT (c)--() DELETE c",config=config)
        # Only remove the unique database owned by this fixture.
        client.drop_database(config.mongo_database)
    finally: driver.close(); client.close()

def account(client,name):
    response=client.post('/api/auth/register',json={'username':name,'password':'test-password-12345'})
    assert response.status_code==201
    data=response.get_json()
    return data['reviewerID'],{'Authorization':'Bearer '+data['token']}

def test_authenticated_review_edit_vote_and_graph_idempotency(live):
    db,driver,config,client,asin=live
    uid,headers=account(client,'writer')
    assert client.get('/api/products?min_price=nan').status_code==400
    assert client.post('/api/reviews',json={'asin':asin,'overall':5}).status_code==401
    assert client.post('/api/reviews',headers=headers,json={'asin':asin,'overall':True}).status_code==400
    response=client.post('/api/reviews',headers=headers,json={'asin':asin,'overall':5,'reviewText':'I love this wonderful film.'})
    assert response.status_code==201
    rid=response.get_json()['review_id']
    assert db.reviews.find_one({'_id':rid})['synced'] is True
    stats=db.products.find_one({'asin':asin})['stats']
    assert stats['review_count']==1 and stats['pagerank']==1.5 and stats['community']==7  # ghi review không xóa kết quả GDS
    assert client.put('/api/reviews/'+rid,headers=headers,json={'overall':2,'reviewText':'A terrible film.'}).status_code==200
    assert client.post('/api/reviews/'+rid+'/helpful',headers=headers).status_code==400
    voter,voter_headers=account(client,'voter')
    assert client.post('/api/reviews/'+rid+'/helpful',headers=voter_headers).status_code==200
    assert client.post('/api/reviews/'+rid+'/helpful',headers=voter_headers).status_code==409
    graph.sync_pending(db,driver,config)
    rows=graph.run(driver,'MATCH ()-[r:REVIEWED {review_id:$id}]->() RETURN count(r) AS n,max(r.rating) AS rating,max(r.helpful) AS helpful',{'id':rid},config)
    assert rows[0]=={'n':1,'rating':2.0,'helpful':1}
    assert db.products.find_one({'asin':asin})['stats']['stars']['2']==1
    assert db.reviews.find_one({'_id':rid})['source_vote']==0
    assert db.reviews.find_one({'_id':rid})['demo_vote_count']==1
    assert db.users.find_one({'reviewerID':uid})['password_hash']!='test-password-12345'
    # Mỗi người chỉ một đánh giá cho một tác phẩm; muốn đổi thì sửa đánh giá cũ.
    again=client.post('/api/reviews',headers=headers,json={'asin':asin,'overall':3})
    assert again.status_code==409 and again.get_json()['review_id']==rid
    # Xóa: mất ở cả hai CSDL, thống kê phim cập nhật.
    assert client.delete('/api/reviews/'+rid,headers=voter_headers).status_code==404
    assert client.delete('/api/reviews/'+rid,headers=headers).status_code==200
    assert db.reviews.find_one({'_id':rid}) is None
    assert graph.run(driver,'MATCH ()-[r:REVIEWED {review_id:$id}]->() RETURN count(r) AS n',{'id':rid},config)[0]['n']==0
    assert db.products.find_one({'asin':asin})['stats'].get('work_reviews',0)==0

def test_delete_keeps_mongodb_when_graph_is_down(live,monkeypatch):
    db,driver,config,client,asin=live
    uid,headers=account(client,'deleter')
    rid=client.post('/api/reviews',headers=headers,json={'asin':asin,'overall':4}).get_json()['review_id']
    def unavailable(*args,**kwargs): raise ConnectionError('Controlled outage')
    monkeypatch.setattr(graph,'run',unavailable)
    assert client.delete('/api/reviews/'+rid,headers=headers).status_code==503
    assert db.reviews.find_one({'_id':rid}) is not None

def test_admin_area_requires_admin_account(live):
    db,driver,config,client,asin=live
    uid,headers=account(client,'normaluser')
    for path in ['/api/statistics','/api/experiments','/api/admin/overview','/api/users/sample','/api/recommendations/'+uid,'/api/graph/ego?asin='+asin]:
        assert client.get(path).status_code==401, path
        assert client.get(path,headers=headers).status_code==403, path
    assert client.post('/api/auth/register',json={'username':'admin','password':'another-password-1'}).status_code==409
    assert client.post('/api/auth/login',json={'username':'admin','password':'wrong-password-1'}).status_code==401
    login=client.post('/api/auth/login',json={'username':'admin','password':config.admin_password})
    assert login.status_code==200 and login.get_json()['role']=='admin'
    admin={'Authorization':'Bearer '+login.get_json()['token']}
    assert client.get('/api/admin/overview',headers=admin).status_code==200
    assert client.get('/api/recommendations/'+uid,headers=admin).status_code==200
    # Token quản trị không dùng được cho thao tác của người dùng.
    assert client.post('/api/reviews',headers=admin,json={'asin':asin,'overall':5}).status_code==401

def test_graph_failure_queues_review_and_retry_recovers(live,monkeypatch):
    db,driver,config,client,asin=live
    uid,headers=account(client,'retryuser')
    original=graph.run
    def unavailable(*args,**kwargs): raise ConnectionError('Controlled outage')
    monkeypatch.setattr(graph,'run',unavailable)
    response=client.post('/api/reviews',headers=headers,json={'asin':asin,'overall':4,'reviewText':'Good.'})
    assert response.status_code==202
    rid=response.get_json()['review_id']
    assert db.reviews.find_one({'_id':rid})['synced'] is False
    monkeypatch.setattr(graph,'run',original)
    graph.sync_pending(db,driver,config)
    assert db.reviews.find_one({'_id':rid})['synced'] is True
    assert graph.run(driver,'MATCH ()-[r:REVIEWED {review_id:$id}]->() RETURN count(r) AS n',{'id':rid},config)[0]['n']==1

def test_acknowledging_old_version_does_not_hide_new_write(live):
    db,driver,config,client,asin=live
    uid,headers=account(client,'versionuser')
    response=client.post('/api/reviews',headers=headers,json={'asin':asin,'overall':4,'reviewText':'Good.'})
    old=db.reviews.find_one({'_id':response.get_json()['review_id']})
    db.reviews.update_one({'_id':old['_id']},{'$inc':{'version':1},'$set':{'synced':False}})
    graph.acknowledge(db,[old])
    assert db.reviews.find_one({'_id':old['_id']})['synced'] is False
    newer=graph.review_row({**old,'version':old['version']+1,'overall':5.})
    graph.run(driver,graph.REVIEWS,{'rows':[newer]},config)
    graph.run(driver,graph.REVIEWS,{'rows':[graph.review_row(old)]},config)
    stored=graph.run(driver,'MATCH ()-[r:REVIEWED {review_id:$id}]->() RETURN r.rating AS rating,r.version AS version',{'id':old['_id']},config)[0]
    assert stored['rating']==5. and stored['version']==old['version']+1

def test_cold_start_returns_popular_without_recommending_seen(live):
    db,driver,config,client,asin=live
    uid,headers=account(client,'coldstart')
    response=client.get('/api/me/recommendations',headers=headers)
    data=response.get_json()
    assert response.status_code==200 and data['fallback_to_popular'] is True and data['needs_more_ratings'] is True
    client.post('/api/reviews',headers=headers,json={'asin':asin,'overall':5})
    data=client.get('/api/me/recommendations',headers=headers).get_json()
    assert asin not in [i['product']['asin'] for i in data['items']] and data['rated']==1
    assert asin not in [p['asin'] for p in client.get('/api/me/to-rate',headers=headers).get_json()['items']]


def test_related_matches_offline_when_more_than_five_reviews_share_timestamp(live):
    from amazon_movies.algorithms import Catalog, Interactions, Recommender
    from amazon_movies.recommend import related_for_user
    from amazon_movies.data import review
    db,driver,config,client,asin=live
    uid,headers=account(client,'ties')
    events=[]
    expected=[]
    for i in range(6):
        seed=f'{asin}_seed_{i}'
        target=f'{asin}_target_{i}'
        for product_id in (seed,target):
            db.products.insert_one({'_id':product_id,'asin':product_id,'title':product_id,'active':True,
                                    'also_buy':[target] if product_id==seed else [],'also_view':[],
                                    'formats':[],'category_paths':[],'brand':''})
        doc=review({'reviewerID':uid,'asin':seed,'overall':5,'unixReviewTime':1500000000},False)
        doc.update(_id=f'{asin}_review_{i}',review_id=f'{asin}_review_{i}',is_demo=True)
        db.reviews.insert_one(doc)
        events.append((uid,seed,5.,1500000000,doc['_id'],'pending'))
        if i: expected.append(target)
    mongo.rebuild_stats(db)
    products=list(db.products.find())
    graph.run(driver,graph.PRODUCTS,{'rows':[graph.product_row(p) for p in products]},config)
    graph.run(driver,graph.LINKS,{'rows':[{'asin':p['asin'],'also_buy':p.get('also_buy',[]),'also_view':[]} for p in products]},config)
    offline=Recommender(Catalog(products),Interactions(list(reversed(events)))).related(uid)
    online=related_for_user(db,driver,uid,config)
    assert [r['asin'] for r in online]==expected
    assert online==offline
