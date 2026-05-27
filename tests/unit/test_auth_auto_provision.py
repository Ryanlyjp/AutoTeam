import base64
import json

import requests

from autoteam import chatgpt_api, codex_auth


def _encode_oauth_session(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = list(cookies)

    def cookies(self, _urls):
        return list(self._cookies)


class _FakeResponse:
    def __init__(self, status_code, *, headers=None, json_data=None, url=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data
        self.url = url

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def test_chatgpt_team_api_get_auto_provision_reads_known_fields(monkeypatch):
    client = chatgpt_api.ChatGPTTeamAPI()
    monkeypatch.setattr(
        client,
        "get_identity",
        lambda: {"settings": {"auto_provision": {"value": True}}},
    )

    assert client.get_auto_provision() is True


def test_chatgpt_team_api_set_auto_provision_posts_expected_payload(monkeypatch):
    client = chatgpt_api.ChatGPTTeamAPI()
    client.account_id = "team-1"
    calls = []

    def fake_api_fetch(method, path, body=None):
        calls.append((method, path, body))
        return {"status": 200, "body": "{}"}

    monkeypatch.setattr(client, "_api_fetch", fake_api_fetch)

    client.set_auto_provision(True)

    assert calls == [
        ("POST", "/backend-api/accounts/team-1/settings/auto_provision", {"value": True}),
    ]


def test_ensure_auto_provision_enabled_turns_setting_on(monkeypatch):
    events = []
    sleep_calls = []

    class FakeClient:
        def start(self):
            events.append("start")

        def get_auto_provision(self):
            events.append("get")
            return False

        def set_auto_provision(self, value):
            events.append(("set", value))

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(chatgpt_api, "ChatGPTTeamAPI", FakeClient)
    monkeypatch.setattr(codex_auth.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    assert codex_auth._ensure_auto_provision_enabled() is True
    assert events == ["start", "get", ("set", True), "stop"]
    assert sleep_calls == [codex_auth.AUTO_PROVISION_PROPAGATION_DELAY]


def test_ensure_auto_provision_enabled_skips_when_already_on(monkeypatch):
    events = []
    sleep_calls = []

    class FakeClient:
        def start(self):
            events.append("start")

        def get_auto_provision(self):
            events.append("get")
            return True

        def set_auto_provision(self, value):
            events.append(("set", value))

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(chatgpt_api, "ChatGPTTeamAPI", FakeClient)
    monkeypatch.setattr(codex_auth.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    assert codex_auth._ensure_auto_provision_enabled() is False
    assert events == ["start", "get", "stop"]
    assert sleep_calls == []


def test_login_codex_via_browser_runs_auto_provision_first(monkeypatch):
    events = []

    def fake_ensure():
        events.append("ensure")
        return True

    def fake_direct(email, password, mail_client=None, *, return_result=False, signup_profile=None):
        events.append(("direct", email, password, mail_client, return_result, signup_profile))
        return {"ok": True}

    monkeypatch.setattr(codex_auth, "_ensure_auto_provision_enabled", fake_ensure)
    monkeypatch.setattr(codex_auth, "_login_codex_via_browser_direct", fake_direct)

    result = codex_auth.login_codex_via_browser("user@example.com", "pw", return_result=True)

    assert result == {"ok": True}
    assert events[0] == "ensure"
    assert events[1] == ("direct", "user@example.com", "pw", None, True, None)


def test_select_target_team_workspace_prefers_account_id():
    session_data = {
        "workspaces": [
            {"id": "personal-1", "workspace_name": "Personal account", "is_personal": True},
            {"id": "team-1", "workspace_name": "Feiqi", "plan_type": "team"},
        ]
    }

    workspace = codex_auth._select_target_team_workspace(
        session_data,
        workspace_name="Feiqi",
        account_id="team-1",
    )

    assert workspace["id"] == "team-1"


def test_continue_oauth_via_api_posts_workspace_select_and_follows_continue_url(monkeypatch):
    calls = []
    follow_calls = []

    cookie_value = _encode_oauth_session(
        {
            "workspaces": [
                {"id": "team-1", "workspace_name": "Feiqi", "plan_type": "team"},
                {"id": "personal-1", "workspace_name": "Personal account", "is_personal": True},
            ]
        }
    )
    context = _FakeContext([{"name": "oai-client-auth-session", "value": cookie_value}])
    page = type("Page", (), {"url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"})()

    class FakeSession:
        def post(self, url, headers=None, json=None, allow_redirects=False, timeout=0):
            calls.append((url, headers or {}, json, allow_redirects, timeout))
            return _FakeResponse(200, json_data={"continue_url": "/oauth/resume"})

    monkeypatch.setattr(requests, "Session", lambda: FakeSession())
    monkeypatch.setattr(
        codex_auth,
        "_follow_oauth_redirect_chain",
        lambda _context, start_url, *, referer=None, max_hops=8: follow_calls.append((start_url, referer, max_hops))
        or "code-123",
    )

    code = codex_auth._continue_oauth_via_api(
        page,
        context,
        workspace_name="Feiqi",
        account_id="team-1",
    )

    assert code == "code-123"
    assert calls == [
        (
            "https://auth.openai.com/api/accounts/workspace/select",
            calls[0][1],
            {"workspace_id": "team-1"},
            False,
            20,
        )
    ]
    assert calls[0][1]["Referer"] == "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
    assert follow_calls == [
        (
            "https://auth.openai.com/oauth/resume",
            "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            8,
        )
    ]


def test_capture_auth_code_from_page_reads_callback_url_from_html():
    page = type(
        "Page",
        (),
        {
            "url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            "frames": [],
            "content": lambda self: '<a href="http://localhost:1455/auth/callback?code=html-code&state=1">ok</a>',
        },
    )()

    assert codex_auth._capture_auth_code_from_page(page) == "html-code"
