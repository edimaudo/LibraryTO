from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_homepage():
    response = client.get('/')
    assert response.status_code == 200
    assert 'LibraryTO' in response.text

def test_overview_data_route():
    response = client.get('/overview')
    assert response.status_code == 200
    assert 'branch_count' in response.json()

def test_branch_directory_route_returns_list():
    response = client.get('/branches')
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_unknown_page_renders_branded_404():
    response = client.get('/this-page-does-not-exist')
    assert response.status_code == 404
    assert 'Page not found' in response.text
    assert 'Go to Overview' in response.text


def test_single_root_fastapi_entrypoint():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    assert (project_root / "main.py").is_file()
    assert not (project_root / "app" / "main.py").exists()
    assert app.title == "LibraryTO"


def test_no_route_contains_api_prefix():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    forbidden_prefix = "/" + "api/"
    assert all(forbidden_prefix not in getattr(route, "path", "") for route in app.routes)
    frontend = (project_root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert forbidden_prefix not in frontend


def test_vercel_configuration_matches_project_specification():
    import json
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    config = json.loads((project_root / "vercel.json").read_text(encoding="utf-8"))
    assert config == {
        "version": 2,
        "builds": [{
            "src": "main.py",
            "use": "@vercel/python",
            "config": {
                "maxDuration": 300,
                "memory": 1024,
                "includeFiles": "data/**",
            },
        }],
        "rewrites": [
            {"source": "/(.*)", "destination": "main.py"},
            {"source": "/(.*)", "destination": "main.py"},
        ],
    }


def test_data_route_validation_errors_are_json():
    response = client.get("/branches/BR001/forecasts?horizon=invalid")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
