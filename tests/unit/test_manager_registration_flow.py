import sys
import types

from autoteam import manager


class _FakeMailClient:
    provider_name = "cloudmail"
    service_id = "svc-1"

    def __init__(self, emails):
        self._emails = list(emails)
        self.deleted = []

    def create_temp_email(self):
        return self._emails.pop(0)

    def delete_account(self, account_id):
        self.deleted.append(account_id)


def test_create_account_direct_discards_failed_mailbox_and_uses_next_email(monkeypatch):
    created = []
    updates = []
    auth_files = []
    resets = []

    class FakeFlow:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.registered = []
            created.append(kwargs)

        def start(self):
            return None

        def run_register(self, email, password, name, birthdate):
            self.registered.append(email)
            if email == "first@example.com":
                raise RuntimeError("register failed")

        def oauth_team(self, email, password):
            return {"ok": True, "bundle": {"email": email, "plan_type": "team"}}

        def close(self):
            return None

    fake_module = types.ModuleType("autoteam.robust_flow")
    fake_module.RobustFlow = FakeFlow
    monkeypatch.setitem(sys.modules, "autoteam.robust_flow", fake_module)
    monkeypatch.setattr(
        manager,
        "_is_email_in_team",
        lambda email: email == "second@example.com",
    )
    monkeypatch.setattr(manager, "add_account", lambda *args, **kwargs: updates.append(("add", args, kwargs)))
    monkeypatch.setattr(manager, "save_auth_file", lambda bundle: f"/tmp/{bundle['email']}.json")
    monkeypatch.setattr(
        manager,
        "update_account",
        lambda email, **kwargs: updates.append(("update", email, kwargs)),
    )
    monkeypatch.setattr(manager, "_auth_repair_reset", lambda email: resets.append(email))
    monkeypatch.setattr(manager.time, "time", lambda: 1234567890)

    mail_client = _FakeMailClient(
        [
            ("mail-1", "first@example.com"),
            ("mail-2", "second@example.com"),
        ]
    )

    result = manager.create_account_direct(mail_client)

    assert result == "second@example.com"
    assert mail_client.deleted == ["mail-1"]
    assert updates
    assert auth_files == []
    assert resets == ["second@example.com"]
    assert len(created) == 2


def test_record_auth_repair_failure_disables_account_on_account_deactivated(monkeypatch):
    updates = []
    monkeypatch.setattr(
        manager,
        "load_accounts",
        lambda: [{"email": "user@example.com", "status": "auth_pending", "auth_retry_count": 0}],
    )
    monkeypatch.setattr(manager, "update_account", lambda email, **kwargs: updates.append((email, kwargs)))
    monkeypatch.setattr(manager.time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(manager, "_is_email_in_team", lambda _email: True)

    state = manager._record_auth_repair_failure("user@example.com", "account_deactivated", "账号已被停用或删除")

    assert state["auth_last_error"] == "account_deactivated"
    assert any(kwargs.get("disabled") is True for _, kwargs in updates)
