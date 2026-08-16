from fastapi.testclient import TestClient

from onep.web.server import create_app


def test_index_served_from_dist_when_present(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<!DOCTYPE html><html><head><title>OnePTeam Web Console</title></head>'
        '<body><div id="root"></div>'
        '<script type="module" src="/assets/index.js"></script></body></html>')
    (dist / "assets").mkdir()
    (dist / "assets" / "index.js").write_text("console.log('onep-ui');")
    monkeypatch.setattr("onep.web.server.UI_DIST", dist)
    client = TestClient(create_app())
    assert client.get("/").status_code == 200
    assert '<div id="root">' in client.get("/").text
    assert client.get("/assets/index.js").status_code == 200


def test_index_fallback_without_dist(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.web.server.UI_DIST", tmp_path / "missing")
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "OnePTeam Web Console" in response.text
    assert "/api/projects" in response.text
