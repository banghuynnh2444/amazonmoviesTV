"""Chạy lại toàn bộ thực nghiệm buổi 4 theo đúng thứ tự và ghi RUN_STATUS.json.

1. PageRank + Louvain (GDS) → ghi pagerank/community về Neo4j và MongoDB
2. Đánh giá gợi ý 80/20 (validation chọn λ và cách chuẩn hóa Hybrid) + kiểm chứng trùng khớp với Cypher
3. Hiệu năng trước/sau index ở 10%, 50%, 100% (MongoDB explain, Neo4j PROFILE)
4. So sánh MongoDB vs Neo4j trên 3 bài toán

Nên chạy khi không có tác vụ nặng khác (ví dụ GDS Node Similarity) để số đo thời gian không bị nhiễu.
"""
from pathlib import Path
import argparse, json, sys, time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amazon_movies.config import settings
from amazon_movies.data import write_json
from amazon_movies import mongo, graph, session4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample-users', type=int, default=1200)
    parser.add_argument('--parity-users', type=int, default=20)
    parser.add_argument('--k', type=int, default=10)
    parser.add_argument('--skip', nargs='*', default=[], choices=['analytics', 'evaluation', 'benchmark', 'comparison'])
    args = parser.parse_args()

    client, db = mongo.connect()
    driver = graph.connect()
    started = time.time()
    steps = {}
    try:
        if 'analytics' not in args.skip:
            print('1/4 PageRank & Louvain…', flush=True)
            steps['graph_analytics_seconds'] = session4.run_graph_analytics(db, driver)['seconds']
        if 'evaluation' not in args.skip:
            print('2/4 Đánh giá gợi ý 80/20 + kiểm chứng Cypher…', flush=True)
            ev = session4.evaluate_recommendations(db, sample_users=args.sample_users, k=args.k, driver=driver, parity_users=args.parity_users)
            steps['evaluation_seconds'] = ev['seconds']
            print(json.dumps(ev['metrics'], ensure_ascii=False), flush=True)
        if 'benchmark' not in args.skip:
            print('3/4 Hiệu năng index 10% / 50% / 100%…', flush=True)
            steps['index_benchmark_seconds'] = session4.benchmark_indexes(db, driver)['seconds']
        if 'comparison' not in args.skip:
            print('4/4 So sánh MongoDB và Neo4j…', flush=True)
            steps['db_comparison_seconds'] = session4.compare_databases(db, driver)['seconds']
        status_path = settings.report_dir / 'RUN_STATUS.json'
        state = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {'steps': {}}
        state.setdefault('steps', {})['session4'] = {**steps, 'total_seconds': round(time.time() - started, 2), 'ok': True,
                                                     'completed_at': time.strftime('%Y-%m-%d %H:%M:%S')}
        similarity = settings.report_dir / 'buoi3_gds_similarity.json'
        if similarity.exists():
            state['steps']['gds_similarity'] = json.loads(similarity.read_text(encoding='utf-8'))
        write_json(status_path, state)
        print('XONG sau', round(time.time() - started, 1), 'giây', flush=True)
    finally:
        driver.close()
        client.close()


if __name__ == '__main__':
    main()
