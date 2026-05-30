import importlib

from autoteam import config


def test_easyproxy_follow_pool_overrides_manual_proxy(monkeypatch):
    monkeypatch.setenv("EASYPROXY_ENABLED", "true")
    monkeypatch.setenv("EASYPROXY_MASTER_MODE", "follow_pool")
    monkeypatch.setenv("EASYPROXY_PROXY_HOST", "10.0.0.5")
    monkeypatch.setenv("EASYPROXY_POOL_PORT", "2323")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_URL", "http://manual-proxy:8080")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_BYPASS", "localhost,127.0.0.1")

    importlib.reload(config)
    try:
        assert config.get_chatgpt_http_proxy_url() == "http://10.0.0.5:2323"
        assert config.get_playwright_launch_options()["proxy"] == {
            "server": "http://10.0.0.5:2323",
            "bypass": "localhost,127.0.0.1",
        }
    finally:
        importlib.reload(config)


def test_easyproxy_direct_disables_proxy_even_if_manual_proxy_is_set(monkeypatch):
    monkeypatch.setenv("EASYPROXY_ENABLED", "true")
    monkeypatch.setenv("EASYPROXY_MASTER_MODE", "direct")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_URL", "http://manual-proxy:8080")
    monkeypatch.setenv("PLAYWRIGHT_PROXY_BYPASS", "localhost,127.0.0.1")

    importlib.reload(config)
    try:
        assert config.get_chatgpt_http_proxy_url() == ""
        from autoteam import easyproxy

        monkeypatch.setattr(
            easyproxy,
            "select_proxy_assignment",
            lambda env=None: {
                "proxy_url": "http://10.0.0.9:24007",
                "port": 24007,
                "tag": "node-7",
                "name": "node-7",
            },
        )

        assert config.get_playwright_launch_options()["proxy"] == {
            "server": "http://10.0.0.9:24007",
            "bypass": "localhost,127.0.0.1",
        }
    finally:
        importlib.reload(config)
