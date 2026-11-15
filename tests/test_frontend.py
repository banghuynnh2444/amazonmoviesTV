"""Run frontend regression checks with Node.js (no browser or database writes)."""
from pathlib import Path
import os,shutil,subprocess
import pytest

def test_frontend_javascript_rendering_and_request_order():
    node=os.getenv('NODE_BINARY') or shutil.which('node')
    if not node: pytest.skip('Node.js is required for frontend checks; set NODE_BINARY if needed')
    root=Path(__file__).resolve().parents[1]
    subprocess.run([node,'--check',str(root/'amazon_movies/static/app.js')],check=True,capture_output=True,text=True,encoding='utf-8')
    subprocess.run([node,str(root/'tests/test_frontend.cjs')],check=True,capture_output=True,text=True,encoding='utf-8')
