from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / '.env', override=False)

@dataclass(frozen=True)
class Settings:
    mongo_uri: str = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27028')
    mongo_database: str = os.getenv('MONGO_DATABASE', 'amazon_movies_tv')
    neo4j_uri: str = os.getenv('NEO4J_URI', 'bolt://127.0.0.1:7698')
    neo4j_user: str = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password: str = os.getenv('NEO4J_PASSWORD', '')
    neo4j_database: str = os.getenv('NEO4J_DATABASE', 'neo4j')
    app_secret: str = os.getenv('APP_SECRET', '')
    # Tài khoản quản trị (khu phân tích). Tạo bằng: python -m amazon_movies create-admin (mật khẩu ngẫu nhiên ghi vào .env).
    admin_username: str = os.getenv('ADMIN_USERNAME', 'admin').strip().lower()
    admin_password: str = os.getenv('ADMIN_PASSWORD', '')
    api_host: str = os.getenv('API_HOST', '127.0.0.1')
    api_port: int = int(os.getenv('API_PORT', '5055'))
    data_dir: Path = (PROJECT / os.getenv('DATA_DIR', 'D:/AmazonMoviesTV/data')).resolve()
    report_dir: Path = (PROJECT / os.getenv('REPORT_DIR', 'reports')).resolve()

    def raw(self, name):
        return self.data_dir / 'raw' / name

settings = Settings()
