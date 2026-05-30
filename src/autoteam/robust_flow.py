from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
import secrets
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from playwright.sync_api import sync_playwright

from autoteam.admin_state import get_chatgpt_account_id, get_chatgpt_workspace_name
from autoteam.config import (
    EMAIL_POLL_INTERVAL,
    EMAIL_POLL_TIMEOUT,
    clear_last_easyproxy_assignment,
    get_playwright_launch_options,
    mark_last_easyproxy_assignment_bad,
)
from autoteam.signup_profile import SignupProfile, generate_signup_profile

logger = logging.getLogger(__name__)

BASE = "https://chatgpt.com"
AUTH = "https://auth.openai.com"
OAUTH_ISSUER = AUTH
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
OAUTH_TOKEN_URL = f"{AUTH}/oauth/token"

PLAYWRIGHT_TIMEOUT_MS = 45000
SENTINEL_BASE = "https://sentinel.openai.com"
SENTINEL_SDK_VERSION = "20260219f9f6"
SENTINEL_FRAME_URL = f"{SENTINEL_BASE}/backend-api/sentinel/frame.html?sv={SENTINEL_SDK_VERSION}"

_CHROME_PROFILES = [
    {
        "major": 147,
        "build": 0,
        "patch": (0, 0),
        "ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    },
]

_TEAM_PLAN_TYPES = {"team", "business", "enterprise"}


class FlowError(Exception):
    pass


def _random_chrome_version() -> tuple[str, str, str]:
    profile = random.choice(_CHROME_PROFILES)
    patch = random.randint(*profile["patch"])
    full = f"{profile['major']}.0.{profile['build']}.{patch}"
    ua = (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full} Safari/537.36"
    )
    return full, ua, profile["ua"]


def _extract_code(url: str) -> str | None:
    try:
        return parse_qs(urlparse(url).query).get("code", [None])[0]
    except Exception:
        return None


def _generate_pkce() -> tuple[str, str]:
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _trace_headers() -> dict[str, str]:
    trace_id = random.randint(10**17, 10**18 - 1)
    parent_id = random.randint(10**17, 10**18 - 1)
    return {
        "traceparent": f"00-{uuid.uuid4().hex}-{format(parent_id, '016x')}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": str(trace_id),
        "x-datadog-parent-id": str(parent_id),
    }


def _extract_direct_token(raw: Any) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("token", "sentinel", "sentinel_token", "sentinelToken", "value", "result"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_triplet(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    proof = str(raw.get("p") or raw.get("pow") or raw.get("proof") or "").strip()
    turnstile = str(raw.get("t") or raw.get("turnstile") or raw.get("turnstile_token") or "").strip()
    challenge = str(raw.get("c") or raw.get("challenge") or raw.get("challenge_token") or raw.get("token") or "").strip()
    if not proof or not challenge:
        return None
    return {"p": proof, "t": turnstile, "c": challenge}


def _parse_jwt_payload(token: str) -> dict[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _workspace_looks_personal(workspace: Any) -> bool:
    if not isinstance(workspace, dict):
        return False
    if workspace.get("is_personal") is True:
        return True
    plan_type = str(workspace.get("plan_type") or "").strip().lower()
    structure = str(workspace.get("structure") or "").strip().lower()
    label = " ".join(
        str(workspace.get(key) or "").strip().lower()
        for key in ("workspace_name", "name", "label", "display_name")
    ).strip()
    return (
        plan_type == "free"
        or structure.startswith("personal")
        or "personal account" in label
        or label == "personal"
    )


class RobustFlow:
    def __init__(
        self,
        *,
        mail_client=None,
        otp_timeout: int = EMAIL_POLL_TIMEOUT,
        workspace_name: str = "",
        account_id: str = "",
        mailbox_id: int | str | None = None,
        tag: str = "Codex",
        signup_profile: SignupProfile | None = None,
    ):
        self.mail_client = mail_client
        self.otp_timeout = max(30, int(otp_timeout or EMAIL_POLL_TIMEOUT))
        self.workspace_name = str(workspace_name or get_chatgpt_workspace_name() or "").strip()
        self.account_id = str(account_id or get_chatgpt_account_id() or "").strip()
        self.mailbox_id = mailbox_id
        self.tag = str(tag or "Codex").strip() or "Codex"
        self.signup_profile = signup_profile or generate_signup_profile()

        self.device_id = str(uuid.uuid4())
        self.auth_session_logging_id = str(uuid.uuid4())
        self.chrome_full, self.ua, self.sec_ch_ua = _random_chrome_version()
        self.accept_language = random.choice(
            ["en-US,en;q=0.9", "en-US,en;q=0.9,zh-CN;q=0.8", "en,en-US;q=0.9"]
        )

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.sentinel_page = None
        self.api = None
        self.launch_proxy = None

        self.callback_url = ""
        self.captured_code: str | None = None
        self.captured_code_url: str = ""
        self.last_oauth_continue_url = ""
        self.last_oauth_continue_source = ""
        self.last_oauth_continue_at = 0.0
        self.last_otp_url = ""
        self.oauth_fail_reason = ""

        self._sentinel_bundle_loaded = False
        self._sentinel_flow_tokens: dict[str, str] = {}
        self._sentinel_flow_so_tokens: dict[str, str] = {}

    def p(self, message: str, level: str = "info") -> None:
        line = f"[{self.tag}] {message}"
        getattr(logger, level if level in {"debug", "info", "warning", "error"} else "info")(line)

    def set_mail_context(self, mailbox_id: int | str | None) -> None:
        self.mailbox_id = mailbox_id

    def start(self) -> None:
        if self.playwright:
            return

        launch_options = get_playwright_launch_options()
        self.launch_proxy = dict(launch_options.get("proxy") or {}) if isinstance(launch_options, dict) else {}

        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(**launch_options)
            clear_last_easyproxy_assignment()
        except Exception as exc:
            mark_last_easyproxy_assignment_bad(str(exc))
            self.close()
            raise

        try:
            self.context = self.browser.new_context(
                user_agent=self.ua,
                locale="en-US",
                viewport={"width": 1600, "height": 980},
                ignore_https_errors=True,
            )
            self.context.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)
            self._prime_cookies()
            self.page = self.context.new_page()
            self.sentinel_page = self.context.new_page()
            self._hook_code_capture(self.page)
            self._hook_code_capture(self.sentinel_page)
            try:
                self.sentinel_page.goto(
                    SENTINEL_FRAME_URL,
                    wait_until="domcontentloaded",
                    timeout=PLAYWRIGHT_TIMEOUT_MS,
                )
                self.sentinel_page.wait_for_timeout(1500)
            except Exception:
                pass
            self._sync_api_from_browser()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for name in ("api", "sentinel_page", "page", "context", "browser"):
            obj = getattr(self, name, None)
            if not obj:
                continue
            try:
                if name == "api":
                    obj.dispose()
                else:
                    obj.close()
            except Exception:
                pass
            setattr(self, name, None)
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        self.playwright = None

    def _prime_cookies(self) -> None:
        cookies = []
        for raw in (BASE, AUTH, OAUTH_ISSUER):
            host = urlparse(raw).hostname or ""
            for domain in (host, f".{host}"):
                cookies.append(
                    {
                        "name": "oai-did",
                        "value": self.device_id,
                        "domain": domain,
                        "path": "/",
                        "httpOnly": False,
                        "secure": True,
                        "sameSite": "Lax",
                    }
                )

        if self.account_id:
            cookies.extend(
                [
                    {
                        "name": "_account",
                        "value": self.account_id,
                        "domain": "chatgpt.com",
                        "path": "/",
                        "secure": True,
                        "sameSite": "Lax",
                    },
                    {
                        "name": "_account",
                        "value": self.account_id,
                        "domain": "auth.openai.com",
                        "path": "/",
                        "secure": True,
                        "sameSite": "Lax",
                    },
                ]
            )

        self.context.add_cookies(cookies)

    def _build_session_cookies(self, session_token: str, domain: str) -> list[dict[str, Any]]:
        if len(session_token) > 3800:
            return [
                {
                    "name": "__Secure-next-auth.session-token.0",
                    "value": session_token[:3800],
                    "domain": domain,
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "__Secure-next-auth.session-token.1",
                    "value": session_token[3800:],
                    "domain": domain,
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                },
            ]
        return [
            {
                "name": "__Secure-next-auth.session-token",
                "value": session_token,
                "domain": domain,
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ]

    def _inject_session(self, session_token: str) -> None:
        cookies: list[dict[str, Any]] = []
        for domain in ("chatgpt.com", "auth.openai.com"):
            cookies.extend(self._build_session_cookies(session_token, domain))
        if self.account_id:
            cookies.extend(
                [
                    {
                        "name": "_account",
                        "value": self.account_id,
                        "domain": "chatgpt.com",
                        "path": "/",
                        "secure": True,
                        "sameSite": "Lax",
                    },
                    {
                        "name": "_account",
                        "value": self.account_id,
                        "domain": "auth.openai.com",
                        "path": "/",
                        "secure": True,
                        "sameSite": "Lax",
                    },
                ]
            )
        self.context.add_cookies(cookies)
        self._sync_api_from_browser()

    def _hook_code_capture(self, page) -> None:
        def remember(url: str) -> None:
            code = _extract_code(url)
            if code:
                self.captured_code = code
                self.captured_code_url = url

        def remember_auth_payload(resp) -> None:
            try:
                url = str(resp.url or "").strip()
                if OAUTH_ISSUER not in url or "/api/accounts/" not in url:
                    return
                data = resp.json()
            except Exception:
                return
            self._remember_oauth_continue(url, data)

        def on_response(resp) -> None:
            remember(resp.url)
            remember_auth_payload(resp)

        def on_request_finished(req) -> None:
            try:
                resp = req.response()
                if resp:
                    remember(resp.url)
            except Exception:
                pass

        page.on("response", on_response)
        page.on("requestfinished", on_request_finished)

    def _sync_api_from_browser(self) -> None:
        if self.api:
            try:
                self.api.dispose()
            except Exception:
                pass

        kwargs: dict[str, Any] = {
            "storage_state": self.context.storage_state(),
            "ignore_https_errors": True,
            "user_agent": self.ua,
            "timeout": PLAYWRIGHT_TIMEOUT_MS,
            "fail_on_status_code": False,
            "extra_http_headers": {
                "Accept-Language": self.accept_language,
                "sec-ch-ua": self.sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        }
        if self.launch_proxy:
            kwargs["proxy"] = self.launch_proxy
        self.api = self.playwright.request.new_context(**kwargs)

    def _sync_browser_from_api(self) -> None:
        try:
            cookies = self.api.storage_state().get("cookies") or []
            if cookies:
                self.context.add_cookies(cookies)
        except Exception:
            pass

    def _std(self) -> dict[str, str]:
        return {
            "User-Agent": self.ua,
            "Accept-Language": self.accept_language,
            "sec-ch-ua": self.sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    def _same_origin_fetch_headers(self) -> dict[str, str]:
        return {
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def _json_headers(self, referer: str, origin: str) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": referer,
            "Origin": origin,
            "oai-device-id": self.device_id,
        }
        headers.update(self._std())
        headers.update(self._same_origin_fetch_headers())
        headers.update(_trace_headers())
        return headers

    def _api_call(self, method: str, url: str, step: str = "", max_redirects: int = 20, **kwargs) -> dict[str, Any]:
        self._sync_api_from_browser()
        kwargs.setdefault("timeout", PLAYWRIGHT_TIMEOUT_MS)
        kwargs.setdefault("max_redirects", max_redirects)
        if "json_body" in kwargs:
            kwargs["data"] = json.dumps(kwargs.pop("json_body"))
        fn = getattr(self.api, method.lower())
        resp = fn(url, **kwargs)
        text = ""
        data: Any = None
        try:
            text = resp.text()
        except Exception:
            pass
        try:
            data = resp.json()
        except Exception:
            data = None
        result = {
            "status": int(resp.status),
            "url": str(resp.url),
            "text": text,
            "json": data,
            "headers": {str(k).lower(): str(v) for k, v in dict(resp.headers or {}).items()},
        }
        try:
            resp.dispose()
        except Exception:
            pass
        self._sync_browser_from_api()
        if step:
            logger.debug("[%s] %s %s -> %s", self.tag, method.upper(), url, result["status"])
        return result

    def goto(self, url: str, referer: str | None = None) -> str:
        self.captured_code = None
        self.captured_code_url = ""
        try:
            self.page.goto(url, referer=referer, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
        finally:
            self._sync_api_from_browser()
        return self.page.url

    def _abs_auth_url(self, url: str) -> str:
        raw = str(url or "").strip()
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if raw.startswith("/"):
            return f"{AUTH}{raw}"
        return raw

    def _clear_oauth_continue(self) -> None:
        self.last_oauth_continue_url = ""
        self.last_oauth_continue_source = ""
        self.last_oauth_continue_at = 0.0

    def _remember_oauth_continue(self, source_url: str, data: Any) -> None:
        if not isinstance(data, dict):
            return
        next_url = str(data.get("continue_url") or data.get("url") or data.get("redirect_url") or "").strip()
        if not next_url:
            return
        target = self._abs_auth_url(next_url)
        if not target:
            return
        self.last_oauth_continue_url = target
        self.last_oauth_continue_source = str(source_url or "").strip()
        self.last_oauth_continue_at = time.time()

    def _consume_oauth_continue(self, max_age: float = 12.0) -> tuple[str, str]:
        target = self._abs_auth_url(self.last_oauth_continue_url)
        age = time.time() - float(self.last_oauth_continue_at or 0.0)
        source = self.last_oauth_continue_source
        self._clear_oauth_continue()
        if not target or age > float(max_age or 0):
            return "", ""
        return target, source

    def _follow_browser_continue(self, referer: str | None = None, max_age: float = 12.0) -> str | None:
        target, _source = self._consume_oauth_continue(max_age=max_age)
        if not target:
            return None
        return _extract_code(target) or self._follow_for_code(target, referer=referer)[0] or self._allow_redirect_code(
            target,
            referer=referer,
        )

    def _page_excerpt(self, limit: int = 300) -> str:
        try:
            text = self.page.locator("body").inner_text(timeout=1500)
        except Exception:
            return ""
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        return text[:limit]

    def _auth_cookie_names(self) -> list[str]:
        names = []
        for cookie in self.context.cookies([AUTH, OAUTH_ISSUER]):
            name = str(cookie.get("name") or "").strip()
            domain = str(cookie.get("domain") or "").lower().strip()
            if name and ("auth.openai.com" in domain or domain.endswith(".openai.com")):
                names.append(name)
        return names

    def _wait_otp(
        self,
        email: str,
        *,
        initial_delay: float = 0.0,
        ignore_email_ids: set[str] | None = None,
        ignore_codes: set[str] | None = None,
    ) -> str:
        if not self.mail_client:
            raise FlowError("mail client is required for OTP")
        if initial_delay > 0:
            time.sleep(initial_delay)

        if hasattr(self.mail_client, "wait_for_otp"):
            try:
                code = self.mail_client.wait_for_otp(
                    email,
                    timeout=self.otp_timeout,
                    sender_keyword="openai",
                    account_id=self.mailbox_id,
                    ignore_email_ids=ignore_email_ids,
                    ignore_codes=ignore_codes,
                )
            except TypeError:
                code = self.mail_client.wait_for_otp(
                    email,
                    timeout=self.otp_timeout,
                    sender_keyword="openai",
                    account_id=self.mailbox_id,
                )
            if isinstance(code, str) and re.fullmatch(r"\d{6}", code):
                return code

        deadline = time.time() + self.otp_timeout
        ignore_email_ids = set(ignore_email_ids or ())
        ignore_codes = set(ignore_codes or ())
        while time.time() < deadline:
            emails = self.mail_client.search_emails_by_recipient(email, size=10, account_id=self.mailbox_id)
            for message in emails or []:
                message_id = str(message.get("emailId") or message.get("id") or "").strip()
                if message_id and message_id in ignore_email_ids:
                    continue
                code = self.mail_client.extract_verification_code(message)
                if not code or code in ignore_codes:
                    continue
                if message_id:
                    ignore_email_ids.add(message_id)
                return code
            time.sleep(max(1, int(EMAIL_POLL_INTERVAL)))
        raise TimeoutError(f"otp timeout for {email}")

    def _snapshot_recent_email_ids(self, email: str, *, size: int = 10) -> set[str]:
        if not self.mail_client:
            return set()
        try:
            emails = self.mail_client.search_emails_by_recipient(email, size=size, account_id=self.mailbox_id)
        except Exception:
            return set()
        out: set[str] = set()
        for message in emails or []:
            message_id = message.get("emailId") or message.get("id")
            if message_id is None:
                continue
            text = str(message_id).strip()
            if text:
                out.add(text)
        return out

    def _classify_failure(self, url: str, body_excerpt: str = "") -> tuple[str, str, bool]:
        current_url = str(url or "").lower()
        body = str(body_excerpt or "").lower()
        if "add-phone" in current_url:
            return "add_phone", "需要手机号验证", False
        if "choose-an-account" in current_url:
            return "choose_account_selection", "卡在账号选择页", True
        if "verify you are human" in body or "captcha" in body:
            return "human_verification", "命中人机验证", False
        if (
            "account_deactivated" in body
            or "account deactivated" in body
            or "deleted or deactivated" in body
            or "you do not have an account because it has been deleted or deactivated" in body
        ):
            return "account_deactivated", "账号已被停用或删除", False
        if "unable to load site" in body or "try again later" in body or "status page" in body:
            return "site_unavailable", "站点暂时不可用或代理异常", True
        if "email-verification" in current_url:
            return "email_verification", "卡在邮箱验证码页", True
        if "workspace" in current_url or "consent" in current_url:
            return "workspace_selection", "卡在 workspace/consent 页面", True
        if "/auth/login" in current_url or "log-in" in current_url:
            return "login_state_lost", "登录态丢失或回到了登录页", True
        return "auth_code_missing", f"未获取到 auth code（停留在 {url or 'unknown'}）", True

    def _build_failure_result(self, url: str, body_excerpt: str = "") -> dict[str, Any]:
        error_type, error_detail, retryable = self._classify_failure(url, body_excerpt)
        return {
            "ok": False,
            "bundle": None,
            "error_type": error_type,
            "error_detail": error_detail,
            "retryable": retryable,
            "current_url": url,
            "body_excerpt": body_excerpt,
        }

    def _inspect_auth_page(self, url: str | None = None, referer: str | None = None) -> dict[str, Any]:
        current = self._abs_auth_url(url or getattr(self.page, "url", ""))
        if current:
            try:
                self.goto(current, referer=referer)
            except Exception:
                pass
        return self._build_failure_result(getattr(self.page, "url", "") or current, self._page_excerpt())

    def _client_auth_session_dump(self, referer: str | None = None) -> dict[str, Any]:
        result = self._api_call(
            "get",
            f"{OAUTH_ISSUER}/api/accounts/client_auth_session_dump",
            step="session-dump",
            headers={
                "Accept": "application/json",
                "Referer": referer or getattr(self.page, "url", "") or f"{OAUTH_ISSUER}/log-in",
                **self._same_origin_fetch_headers(),
                **self._std(),
            },
            max_redirects=0,
        )
        return result.get("json") or {}

    def _request_otp_resend(self, referer: str | None = None, *, why: str = "manual") -> int:
        result = self._api_call(
            "get",
            f"{AUTH}/api/accounts/email-otp/send",
            step=f"otp-send:{why}",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": referer or getattr(self.page, "url", "") or f"{AUTH}/email-verification",
                "Upgrade-Insecure-Requests": "1",
                **self._std(),
            },
        )
        self.last_otp_url = self._abs_auth_url(result["url"]) or self.last_otp_url
        return result["status"]

    def _ensure_sentinel_bundle(self) -> None:
        if self._sentinel_bundle_loaded:
            return
        self._sentinel_bundle_loaded = True
        try:
            result = self.sentinel_page.evaluate(
                """async (flows) => {
                    const out = {};
                    const sdk = window.SentinelSDK || window.sentinelSDK || window.__SentinelSDK || (window.openai && window.openai.SentinelSDK);
                    if (!sdk) return out;
                    for (const flow of flows) {
                        let tokenRaw = null, soRaw = null;
                        try {
                            if (typeof sdk.init === "function") await sdk.init(flow);
                            tokenRaw = await sdk.token(flow);
                        } catch (e) {}
                        try {
                            if (typeof sdk.sessionObserverToken === "function") {
                                soRaw = await sdk.sessionObserverToken(flow);
                            }
                        } catch (e) {}
                        out[flow] = { tokenRaw, soRaw };
                    }
                    return out;
                }""",
                [
                    "authorize_continue",
                    "username_password_create",
                    "password_verify",
                    "oauth_create_account",
                    "email_otp_verification",
                ],
            )
        except Exception:
            return
        if not isinstance(result, dict):
            return
        for flow, data in result.items():
            if not isinstance(data, dict):
                continue
            token = _extract_direct_token(data.get("tokenRaw"))
            if not token:
                triplet = _extract_triplet(data.get("tokenRaw"))
                if triplet and triplet.get("p") and triplet.get("c"):
                    triplet["id"] = self.device_id
                    triplet["flow"] = flow
                    token = json.dumps(triplet, separators=(",", ":"))
            so_token = _extract_direct_token(data.get("soRaw")) or ""
            if token:
                self._sentinel_flow_tokens[str(flow)] = token
            if so_token:
                self._sentinel_flow_so_tokens[str(flow)] = so_token

    def _resolve_sentinel_token(self, flow: str, fallback_flow: str | None = None) -> str | None:
        self._ensure_sentinel_bundle()
        flow = str(flow or "").strip()
        fallback_flow = str(fallback_flow or "").strip()
        token = self._sentinel_flow_tokens.get(flow) or (
            self._sentinel_flow_tokens.get(fallback_flow) if fallback_flow else None
        )
        if token:
            return token
        try:
            result = self.sentinel_page.evaluate(
                """async ({flow,deviceId}) => {
                    const sdk = window.SentinelSDK || window.sentinelSDK || window.__SentinelSDK || (window.openai && window.openai.SentinelSDK);
                    if (!sdk || typeof sdk.token !== 'function') return null;
                    const lang = navigator.language || 'en-US';
                    const caps = JSON.stringify({is_passkey_supported:false,is_platform_authenticator_available:false,is_conditional_mediation_available:false});
                    const tries = [
                        () => sdk.token({flow,id:deviceId}),
                        () => sdk.token({flow,id:deviceId,'data-build':lang}),
                        () => sdk.token({flow,id:deviceId,dataBuild:lang}),
                        () => sdk.token({flow,id:deviceId,'data-build':lang,'ext-passkey-client-capabilities':caps}),
                        () => sdk.token(flow),
                        () => sdk.token({flow}),
                        () => sdk.token(),
                    ];
                    for (const fn of tries) { try { return await fn(); } catch(e) {} }
                    return null;
                }""",
                {"flow": flow, "deviceId": self.device_id},
            )
        except Exception:
            return None
        direct = _extract_direct_token(result)
        if direct:
            return direct
        triplet = _extract_triplet(result)
        if triplet and triplet.get("p") and triplet.get("c"):
            triplet["id"] = self.device_id
            triplet["flow"] = flow
            return json.dumps(triplet, separators=(",", ":"))
        return None

    def _resolve_sentinel_so_token(self, flow: str) -> str:
        self._ensure_sentinel_bundle()
        token = self._sentinel_flow_so_tokens.get(str(flow or "").strip())
        if token:
            return token
        try:
            return (
                self.sentinel_page.evaluate(
                    """async (flow) => {
                        const sdk = window.SentinelSDK || window.sentinelSDK || window.__SentinelSDK || (window.openai && window.openai.SentinelSDK);
                        if (!sdk || typeof sdk.sessionObserverToken !== 'function') return '';
                        try { return await sdk.sessionObserverToken(flow); } catch(e) { return ''; }
                    }""",
                    flow,
                )
                or ""
            )
        except Exception:
            return ""

    def _visit_homepage(self) -> None:
        self.goto(f"{BASE}/")

    def _get_csrf(self) -> str:
        result = self._api_call(
            "get",
            f"{BASE}/api/auth/csrf",
            step="csrf",
            headers={"Accept": "application/json", "Referer": f"{BASE}/", **self._std()},
        )
        token = str((result["json"] or {}).get("csrfToken") or "").strip()
        if not token:
            raise FlowError("missing csrfToken")
        return token

    def _signin(self, email: str, csrf: str) -> str:
        result = self._api_call(
            "post",
            f"{BASE}/api/auth/signin/openai",
            step="signin",
            params={
                "prompt": "login",
                "ext-oai-did": self.device_id,
                "auth_session_logging_id": self.auth_session_logging_id,
                "screen_hint": "login_or_signup",
                "login_hint": email,
            },
            form={"callbackUrl": f"{BASE}/", "csrfToken": csrf, "json": "true"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Referer": f"{BASE}/",
                "Origin": BASE,
                **self._std(),
            },
        )
        url = str((result["json"] or {}).get("url") or "").strip()
        if not url:
            raise FlowError("missing authorize url")
        return url

    def _authorize(self, url: str) -> str:
        return self.goto(url, referer=f"{BASE}/")

    def _register(self, email: str, password: str) -> tuple[int, dict[str, Any]]:
        headers = self._json_headers(f"{AUTH}/create-account/password", AUTH)
        token = self._resolve_sentinel_token("username_password_create")
        if token:
            headers["openai-sentinel-token"] = token
        result = self._api_call(
            "post",
            f"{AUTH}/api/accounts/user/register",
            step="register",
            params={
                "ext-passkey-client-capabilities": json.dumps(
                    {
                        "is_passkey_supported": False,
                        "is_platform_authenticator_available": False,
                        "is_conditional_mediation_available": False,
                    },
                    separators=(",", ":"),
                )
            },
            json_body={"username": email, "password": password},
            headers=headers,
        )
        return result["status"], (result["json"] or {"text": (result["text"] or "")[:300]})

    def _send_otp(self) -> int:
        return self._request_otp_resend(referer=f"{AUTH}/create-account/password", why="register")

    def _validate_register_otp(self, code: str) -> tuple[int, dict[str, Any]]:
        headers = self._json_headers(f"{AUTH}/email-verification", AUTH)
        token = self._resolve_sentinel_token("email_otp_verification")
        if token:
            headers["openai-sentinel-token"] = token
        result = self._api_call(
            "post",
            f"{AUTH}/api/accounts/email-otp/validate",
            step="register-otp",
            json_body={"code": code},
            headers=headers,
        )
        return result["status"], (result["json"] or {"text": (result["text"] or "")[:300]})

    def _create_account(self, name: str, birthdate: str) -> tuple[int, dict[str, Any]]:
        headers = self._json_headers(f"{AUTH}/about-you", AUTH)
        token = self._resolve_sentinel_token("oauth_create_account", "create_account")
        if token:
            headers["openai-sentinel-token"] = token
        so_token = self._resolve_sentinel_so_token("oauth_create_account")
        if so_token:
            headers["openai-sentinel-so-token"] = so_token
        result = self._api_call(
            "post",
            f"{AUTH}/api/accounts/create_account",
            step="create-account",
            json_body={"name": name, "birthdate": birthdate},
            headers=headers,
        )
        data = result["json"] or {"text": (result["text"] or "")[:300]}
        if isinstance(data, dict):
            self.callback_url = data.get("continue_url") or data.get("url") or data.get("redirect_url") or ""
        return result["status"], data

    def _consume_callback(self, url: str | None = None) -> None:
        target = url or self.callback_url
        if not target:
            return
        try:
            self.goto(target)
        except Exception:
            pass

    def run_register(self, email: str, password: str, name: str, birthdate: str) -> None:
        self.p(f"Start register: {email}")
        self._visit_homepage()
        csrf = self._get_csrf()
        auth_url = self._signin(email, csrf)
        final = self._authorize(auth_url)
        path = urlparse(final).path.lower()

        need_otp = False
        if "create-account/password" in path:
            status, data = self._register(email, password)
            if status != 200:
                raise FlowError(f"register failed: {data}")
            self._send_otp()
            need_otp = True
        elif "email-verification" in path or "email-otp" in path:
            need_otp = True
        elif "about-you" in path:
            status, data = self._create_account(name, birthdate)
            if status != 200:
                raise FlowError(f"create_account failed: {data}")
            self._consume_callback()
            return
        else:
            status, data = self._register(email, password)
            if status != 200:
                raise FlowError(f"register fallback failed: {data}")
            self._send_otp()
            need_otp = True

        if need_otp:
            self.last_otp_url = self.last_otp_url or f"{AUTH}/email-verification"
            last: dict[str, Any] = {}
            for _ in range(3):
                code = self._wait_otp(email)
                status, data = self._validate_register_otp(code)
                last = data
                if status == 200:
                    break
                self._request_otp_resend(why=f"register-otp-{status}")
                time.sleep(2)
            else:
                raise FlowError(f"register otp failed: {last}")

        status, data = self._create_account(name, birthdate)
        if status != 200:
            raise FlowError(f"create_account failed: {data}")
        self._consume_callback()

    def _decode_oauth_session(self) -> dict[str, Any] | None:
        for cookie in self.context.cookies([AUTH, OAUTH_ISSUER]):
            name = str(cookie.get("name") or "")
            if "oai-client-auth-session" not in name:
                continue
            raw = str(cookie.get("value") or "").strip()
            if not raw:
                continue
            for value in (raw, unquote(raw)):
                try:
                    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    part = value.split(".")[0] if "." in value else value
                    part += "=" * ((4 - len(part) % 4) % 4)
                    data = json.loads(base64.urlsafe_b64decode(part).decode())
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
        return None

    def _follow_for_code(self, start_url: str, referer: str | None = None, max_hops: int = 16) -> tuple[str | None, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            **self._std(),
        }
        if referer:
            headers["Referer"] = referer
        current = start_url
        last = start_url
        for _ in range(max_hops):
            result = self._api_call("get", current, step="follow", headers=headers, max_redirects=0)
            last = result["url"] or current
            code = _extract_code(last)
            if code:
                return code, last
            if result["status"] in (301, 302, 303, 307, 308):
                location = str(result["headers"].get("location") or "").strip()
                if not location:
                    return None, last
                if location.startswith("/"):
                    location = f"{OAUTH_ISSUER}{location}"
                code = _extract_code(location)
                if code:
                    return code, location
                current = location
                headers["Referer"] = last
                continue
            return None, last
        return None, last

    def _allow_redirect_code(self, url: str, referer: str | None = None) -> str | None:
        try:
            final = self.goto(url, referer=referer)
        except Exception as exc:
            match = re.search(r"(https?://localhost[^\s'\"]+)", str(exc))
            final = match.group(1) if match else (self.captured_code_url or "")
        return self.captured_code or _extract_code(final or "")

    def _select_target_team_workspace(self, session_data: dict[str, Any] | None) -> dict[str, Any] | None:
        workspaces = session_data.get("workspaces") if isinstance(session_data, dict) else None
        if not isinstance(workspaces, list):
            return None

        preferred_id = str(self.account_id or "").strip().lower()
        preferred_name = str(self.workspace_name or "").strip().lower()
        normalized = [item for item in workspaces if isinstance(item, dict) and item.get("id")]
        if not normalized:
            return None

        if preferred_id:
            for workspace in normalized:
                if str(workspace.get("id") or "").strip().lower() == preferred_id:
                    return workspace

        if preferred_name:
            for workspace in normalized:
                for key in ("workspace_name", "name", "label", "display_name"):
                    label = str(workspace.get(key) or "").strip().lower()
                    if label and label == preferred_name:
                        return workspace

        for workspace in normalized:
            if not _workspace_looks_personal(workspace):
                return workspace

        return normalized[0]

    def _continue_team_oauth_via_api(self, consent_url: str) -> str | None:
        session = self._decode_oauth_session()
        workspace = self._select_target_team_workspace(session)
        if not workspace:
            return None

        def do_post(url: str, payload: dict[str, Any], *, referer: str) -> dict[str, Any]:
            return self._api_call(
                "post",
                url,
                step="consent-api",
                json_body=payload,
                headers=self._json_headers(referer, OAUTH_ISSUER),
                max_redirects=0,
            )

        response = do_post(
            f"{AUTH}/api/accounts/workspace/select",
            {"workspace_id": workspace["id"]},
            referer=consent_url,
        )
        location = self._abs_auth_url(response["headers"].get("location") or "")
        if response["status"] in (301, 302, 303, 307, 308) and location:
            return _extract_code(location) or self._follow_for_code(location, referer=consent_url)[0] or self._allow_redirect_code(
                location,
                referer=consent_url,
            )

        payload = response.get("json") or {}
        if response["status"] != 200:
            return None

        next_url = self._abs_auth_url(payload.get("continue_url") or "")
        orgs = ((payload.get("data") or {}).get("orgs")) if isinstance(payload, dict) else None
        if isinstance(orgs, list) and orgs:
            org = orgs[0] if isinstance(orgs[0], dict) else {}
            org_id = str(org.get("id") or "").strip()
            if org_id:
                org_payload: dict[str, Any] = {"org_id": org_id}
                projects = org.get("projects") or []
                if isinstance(projects, list) and projects:
                    project_id = str((projects[0] or {}).get("id") or "").strip()
                    if project_id:
                        org_payload["project_id"] = project_id
                org_referer = next_url or consent_url
                response = do_post(
                    f"{AUTH}/api/accounts/organization/select",
                    org_payload,
                    referer=org_referer,
                )
                location = self._abs_auth_url(response["headers"].get("location") or "")
                if response["status"] in (301, 302, 303, 307, 308) and location:
                    return _extract_code(location) or self._follow_for_code(location, referer=org_referer)[0] or self._allow_redirect_code(
                        location,
                        referer=org_referer,
                    )
                payload = response.get("json") or {}
                if response["status"] == 200:
                    next_url = self._abs_auth_url(payload.get("continue_url") or "") or next_url

        if not next_url:
            return None
        return self._follow_for_code(next_url, referer=consent_url)[0] or self._allow_redirect_code(
            next_url,
            referer=consent_url,
        )

    def _click_team_workspace_radio(self) -> bool:
        if not self.workspace_name:
            return False
        selectors = [
            f"text=/{re.escape(self.workspace_name)}/i",
            f"label:has-text('{self.workspace_name}')",
            f"[role='radio']:has-text('{self.workspace_name}')",
        ]
        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                if locator.count() < 1 or not locator.is_visible(timeout=500):
                    continue
                locator.click(timeout=3000)
                try:
                    self.page.wait_for_timeout(500)
                except Exception:
                    time.sleep(0.5)
                return True
            except Exception:
                continue
        return False

    def _auto_click_team_consent(self, consent_url: str, referer: str | None = None) -> tuple[bool, str | None]:
        target = self._abs_auth_url(consent_url or getattr(self.page, "url", ""))
        if not target:
            return False, None
        self._clear_oauth_continue()
        try:
            self.goto(target, referer=referer)
        except Exception:
            pass
        code = self.captured_code or _extract_code(self.captured_code_url) or _extract_code(getattr(self.page, "url", ""))
        if code:
            return False, code

        self._click_team_workspace_radio()

        selectors = [
            "button[data-dd-action-name='Continue']",
            "button:has-text('Continue')",
            "button:has-text('Authorize')",
            "button:has-text('Allow')",
            "button:has-text('Accept')",
            "button:has-text('Approve')",
            "button:has-text('Confirm')",
            "[role=button]:has-text('Continue')",
            "[role=button]:has-text('Allow')",
            "[role=button]:has-text('Accept')",
            "button[type='submit']",
            "form button[type='submit']",
            "input[type='submit']",
        ]
        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                if locator.count() < 1 or not locator.is_visible():
                    continue
                locator.click(timeout=5000)
                try:
                    self.page.wait_for_timeout(1500)
                except Exception:
                    time.sleep(1.5)
                self._sync_api_from_browser()
                current = (
                    self._abs_auth_url(getattr(self.page, "url", ""))
                    or self._abs_auth_url(self.captured_code_url)
                    or target
                )
                code = self.captured_code or _extract_code(current) or _extract_code(self.captured_code_url)
                if code:
                    return True, code
                code = self._follow_browser_continue(referer=current, max_age=20.0)
                return True, code
            except Exception as exc:
                match = re.search(r"(https?://localhost[^\s'\"]+)", str(exc))
                if match:
                    code = _extract_code(match.group(1)) or self.captured_code or _extract_code(self.captured_code_url)
                    if code:
                        return True, code
        return False, None

    def _resolve_code_from_consent(self, consent_url: str, referer: str | None = None) -> str | None:
        candidates: list[str] = []
        seen = set()

        def add(url: str) -> None:
            raw = self._abs_auth_url(url)
            if raw and raw not in seen:
                seen.add(raw)
                candidates.append(raw)

        add(consent_url)
        add(getattr(self.page, "url", ""))
        add(self.last_otp_url)
        add(f"{AUTH}/sign-in-with-chatgpt/codex/consent")

        for candidate in candidates:
            code = _extract_code(candidate)
            if code:
                return code

            code = self._allow_redirect_code(candidate, referer=referer)
            if code:
                return code

            code = self._continue_team_oauth_via_api(candidate)
            if code:
                return code

            clicked, code = self._auto_click_team_consent(candidate, referer=referer)
            if code:
                return code

            current = self._abs_auth_url(getattr(self.page, "url", "")) or candidate
            code = self._follow_browser_continue(referer=current, max_age=20.0)
            if code:
                return code

            if clicked:
                current = self._abs_auth_url(getattr(self.page, "url", "")) or current
            code, _ = self._follow_for_code(current, referer=referer)
            if code:
                return code

        return None

    def _oauth_validate_otp(self, code: str) -> dict[str, Any]:
        referer = self._abs_auth_url(self.last_otp_url or getattr(self.page, "url", "")) or f"{OAUTH_ISSUER}/email-verification"
        headers = self._json_headers(referer, OAUTH_ISSUER)
        token = self._resolve_sentinel_token("email_otp_verification", "password_verify")
        if token:
            headers["openai-sentinel-token"] = token
        return self._api_call(
            "post",
            f"{OAUTH_ISSUER}/api/accounts/email-otp/validate",
            step="oauth-otp",
            json_body={"code": code},
            headers=headers,
            max_redirects=0,
        )

    def _exchange_auth_code(self, auth_code: str, code_verifier: str, fallback_email: str | None = None) -> dict[str, Any] | None:
        result = self._api_call(
            "post",
            OAUTH_TOKEN_URL,
            step="oauth-token",
            form={
                "grant_type": "authorization_code",
                "client_id": OAUTH_CLIENT_ID,
                "code": auth_code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", **self._std()},
        )
        if result["status"] != 200:
            return None
        token_data = result["json"] or {}
        id_token = token_data.get("id_token", "")
        claims = _parse_jwt_payload(id_token)
        auth_claims = claims.get("https://api.openai.com/auth", {})
        return {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "id_token": id_token,
            "account_id": auth_claims.get("chatgpt_account_id", ""),
            "email": claims.get("email", fallback_email or ""),
            "plan_type": auth_claims.get("chatgpt_plan_type", "unknown"),
            "expired": time.time() + token_data.get("expires_in", 3600),
        }

    def oauth_team(self, email: str, password: str) -> dict[str, Any]:
        self.oauth_fail_reason = ""
        self.p(f"Start OAuth: {email}")
        self._clear_oauth_continue()
        self._prime_cookies()
        self._sync_api_from_browser()

        code_verifier, code_challenge = _generate_pkce()
        state = secrets.token_urlsafe(24)
        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "prompt": "login",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
        }
        authorize_url = f"{OAUTH_ISSUER}/oauth/authorize?{urlencode(params)}"
        current_auth_referer = f"{OAUTH_ISSUER}/log-in"

        result0 = self._api_call(
            "get",
            authorize_url,
            step="oauth-authorize",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{BASE}/",
                "Upgrade-Insecure-Requests": "1",
                **self._std(),
            },
            max_redirects=20,
        )
        final0 = result0["url"]
        cookie_names = self._auth_cookie_names()
        has_login = ("login_session" in cookie_names) or any(name.startswith("oai-client-auth-session") for name in cookie_names)
        if not has_login:
            retry_result = self._api_call(
                "get",
                f"{OAUTH_ISSUER}/api/oauth/oauth2/auth",
                step="oauth-auth-retry",
                params=params,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": authorize_url,
                    "Upgrade-Insecure-Requests": "1",
                    **self._std(),
                },
                max_redirects=20,
            )
            final0 = retry_result["url"] or final0

        oauth_otp_baseline_ids = self._snapshot_recent_email_ids(email, size=12)

        def do_authorize_continue() -> dict[str, Any]:
            headers = self._json_headers(
                final0 if str(final0).startswith(OAUTH_ISSUER) else f"{OAUTH_ISSUER}/log-in",
                OAUTH_ISSUER,
            )
            token = self._resolve_sentinel_token("authorize_continue")
            if token:
                headers["openai-sentinel-token"] = token
            return self._api_call(
                "post",
                f"{OAUTH_ISSUER}/api/accounts/authorize/continue",
                step="authorize-continue",
                json_body={"username": {"kind": "email", "value": email}},
                headers=headers,
                max_redirects=0,
            )

        response = do_authorize_continue()
        if response["status"] != 200:
            return self._build_failure_result(response["url"] or authorize_url, (response["text"] or "")[:300])

        data = response["json"] or {}
        next_url = str(data.get("continue_url") or "")
        page_type = str(((data.get("page") or {}).get("type")) or "")
        current_auth_referer = self._abs_auth_url(final0) or current_auth_referer
        self._client_auth_session_dump(referer=current_auth_referer)

        if "add_phone" in page_type or "add-phone" in next_url or "add_phone" in next_url:
            return {
                "ok": False,
                "bundle": None,
                "error_type": "add_phone",
                "error_detail": "需要手机号验证",
                "retryable": False,
            }

        need_password = (
            page_type in ("login_password", "password", "log-in/password")
            or "log-in/password" in next_url
            or "/password" in next_url.lower()
        )
        if need_password:
            password_page = self._abs_auth_url(next_url) or f"{OAUTH_ISSUER}/log-in/password"
            headers = self._json_headers(password_page, OAUTH_ISSUER)
            token = self._resolve_sentinel_token("password_verify")
            if token:
                headers["openai-sentinel-token"] = token
            response = self._api_call(
                "post",
                f"{OAUTH_ISSUER}/api/accounts/password/verify",
                step="password-verify",
                json_body={"password": password},
                headers=headers,
                max_redirects=0,
            )

            if response["status"] == 409 and "invalid_state" in (response["text"] or ""):
                self._clear_oauth_continue()
                self._prime_cookies()
                self._sync_api_from_browser()
                self._api_call(
                    "get",
                    authorize_url,
                    step="oauth-authorize-retry",
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": f"{BASE}/",
                        "Upgrade-Insecure-Requests": "1",
                        **self._std(),
                    },
                    max_redirects=20,
                )
                retry_continue = do_authorize_continue()
                if retry_continue["status"] == 200:
                    retry_data = retry_continue["json"] or {}
                    next_url = str(retry_data.get("continue_url") or next_url)
                    page_type = str(((retry_data.get("page") or {}).get("type")) or page_type)
                    self._client_auth_session_dump(referer=current_auth_referer)
                    password_page = self._abs_auth_url(next_url) or password_page
                    headers = self._json_headers(password_page, OAUTH_ISSUER)
                    token = self._resolve_sentinel_token("password_verify")
                    if token:
                        headers["openai-sentinel-token"] = token
                    response = self._api_call(
                        "post",
                        f"{OAUTH_ISSUER}/api/accounts/password/verify",
                        step="password-verify-retry",
                        json_body={"password": password},
                        headers=headers,
                        max_redirects=0,
                    )

            if response["status"] != 200:
                return self._build_failure_result(response["url"] or password_page, (response["text"] or "")[:300])

            data = response["json"] or {}
            next_url = str(data.get("continue_url") or next_url)
            page_type = str(((data.get("page") or {}).get("type")) or page_type)
            current_auth_referer = password_page
            self._client_auth_session_dump(referer=current_auth_referer)

            if "add_phone" in page_type or "add-phone" in next_url or "add_phone" in next_url:
                return {
                    "ok": False,
                    "bundle": None,
                    "error_type": "add_phone",
                    "error_detail": "需要手机号验证",
                    "retryable": False,
                }

        need_otp = page_type == "email_otp_verification" or "email-verification" in next_url or "email-otp" in next_url
        if need_otp:
            self.last_otp_url = self._abs_auth_url(next_url or f"{OAUTH_ISSUER}/email-verification")
            current_auth_referer = self.last_otp_url
            ignore_email_ids = set(oauth_otp_baseline_ids)
            ignore_codes: set[str] = set()
            soft_retry_used = False
            wait_before_fetch = 2.0
            success = False
            for _ in range(3):
                code = self._wait_otp(
                    email,
                    initial_delay=wait_before_fetch,
                    ignore_email_ids=ignore_email_ids,
                    ignore_codes=ignore_codes,
                )
                response = self._oauth_validate_otp(code)
                ignore_codes.add(code)
                ignore_email_ids.update(self._snapshot_recent_email_ids(email, size=12))
                if response["status"] == 401 and not soft_retry_used:
                    soft_retry_used = True
                    continue
                if response["status"] == 200:
                    data = response["json"] or {}
                    next_url = str(data.get("continue_url") or next_url)
                    page_type = str(((data.get("page") or {}).get("type")) or page_type)
                    self._client_auth_session_dump(referer=current_auth_referer)
                    if "add_phone" in page_type or "add-phone" in next_url or "add_phone" in next_url:
                        return {
                            "ok": False,
                            "bundle": None,
                            "error_type": "add_phone",
                            "error_detail": "需要手机号验证",
                            "retryable": False,
                        }
                    success = True
                    break
                self._request_otp_resend(why=f"oauth-otp-{response['status']}")
                time.sleep(2)
            if not success:
                failure = self._inspect_auth_page(self.last_otp_url, referer=current_auth_referer)
                if failure["error_type"] == "account_deactivated":
                    return failure
                failure["error_detail"] = "未获取到 auth code（停留在 https://auth.openai.com/email-verification）"
                failure["retryable"] = True
                return failure

        consent_url = next_url
        if consent_url.startswith("/"):
            consent_url = f"{OAUTH_ISSUER}{consent_url}"
        consent_referer = current_auth_referer or f"{OAUTH_ISSUER}/log-in/password"

        auth_code = _extract_code(consent_url) if consent_url else None
        consent_hint = (
            ("consent" in (consent_url or ""))
            or ("workspace" in (consent_url or ""))
            or ("organization" in (consent_url or ""))
            or ("consent" in page_type)
            or ("organization" in page_type)
        )
        if not auth_code and consent_hint:
            auth_code = self._resolve_code_from_consent(consent_url, referer=consent_referer)
        if not auth_code:
            auth_code = self._resolve_code_from_consent("", referer=consent_referer)
        if not auth_code:
            failure = self._inspect_auth_page(consent_url or next_url or getattr(self.page, "url", ""), referer=consent_referer)
            return failure

        logger.info("[Codex] Captured auth code")
        bundle = self._exchange_auth_code(auth_code, code_verifier, fallback_email=email)
        if not bundle:
            return {
                "ok": False,
                "bundle": None,
                "error_type": "token_exchange_failed",
                "error_detail": "Token exchange failed",
                "retryable": True,
            }

        plan_type = str(bundle.get("plan_type") or "").lower()
        if plan_type not in _TEAM_PLAN_TYPES:
            return {
                "ok": False,
                "bundle": None,
                "error_type": "non_team_plan",
                "error_detail": f"plan={plan_type or 'unknown'} is not Team",
                "retryable": True,
            }

        logger.info("[Codex] 登录成功: %s (plan: %s)", bundle.get("email") or email, bundle.get("plan_type"))
        return {
            "ok": True,
            "bundle": bundle,
            "error_type": None,
            "error_detail": None,
            "retryable": False,
        }

    def oauth_team_via_session(self, email: str, session_token: str) -> dict[str, Any]:
        self.oauth_fail_reason = ""
        self.p(f"Start OAuth via session: {email}")
        self._clear_oauth_continue()
        self._prime_cookies()
        self._inject_session(session_token)

        code_verifier, code_challenge = _generate_pkce()
        state = secrets.token_urlsafe(24)
        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "prompt": "login",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
        }
        authorize_url = f"{OAUTH_ISSUER}/oauth/authorize?{urlencode(params)}"
        current_url = authorize_url
        try:
            current_url = self.goto(authorize_url, referer=f"{BASE}/")
        except Exception as exc:
            match = re.search(r"(https?://localhost[^\s'\"]+)", str(exc))
            if match:
                current_url = match.group(1)

        auth_code = (
            self.captured_code
            or _extract_code(self.captured_code_url)
            or _extract_code(current_url)
            or _extract_code(getattr(self.page, "url", ""))
        )
        page_url = self._abs_auth_url(getattr(self.page, "url", "") or current_url) or authorize_url

        if not auth_code and any(token in page_url.lower() for token in ("consent", "workspace", "organization")):
            auth_code = self._resolve_code_from_consent(page_url, referer=authorize_url)
        if not auth_code:
            auth_code = self._follow_browser_continue(referer=page_url, max_age=20.0)
        if not auth_code:
            auth_code = self._follow_for_code(page_url, referer=authorize_url)[0]
        if not auth_code:
            return self._inspect_auth_page(page_url, referer=authorize_url)

        logger.info("[Codex] Captured auth code")
        bundle = self._exchange_auth_code(auth_code, code_verifier, fallback_email=email)
        if not bundle:
            return {
                "ok": False,
                "bundle": None,
                "error_type": "token_exchange_failed",
                "error_detail": "Token exchange failed",
                "retryable": True,
            }

        plan_type = str(bundle.get("plan_type") or "").lower()
        if plan_type not in _TEAM_PLAN_TYPES:
            return {
                "ok": False,
                "bundle": None,
                "error_type": "non_team_plan",
                "error_detail": f"plan={plan_type or 'unknown'} is not Team",
                "retryable": True,
            }

        logger.info("[Codex] 登录成功: %s (plan: %s)", bundle.get("email") or email, bundle.get("plan_type"))
        return {
            "ok": True,
            "bundle": bundle,
            "error_type": None,
            "error_detail": None,
            "retryable": False,
        }

    def accept_invite(self, invite_link: str, *, email: str = "") -> bool:
        target = str(invite_link or "").strip()
        if not target:
            return True

        try:
            self.goto(target, referer=f"{BASE}/")
        except Exception:
            try:
                self.page.goto(target, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
            except Exception:
                return False

        selectors = [
            "button:has-text('Accept invite')",
            "button:has-text('Join workspace')",
            "button:has-text('Join')",
            "button:has-text('Accept')",
            "button:has-text('Continue')",
            "a:has-text('Join workspace')",
            "a:has-text('Accept invite')",
            "button[type='submit']",
        ]
        for _ in range(6):
            for selector in selectors:
                try:
                    locator = self.page.locator(selector).first
                    if locator.count() < 1 or not locator.is_visible(timeout=400):
                        continue
                    locator.click(timeout=3000)
                    try:
                        self.page.wait_for_timeout(1500)
                    except Exception:
                        time.sleep(1.5)
                except Exception:
                    continue
            current_url = str(getattr(self.page, "url", "") or "").lower()
            if "chatgpt.com" in current_url and "auth" not in current_url:
                return True
            if email:
                try:
                    from autoteam.manager import _is_email_in_team

                    if _is_email_in_team(email):
                        return True
                except Exception:
                    pass
            time.sleep(1)
        return False
