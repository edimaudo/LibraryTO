from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_homepage():
    response = client.get('/')
    assert response.status_code == 200
    assert 'LibraryTO' in response.text

def test_overview_api():
    response = client.get('/api/overview')
    assert response.status_code == 200
    assert 'branch_count' in response.json()

def test_branch_api_returns_list():
    response = client.get('/api/branches')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_unknown_page_renders_branded_404():
    response = client.get('/this-page-does-not-exist')
    assert response.status_code == 404
    assert 'Page not found' in response.text
    assert 'Go to Overview' in response.text

def test_unknown_api_route_returns_json_404():
    response = client.get('/api/this-route-does-not-exist')
    assert response.status_code == 404
    assert response.headers['content-type'].startswith('application/json')


def test_single_root_fastapi_entrypoint():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    assert (project_root / "main.py").is_file()
    assert not (project_root / "app" / "main.py").exists()
    assert app.title == "LibraryTO"
