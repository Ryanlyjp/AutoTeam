"""Self-hosted tempmail backend client."""

from __future__ import annotations

import html
import logging
import re
import time
import uuid

import requests

from autoteam.config import EMAIL_POLL_INTERVAL, EMAIL_POLL_TIMEOUT, TEMPMAIL_API_KEY, TEMPMAIL_BASE_URL, TEMPMAIL_DOMAIN

logger = logging.getLogger(__name__)

_VERIFICATION_CODE_PATTERNS = (
    r"(?:temporary\s+(?:openai|chatgpt)\s+login\s+code(?:\s+is)?|verification\s+code(?:\s+is)?|login\s+code(?:\s+is)?|code(?:\s+is)?|验证码(?:为|是)?)\D{0,24}(\d{6})",
    r"\b(\d{6})\b",
)


def _normalize_email(value):
    return str(value or "").strip().lower()


class TempmailClient:
    provider_name = "tempmail"

    def __init__(self, service=None):
        service = dict(service or {})
        self.service_id = str(service.get("id") or "").strip() or None
        self.service_name = str(service.get("name") or "").strip()
        self.base_url = str(service.get("base_url") or TEMPMAIL_BASE_URL or "").strip().rstrip("/")
        self.api_key = str(service.get("api_key") or TEMPMAIL_API_KEY or "").strip()
        self.domain = str(service.get("domain") or TEMPMAIL_DOMAIN or "").strip().lstrip("@")
        self.session = requests.Session()
        self._mailbox_ids: dict[str, str] = {}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _get(self, path, params=None):
        return self.session.get(self._url(path), headers=self._headers(), params=params, timeout=30)

    def _post(self, path, data=None):
        return self.session.post(self._url(path), headers=self._headers(), json=data or {}, timeout=30)

    def _delete(self, path):
        return self.session.delete(self._url(path), headers=self._headers(), timeout=30)

    @staticmethod
    def _unwrap_email_payload(payload):
        if isinstance(payload, dict):
            for key in ("email", "data", "item", "message"):
                value = payload.get(key)
                if isinstance(value, dict):
                    return value
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _sanitize_prefix(prefix: str | None) -> str:
        if not prefix:
            return uuid.uuid4().hex[:10]
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "", str(prefix)).strip(".-_")
        return cleaned[:60] or uuid.uuid4().hex[:10]

    @staticmethod
    def _parse_or_raise(response: requests.Response, label: str) -> dict:
        if response.status_code in {401, 403}:
            raise RuntimeError(f"tempmail {label} 鉴权失败，请检查 api_key")
        if response.status_code >= 400:
            try:
                payload = response.json() or {}
                detail = payload.get("error") or payload.get("detail") or response.text[:200]
            except Exception:
                detail = response.text[:200]
            raise RuntimeError(f"tempmail {label} 失败: HTTP {response.status_code} {detail}")
        try:
            return response.json() or {}
        except Exception as exc:
            raise RuntimeError(f"tempmail {label} 返回了非 JSON 内容") from exc

    @staticmethod
    def _html_to_visible_text(value):
        content = str(value or "")
        if not content:
            return ""
        content = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", content)
        content = re.sub(r"(?is)<!--.*?-->", " ", content)
        content = re.sub(r"(?i)<br\s*/?>", "\n", content)
        content = re.sub(r"(?i)</(?:p|div|tr|table|h[1-6]|li|td|section|article)>", "\n", content)
        content = re.sub(r"(?s)<[^>]+>", " ", content)
        content = html.unescape(content)
        content = re.sub(r"[\t\r\f\v ]+", " ", content)
        content = re.sub(r"\n\s+", "\n", content)
        content = re.sub(r"\n{2,}", "\n", content)
        return content.strip()

    def login(self):
        if not self.base_url:
            raise RuntimeError("tempmail 未配置 base_url")
        if not self.api_key:
            raise RuntimeError("tempmail 未配置 api_key")
        response = self._get("/api/me")
        if response.status_code in {401, 403}:
            raise RuntimeError(f"tempmail api_key 无效 (HTTP {response.status_code})")
        if response.status_code != 200:
            raise RuntimeError(f"tempmail 登录失败: HTTP {response.status_code} {(response.text or '')[:200]}")
        return f"key-{self.api_key[:6]}"

    def create_temp_email(self, prefix=None):
        payload = {"source": "api"}
        if prefix:
            payload["address"] = self._sanitize_prefix(prefix)
        if self.domain:
            payload["domain"] = self.domain
        data = self._parse_or_raise(self._post("/api/mailboxes", payload), "创建邮箱")
        mailbox = data.get("mailbox") or {}
        mailbox_id = mailbox.get("id") or mailbox.get("uuid")
        email = mailbox.get("full_address") or mailbox.get("fullAddress") or ""
        if not mailbox_id or not email:
            raise RuntimeError(f"tempmail 创建邮箱响应缺字段: {mailbox!r}")
        self._mailbox_ids[_normalize_email(email)] = str(mailbox_id)
        logger.info("[Tempmail] 临时邮箱已创建: %s (mailboxId=%s)", email, mailbox_id)
        return mailbox_id, email

    def list_accounts(self, size=200):
        data = self._parse_or_raise(self._get("/api/mailboxes", params={"size": min(int(size or 200), 100)}), "获取邮箱列表")
        results = []
        for row in data.get("data") or []:
            account = {
                "accountId": row.get("id"),
                "email": row.get("full_address"),
                "createTime": row.get("created_at"),
                "expiresAt": row.get("expires_at"),
            }
            results.append(account)
            email = account.get("email")
            if email and account.get("accountId") is not None:
                self._mailbox_ids[_normalize_email(email)] = str(account["accountId"])
        return results

    def _resolve_id(self, value):
        text = str(value or "").strip()
        if not text:
            return None
        if "@" not in text:
            return text
        cached = self._mailbox_ids.get(_normalize_email(text))
        if cached:
            return cached
        for row in self.list_accounts(size=500):
            if _normalize_email(row.get("email")) == _normalize_email(text):
                return str(row.get("accountId"))
        return None

    @staticmethod
    def _normalize_email_row(row, recipient=None):
        return {
            "emailId": row.get("id"),
            "accountEmail": recipient,
            "toEmail": recipient,
            "sendEmail": row.get("sender") or row.get("from_addr") or row.get("from") or "",
            "sender": row.get("sender") or row.get("from_addr") or row.get("from") or "",
            "subject": row.get("subject") or "",
            "text": row.get("body_text") or row.get("text_body") or row.get("text") or "",
            "content": row.get("body_html") or row.get("html_body") or row.get("html") or row.get("content") or "",
            "messageId": row.get("message_id") or row.get("messageId") or "",
            "createTime": row.get("received_at") or row.get("created_at") or "",
            "raw": row.get("raw") or "",
            "otpCode": ((row.get("otp") or {}) if isinstance(row.get("otp"), dict) else {}).get("code") or "",
        }

    def _fetch_email_detail(self, mailbox_id, email_id):
        if not mailbox_id or not email_id:
            return {}
        response = self._get(f"/api/mailboxes/{mailbox_id}/emails/{email_id}")
        if response.status_code != 200:
            return {}
        try:
            payload = response.json() or {}
        except Exception:
            return {}
        return self._unwrap_email_payload(payload)

    def _fetch_latest_otp(self, mailbox_id):
        if not mailbox_id:
            return None
        response = self._get(f"/api/mailboxes/{mailbox_id}/otp/latest")
        if response.status_code != 200:
            return None
        try:
            payload = response.json() or {}
        except Exception:
            return None
        otp = payload.get("otp")
        if not isinstance(otp, dict):
            return None
        code = str(otp.get("code") or "").strip()
        if not code:
            return None
        return {
            "code": code,
            "sender": str(otp.get("sender") or "").strip(),
        }

    def list_emails(self, account_id, size=10):
        mailbox_id = self._resolve_id(account_id)
        if not mailbox_id:
            return []
        response = self._get(f"/api/mailboxes/{mailbox_id}/emails", params={"size": min(int(size or 10), 100)})
        if response.status_code != 200:
            return []
        data = response.json() or {}
        emails = []
        for row in data.get("data") or []:
            if not isinstance(row, dict):
                continue
            detail = self._fetch_email_detail(mailbox_id, row.get("id"))
            merged = {**row, **detail} if detail else row
            emails.append(self._normalize_email_row(merged))
        return emails

    def search_emails_by_recipient(self, to_email, size=10, account_id=None):
        mailbox_id = self._resolve_id(account_id) if account_id else self._resolve_id(to_email)
        if not mailbox_id:
            return []
        response = self._get(f"/api/mailboxes/{mailbox_id}/emails", params={"size": min(int(size or 10), 100)})
        if response.status_code != 200:
            return []
        data = response.json() or {}
        emails = []
        for row in data.get("data") or []:
            if not isinstance(row, dict):
                continue
            detail = self._fetch_email_detail(mailbox_id, row.get("id"))
            merged = {**row, **detail} if detail else row
            emails.append(self._normalize_email_row(merged, recipient=to_email))
        return emails

    def wait_for_email(self, to_email, timeout=None, sender_keyword=None):
        timeout = timeout or EMAIL_POLL_TIMEOUT
        logger.info("[Tempmail] 等待邮件到达 %s... (超时 %ds)", to_email, timeout)
        start = time.time()

        while time.time() - start < timeout:
            emails = self.search_emails_by_recipient(to_email, size=10)
            for email_data in emails:
                sender = str(email_data.get("sendEmail") or email_data.get("sender") or "")
                if sender_keyword and sender_keyword.lower() not in sender.lower():
                    continue
                logger.info("[Tempmail] 收到邮件: %s (from: %s)", email_data.get("subject"), sender)
                return email_data

            elapsed = int(time.time() - start)
            print(f"\r[Tempmail] 等待中... ({elapsed}s)", end="", flush=True)
            time.sleep(EMAIL_POLL_INTERVAL)

        print()
        raise TimeoutError("等待邮件超时")

    def _wait_for_otp_via_search(
        self,
        to_email,
        *,
        timeout,
        sender_keyword="openai",
        account_id=None,
        ignore_email_ids: set[str] | None = None,
        ignore_codes: set[str] | None = None,
    ):
        deadline = time.time() + timeout
        seen_ids = set()
        ignore_email_ids = {str(item) for item in (ignore_email_ids or set()) if item}
        ignore_codes = {str(item) for item in (ignore_codes or set()) if item}
        seen_senders: list[str] = []
        emails_total = 0
        regex_misses = 0
        polls = 0
        started = time.time()

        while time.time() < deadline:
            polls += 1
            try:
                emails = self.search_emails_by_recipient(to_email, size=10, account_id=account_id)
            except Exception as exc:
                logger.warning("[tempmail] OTP 轮询失败: %s", exc)
                emails = []
            for em in emails:
                eid = em.get("emailId") or em.get("id")
                eid_str = str(eid).strip() if eid is not None else ""
                if eid_str and eid_str in ignore_email_ids:
                    continue
                if eid_str and eid_str in seen_ids:
                    continue
                if eid_str:
                    seen_ids.add(eid_str)
                emails_total += 1
                sender = str(em.get("sendEmail") or em.get("sender") or "").lower()
                if sender and sender not in seen_senders:
                    seen_senders.append(sender)
                if sender_keyword and sender_keyword.lower() not in sender:
                    continue
                code = self.extract_verification_code(em)
                if code and code in ignore_codes:
                    continue
                if code:
                    logger.info("[tempmail] OTP 命中 (poll #%d, %.1fs): %s from %s", polls, time.time() - started, code, sender)
                    return code
                regex_misses += 1
            time.sleep(EMAIL_POLL_INTERVAL)

        elapsed = time.time() - started
        diag = f"polls={polls} elapsed={elapsed:.1f}s emails_seen={emails_total}"
        if seen_senders:
            diag += f" senders={seen_senders[:5]}"
        if emails_total == 0:
            hint = "邮箱完全没收到邮件 — 检查 OpenAI 是否真的发了, 域名 MX 是否正确, 是否被风控"
        elif regex_misses == emails_total and sender_keyword:
            hint = f"收到 {emails_total} 封邮件但没有 sender 含 {sender_keyword!r} — 可能不是 OpenAI 发件域, 或其它邮件混入"
        else:
            hint = "收到匹配邮件但提取不到 6 位验证码 — 看邮件正文是不是被改成了链接形式"
        raise TimeoutError(f"等待 {to_email} OTP 超时 ({elapsed:.1f}s, timeout={timeout}s) — {diag} | hint: {hint}")

    def wait_for_otp(
        self,
        to_email,
        timeout=None,
        sender_keyword="openai",
        account_id=None,
        ignore_email_ids: set[str] | None = None,
        ignore_codes: set[str] | None = None,
    ):
        timeout = timeout or EMAIL_POLL_TIMEOUT
        mailbox_id = self._resolve_id(account_id) if account_id else self._resolve_id(to_email)
        if not mailbox_id:
            logger.warning("[tempmail] wait_for_otp: 找不到 mailbox id for %s, 走 search 路径", to_email)
            return self._wait_for_otp_via_search(
                to_email,
                timeout=timeout,
                sender_keyword=sender_keyword,
                account_id=account_id,
                ignore_email_ids=ignore_email_ids,
                ignore_codes=ignore_codes,
            )

        if ignore_email_ids or ignore_codes:
            return self._wait_for_otp_via_search(
                to_email,
                timeout=timeout,
                sender_keyword=sender_keyword,
                account_id=mailbox_id,
                ignore_email_ids=ignore_email_ids,
                ignore_codes=ignore_codes,
            )

        started = time.time()
        deadline = started + timeout
        seen_status: dict[int, int] = {}
        seen_senders: list[str] = []
        last_otp_code = None
        last_otp_sender = ""
        polls = 0

        while time.time() < deadline:
            polls += 1
            try:
                response = self._get(f"/api/mailboxes/{mailbox_id}/otp/latest")
            except Exception as exc:
                logger.warning("[tempmail] otp/latest 异常: %s", exc)
                time.sleep(EMAIL_POLL_INTERVAL)
                continue

            status_code = response.status_code
            seen_status[status_code] = seen_status.get(status_code, 0) + 1
            if response.status_code == 200:
                try:
                    payload = response.json() or {}
                except Exception:
                    payload = {}
                otp = payload.get("otp") if isinstance(payload, dict) else {}
                code = str((otp or {}).get("code") or "").strip()
                sender = str((otp or {}).get("sender") or "").lower()
                last_otp_code = code
                last_otp_sender = sender
                if sender and sender not in seen_senders:
                    seen_senders.append(sender)
                if code and (not sender_keyword or sender_keyword.lower() in sender):
                    logger.info("[tempmail] OTP 命中 (poll #%d, %.1fs): %s from %s", polls, time.time() - started, code, sender)
                    return code

            time.sleep(EMAIL_POLL_INTERVAL)

        elapsed = time.time() - started
        diag_parts = [f"polls={polls} elapsed={elapsed:.1f}s"]
        diag_parts.append("server_responses=" + ",".join(f"{k}:{v}" for k, v in sorted(seen_status.items())))
        if seen_senders:
            diag_parts.append(f"saw_senders={seen_senders[:5]}")
        if last_otp_code:
            diag_parts.append(f"last_email_had_code_but_sender={last_otp_sender!r}_!~_{sender_keyword!r}")
        diag = " | ".join(diag_parts)

        if seen_status.get(404, 0) == polls:
            hint = "全程 404 — 邮箱从未收到任何邮件。检查 OpenAI 是否真的发了, 域名 MX 是否指向 tempmail, 是否被 OpenAI 标黑"
        elif last_otp_code and sender_keyword and sender_keyword.lower() not in last_otp_sender:
            hint = f"邮件到了但发件人 ({last_otp_sender}) 不含 {sender_keyword!r} — 可能不是 OpenAI 发的, 或 OpenAI 用了别的域名"
        else:
            hint = "看上面 server_responses 分布"
        raise TimeoutError(f"等待 {to_email} OTP 超时 ({elapsed:.1f}s, timeout={timeout}s) — {diag} | hint: {hint}")

    def extract_verification_code(self, email_data):
        otp_code = str(email_data.get("otpCode") or "").strip()
        if otp_code:
            match = re.search(r"\b(\d{6})\b", otp_code)
            if match:
                return match.group(1)

        sources = []

        plain_text = str(email_data.get("text") or "").strip()
        if plain_text:
            sources.append(plain_text)

        html_text = self._html_to_visible_text(email_data.get("content"))
        if html_text and html_text not in sources:
            sources.append(html_text)

        subject = str(email_data.get("subject") or "").strip()
        if subject and subject not in sources:
            sources.append(subject)

        for source in sources:
            for pattern in _VERIFICATION_CODE_PATTERNS:
                match = re.search(pattern, source, re.IGNORECASE)
                if match:
                    return match.group(1)

        account_id = self._resolve_id(email_data.get("accountEmail") or email_data.get("toEmail"))
        latest_otp = self._fetch_latest_otp(account_id)
        latest_code = str((latest_otp or {}).get("code") or "").strip()
        if latest_code:
            match = re.search(r"\b(\d{6})\b", latest_code)
            if match:
                return match.group(1)

        return None

    def extract_invite_link(self, email_data):
        html_body = str(email_data.get("content") or "")
        text = str(email_data.get("text") or "")

        links = re.findall(r'href="(https://chatgpt\.com/auth/login\?[^"]*)"', html_body)
        if links:
            return links[0]

        links = re.findall(r'(https://chatgpt\.com/auth/login\?[^\s<>"\']+)', text)
        if links:
            return links[0]

        match = re.search(r'https?://[^\s<>"\']+(?:invite|accept|join|workspace)[^\s<>"\']*', html_body or text, re.IGNORECASE)
        if match:
            return match.group(0)
        return None

    def delete_emails_for(self, to_email):
        mailbox_id = self._resolve_id(to_email)
        if not mailbox_id:
            return 0
        emails = self.search_emails_by_recipient(to_email, size=100, account_id=mailbox_id)
        deleted = 0
        for email_data in emails:
            email_id = email_data.get("emailId")
            if not email_id:
                continue
            try:
                response = self._delete(f"/api/mailboxes/{mailbox_id}/emails/{email_id}")
                if response.status_code in {200, 204}:
                    deleted += 1
            except Exception:
                pass
        if deleted:
            logger.info("[Tempmail] 已删除 %s 的 %d 封旧邮件", to_email, deleted)
        return deleted

    def delete_account(self, account_id):
        mailbox_id = self._resolve_id(account_id)
        if not mailbox_id:
            return {"code": 404, "message": "mailbox not found"}
        response = self._delete(f"/api/mailboxes/{mailbox_id}")
        if response.status_code in {200, 204}:
            logger.info("[Tempmail] 临时邮箱已删除 (mailboxId=%s)", mailbox_id)
            return {"code": 200}
        return {"code": response.status_code, "message": (response.text or "")[:200]}
