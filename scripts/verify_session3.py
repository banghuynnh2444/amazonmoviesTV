"""Kiểm tra truy vấn/API trên dữ liệu thật, không ghi review demo vào dữ liệu nguồn."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from amazon_movies.config import settings
from amazon_movies import mongo,graph
from amazon_movies.api import create_app
from amazon_movies.recommend import recommend, seen_works
from amazon_movies.data import write_json

def main():
    client,db=mongo.connect(); driver=graph.connect()
    try:
        graph.run(driver,"MATCH (c:Category {name:'TEST'}) WHERE NOT (c)--() DELETE c")
        users=list(db.users.find({'is_demo':False,'stats.review_count':{'$gte':10,'$lte':30}}).sort('stats.review_count',-1).limit(5))
        if not users: users=list(db.users.find({'is_demo':False}).sort('stats.review_count',-1).limit(5))
        selected=users[0]['reviewerID']
        for u in users:
            if not recommend(db,driver,u['reviewerID'],'collaborative',5)['fallback_to_popular']:
                selected=u['reviewerID']; break
        methods={}
        # Mức tác phẩm: không gợi ý lại tác phẩm đã review ở bất kỳ ấn bản nào, và chỉ gợi ý ấn bản đại diện.
        seen=seen_works(db,selected)
        for method in ['collaborative','related','content','hybrid','popular']:
            result=recommend(db,driver,selected,method,10)
            asins=[row['asin'] for row in result['items']]
            works={p['asin']:p.get('work') or p['asin'] for p in db.products.find({'asin':{'$in':asins}},{'work':1,'asin':1})}
            assert all(works[a] not in seen for a in asins)
            assert all(works[a]==a for a in asins), 'chỉ gợi ý ấn bản đại diện'
            assert len(set(asins))==len(asins)
            methods[method]={'count':len(asins),'fallback':result['fallback_to_popular'],'examples':[{'asin':row['asin'],'score':row['score']} for row in result['items'][:3]]}
        app=create_app(db,driver); test=app.test_client()
        login=test.post('/api/auth/login',json={'username':settings.admin_username,'password':settings.admin_password})
        assert login.status_code==200,'cần ADMIN_PASSWORD trong .env (python -m amazon_movies create-admin)'
        admin={'Authorization':'Bearer '+login.get_json()['token']}
        asin=db.products.find_one({'active':True})['asin']
        public=['/api/health','/api/products','/api/products?q=film','/api/reviews?q=good','/api/products/'+asin,
                '/api/products/'+asin+'/related','/api/products/'+asin+'/keywords','/api/home']
        protected=['/api/recommendations/'+selected+'?method=hybrid','/api/statistics']
        statuses={path:test.get(path).status_code for path in public}
        statuses.update({path+' (không đăng nhập)':test.get(path).status_code for path in protected})
        responses={path:test.get(path,headers=admin) for path in protected}
        statuses.update({path+' (quản trị)':resp.status_code for path,resp in responses.items()})
        assert all(statuses[p]==200 for p in public) and all(statuses[p+' (không đăng nhập)']==401 for p in protected) \
            and all(statuses[p+' (quản trị)']==200 for p in protected), statuses
        stats_payload=responses['/api/statistics'].get_json()
        result={'dataset_reviews':db.reviews.count_documents({'source':'amazon_2018'}),'methods':methods,'sentiment_alignment':stats_payload.get('sentiment_alignment',{}),'api_statuses':statuses,'all_passed':True}
        write_json(settings.report_dir/'buoi3_queries_api.json',result)
        print(result)
    finally: driver.close(); client.close()

if __name__=='__main__': main()
