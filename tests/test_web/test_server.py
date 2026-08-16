from types import SimpleNamespace
import sys

def test_run_server_uses_config_defaults(monkeypatch):
    calls = {}
    fake_uvicorn = SimpleNamespace(run=lambda app, host, port, log_level: calls.update(
        host=host, port=port, log_level=log_level))
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr("onep.web.runtime.web_config", lambda: ("127.0.0.1", 8311))
    from onep.web.server import run_server
    run_server()
    assert calls == {"host": "127.0.0.1", "port": 8311, "log_level": "info"}
    run_server(host="0.0.0.0", port=9000)
    assert calls["host"] == "0.0.0.0" and calls["port"] == 9000
