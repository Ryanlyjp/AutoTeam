import json

from autoteam import easyproxy


def _env(**overrides):
    base = {
        "EASYPROXY_ENABLED": "true",
        "EASYPROXY_MANAGEMENT_URL": "http://127.0.0.1:9888",
        "EASYPROXY_PASSWORD": "secret",
        "EASYPROXY_PROXY_HOST": "127.0.0.1",
        "EASYPROXY_POOL_PORT": "2323",
        "EASYPROXY_PORT_MIN": "24000",
        "EASYPROXY_PORT_MAX": "24010",
        "EASYPROXY_COOLDOWN_MINUTES": "60",
        "EASYPROXY_MASTER_MODE": "direct",
    }
    base.update(overrides)
    return base


def test_select_proxy_assignment_uses_random_choice_across_selectable_ports(monkeypatch, tmp_path):
    monkeypatch.setattr(easyproxy, "STATE_FILE", tmp_path / "easyproxy_state.json")

    class FakeClient:
        def __init__(self, _cfg):
            self.cfg = _cfg

        def get_json(self, _path):
            return {
                "nodes": [
                    {"port": 24001, "tag": "node-1", "name": "node-1", "available": True, "blacklisted": False},
                    {"port": 24002, "tag": "node-2", "name": "node-2", "available": True, "blacklisted": True},
                    {"port": 24005, "tag": "node-5", "name": "node-5", "available": True, "blacklisted": False},
                ]
            }

    observed = {}

    def fake_choice(candidates):
        observed["ports"] = [entry["port"] for entry in candidates]
        return candidates[-1]

    monkeypatch.setattr(easyproxy, "EasyProxyClient", FakeClient)
    monkeypatch.setattr(easyproxy.secrets, "choice", fake_choice)

    assignment = easyproxy.select_proxy_assignment(env=_env())

    assert observed["ports"] == [24001, 24005]
    assert assignment == {
        "proxy_url": "http://127.0.0.1:24005",
        "port": 24005,
        "tag": "node-5",
        "name": "node-5",
    }


def test_select_proxy_assignment_avoids_last_selected_port_when_possible(monkeypatch, tmp_path):
    state_file = tmp_path / "easyproxy_state.json"
    state_file.write_text(json.dumps({"local_blacklist": {}, "last_selected_port": 24001}))
    monkeypatch.setattr(easyproxy, "STATE_FILE", state_file)

    class FakeClient:
        def __init__(self, _cfg):
            self.cfg = _cfg

        def get_json(self, _path):
            return {
                "nodes": [
                    {"port": 24001, "tag": "node-1", "name": "node-1", "available": True, "blacklisted": False},
                    {"port": 24005, "tag": "node-5", "name": "node-5", "available": True, "blacklisted": False},
                ]
            }

    observed = {}

    def fake_choice(candidates):
        observed["ports"] = [entry["port"] for entry in candidates]
        return candidates[0]

    monkeypatch.setattr(easyproxy, "EasyProxyClient", FakeClient)
    monkeypatch.setattr(easyproxy.secrets, "choice", fake_choice)

    assignment = easyproxy.select_proxy_assignment(env=_env())

    assert observed["ports"] == [24005]
    assert assignment["port"] == 24005
    state = json.loads(state_file.read_text())
    assert state["last_selected_port"] == 24005


def test_release_ports_clears_local_blacklist_and_releases_remote(monkeypatch, tmp_path):
    state_file = tmp_path / "easyproxy_state.json"
    monkeypatch.setattr(easyproxy, "STATE_FILE", state_file)

    easyproxy.set_pending_assignment({"port": 24007, "tag": "node-7", "name": "node-7"})
    easyproxy.mark_pending_assignment_bad("timeout", env=_env())

    released_paths = []

    class FakeClient:
        def __init__(self, _cfg):
            self.cfg = _cfg

        def get_json(self, _path):
            return {
                "nodes": [
                    {"port": 24007, "tag": "node-7", "name": "node-7", "available": True, "blacklisted": False},
                ]
            }

        def post_json(self, path, payload=None):
            released_paths.append((path, payload))
            return {"ok": True}

    monkeypatch.setattr(easyproxy, "EasyProxyClient", FakeClient)

    result = easyproxy.release_ports([24007], remote=True, env=_env())
    state = json.loads(state_file.read_text())

    assert state["local_blacklist"] == {}
    assert result["ok"] is True
    assert result["released"]["local"] == [24007]
    assert result["released"]["remote"] == [24007]
    assert result["summary"]["local_blacklisted"] == 0
    assert result["ports"][0]["selectable"] is True
    assert released_paths == [("/api/nodes/node-7/release", None)]
