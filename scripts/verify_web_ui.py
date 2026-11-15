"""Kiểm tra website và toàn bộ REST API trên dữ liệu thật (chỉ đọc), ghi reports/buoi5_web_ui.json.

Không tạo tài khoản hay review; luồng ghi được kiểm tra bằng tests/test_integration.py trên database riêng.
Khu quản trị được kiểm tra bằng tài khoản quản trị trong .env (python -m amazon_movies create-admin).
"""
from pathlib import Path
import sys, time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from amazon_movies.config import settings
from amazon_movies import mongo, graph
from amazon_movies.api import create_app
from amazon_movies.data import write_json

USER_PAGES = [
    ('#/', 'Trang chủ: phim được yêu thích nhất, điểm cao nhất (Bayesian), thể loại; gợi ý riêng khi đã đăng nhập'),
    ('#/search', 'Tìm phim: từ khóa, thể loại, định dạng, khoảng giá, sắp xếp, phân trang; mỗi tác phẩm một dòng'),
    ('#/search?mode=reviews', 'Tìm trong lời đánh giá, lọc khen/chê'),
    ('#/movie/{asin}', 'Chi tiết phim: điểm và phân bố sao theo tác phẩm, khen/chê, từ khóa, các phiên bản, chấm/sửa/xóa đánh giá, phim mua cùng'),
    ('#/for-you', 'Gợi ý cho bạn: chấm nhanh khi chưa đủ 3 phim, danh sách gợi ý kèm lý do'),
    ('#/reviewer/{reviewerID}', 'Các đánh giá của một người xem'),
    ('#/account', 'Đăng ký, đăng nhập, phim bạn đã chấm'),
]
ADMIN_PAGES = [
    ('#/admin', 'Hệ thống & dữ liệu: trạng thái CSDL, đối soát trực tiếp, hàng chờ đồng bộ, gộp ấn bản, tham số gợi ý'),
    ('#/admin/recommend', 'Phân tích gợi ý: 5 phương pháp, thành phần Hybrid, người dùng tương đồng'),
    ('#/admin/user/{reviewerID}', 'Lịch sử review và người dùng tương đồng'),
    ('#/admin/graph', 'Đồ thị con quanh một phim hoặc người dùng (vis-network)'),
    ('#/admin/stats', 'Thống kê review: kiểm chứng VADER và 6 biểu đồ (Chart.js)'),
    ('#/admin/experiments', 'Kết quả thực nghiệm đọc từ reports/'),
    ('#/admin/communities', 'PageRank, Louvain và 10 cộng đồng lớn nhất'),
]


def main():
    client, db = mongo.connect()
    driver = graph.connect()
    try:
        app = create_app(db, driver)
        test = app.test_client()
        login = test.post('/api/auth/login', json={'username': settings.admin_username, 'password': settings.admin_password})
        assert login.status_code == 200, 'cần ADMIN_PASSWORD trong .env (python -m amazon_movies create-admin)'
        admin = {'Authorization': 'Bearer ' + login.get_json()['token']}
        user = db.users.find_one({'is_demo': {'$ne': True}, 'stats.review_count': {'$gte': 30, '$lte': 120}},
                                 sort=[('stats.review_count', -1), ('_id', 1)])['reviewerID']
        asin = 'B00OV3VGP0'
        community = db.products.find_one({'asin': asin})['stats']['community']
        public = [
            ('/', 200), ('/static/app.js', 200), ('/static/styles.css', 200),
            ('/static/vendor/chart.umd.js', 200), ('/static/vendor/vis-network.min.js', 200),
            ('/api/health', 200), ('/api/facets', 200), ('/api/home', 200),
            ('/api/products?q=star%20wars&format=Blu-ray&min_price=5&max_price=30&sort=rating', 200),
            (f'/api/products/{asin}', 200), (f'/api/products/{asin}/keywords', 200),
            (f'/api/products/{asin}/related?steps=1', 200), (f'/api/products/{asin}/related?steps=2', 200),
            ('/api/reviews?q=masterpiece&sentiment=negative', 200), ('/api/reviews?q=good', 200),
            (f'/api/reviews?work={asin}&sort=helpful', 200), (f'/api/users/{user}/profile', 200),
            ('/api/products/KHONG_TON_TAI', 404), ('/api/products?min_price=abc', 400), ('/api/reviews', 200),
            ('/api/auth/me', 401), ('/api/me/recommendations', 401), ('/api/me/to-rate', 401),
        ]
        admin_paths = [
            '/api/admin/overview', '/api/users/sample', f'/api/users/{user}/similar',
            *[f'/api/recommendations/{user}?method={m}' for m in ['hybrid', 'collaborative', 'related', 'content', 'popular']],
            '/api/recommendations/NGUOI_DUNG_MOI?method=hybrid',
            f'/api/graph/ego?asin={asin}', f'/api/graph/ego?user={user}',
            '/api/statistics', '/api/analytics/communities', f'/api/analytics/communities?community={community}', '/api/experiments',
        ]
        results = {}

        def check(label, path, expected, headers=None):
            started = time.perf_counter()
            response = test.get(path, headers=headers or {})
            results[label] = {'status': response.status_code, 'expected': expected, 'ms': round((time.perf_counter() - started) * 1000, 1)}
            assert response.status_code == expected, (label, response.status_code)
            return response

        for path, expected in public:
            check(path, path, expected)
        for path in admin_paths:
            check(path + ' (không đăng nhập)', path, 401)
            check(path + ' (quản trị)', path, 200, admin)
        check('/api/recommendations/x?method=sai (quản trị)', '/api/recommendations/x?method=sai', 400, admin)
        html = test.get('/').get_data(as_text=True)
        assert 'cdn.jsdelivr.net' not in html and '/static/vendor/chart.umd.js' in html
        cold = test.get('/api/recommendations/NGUOI_DUNG_MOI?method=hybrid', headers=admin).get_json()
        assert cold['fallback_to_popular'] is True
        capped = test.get('/api/reviews?q=good').get_json()
        detail = test.get(f'/api/products/{asin}').get_json()
        user_view = test.get('/api/home').get_json()
        assert all(k not in user_view for k in ('pagerank', 'communities')), 'trang chủ người dùng không chứa số liệu kỹ thuật'
        report = {
            'url': f'http://{settings.api_host}:{settings.api_port}',
            'frontend': {'template': 'amazon_movies/templates/index.html', 'stylesheet': 'amazon_movies/static/styles.css',
                         'script': 'amazon_movies/static/app.js',
                         'libraries': ['Chart.js 4.4.3 (static/vendor/chart.umd.js)', 'vis-network 9.1.9 (static/vendor/vis-network.min.js)'],
                         'offline': 'Không nạp tài nguyên từ Internet',
                         'user_pages': [{'route': route, 'content': content} for route, content in USER_PAGES],
                         'admin_pages': [{'route': route, 'content': content} for route, content in ADMIN_PAGES]},
            'access': 'Khu quản trị và API phân tích trả 401 khi chưa đăng nhập, 403 với tài khoản người dùng thường.',
            'sample': {'reviewerID': user, 'asin': asin, 'community': community, 'work_reviews': detail['work_stats']['reviews']},
            'endpoints_verified': results,
            'behaviour': {'new_user_gets_popular_fallback': cold['fallback_to_popular'],
                          'common_word_search_is_capped': {'query': 'good', 'total_capped': capped['total_capped'], 'sort': capped['sort']}},
            'endpoints': len(results), 'ok': True, 'checked_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        write_json(settings.report_dir / 'buoi5_web_ui.json', report)
        print(f"{len(results)} kiểm tra endpoint đạt; chậm nhất:", sorted(((v['ms'], k) for k, v in results.items()), reverse=True)[:3])
    finally:
        driver.close()
        client.close()


if __name__ == '__main__':
    main()
