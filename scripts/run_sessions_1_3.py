"""Chạy đầy đủ công việc buổi 1–3; dữ liệu/CSDL đặt tại DATA_DIR và runtime ổ D."""
from pathlib import Path
import argparse, sys, time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from amazon_movies.config import settings
from amazon_movies.data import eda,write_json
from amazon_movies import mongo,graph

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--skip-eda',action='store_true')
    args=parser.parse_args()
    client,db=mongo.connect(); driver=graph.connect()
    state={'started_at':time.time(),'scope':'full Movies_and_TV_5 + metadata','steps':{}}
    def record(stage,result):
        state['steps'][stage]=result; state['elapsed_seconds']=round(time.time()-state['started_at'],2)
        write_json(settings.report_dir/'RUN_STATUS.json',state)
        print(stage,result,flush=True)
    try:
        record('environment',{'mongo':client.server_info()['version'],**graph.initialize(driver)})
        if not args.skip_eda: record('eda',eda(settings))
        mongo.initialize(db)
        record('mongodb',mongo.import_data(db,workers=args.workers))
        # Xóa SIMILAR_TO cũ theo lô (hàng triệu quan hệ không xóa được trong một giao dịch).
        with driver.session(database=settings.neo4j_database) as session:
            session.run('MATCH ()-[r:SIMILAR_TO]->() CALL (r) { DELETE r } IN TRANSACTIONS OF 50000 ROWS').consume()
        record('neo4j',graph.import_graph(db,driver))
        # Mặc định: người dùng từ 5 review, ít nhất 3 phim thích (phủ ~89% người dùng, ~22 phút trên toàn bộ dữ liệu).
        record('gds_similarity',graph.gds_similarity(driver,top_k=20))
        verification=graph.verify(db,driver)
        record('reconciliation',verification)
        if not verification['ok']: raise RuntimeError('Đối soát hai CSDL không khớp')
        from verify_session3 import main as smoke
        smoke()
        state['complete']=True; record('queries_api',{'report':'buoi3_queries_api.json','ok':True})
    except Exception as exc:
        state['complete']=False; state['error']={'type':type(exc).__name__,'message':str(exc)}
        write_json(settings.report_dir/'RUN_STATUS.json',state)
        raise
    finally: driver.close(); client.close()

if __name__=='__main__': main()
