"""Helpers for working with a local easyproxy hybrid deployment."""

from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from autoteam.textio import read_text, write_text

EASYPROXY_MASTER_MODE_DIRECT = "direct"
EASYPROXY_MASTER_MODE_POOL = "follow_pool"

PROJECT_ROOT = Path(__file__).parent.parent.parent
STATE_FILE = PROJECT_ROOT / "easyproxy_state.json"
STATE_FILE_MODE = 0o666

_LOCK = threading.RLock()
_TLS = threading.local()

logger = logging.getLogger(__name__)


class EasyProxyError(RuntimeError):
    """Raised when easyproxy settings are invalid or the management API fails."""


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _normalize_int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise EasyProxyError(f"easyproxy.{field} 必须是整数") from exc
    if out < minimum or out > maximum:
        raise EasyProxyError(f"easyproxy.{field} 必须在 {minimum}..{maximum} 之间")
    return out


def _normalize_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _read_state() -> dict[str, Any]:
    with _LOCK:
        if not STATE_FILE.exists():
            return {"local_blacklist": {}}
        try:
            payload = json.loads(read_text(STATE_FILE))
        except Exception:
            return {"local_blacklist": {}}
        if not isinstance(payload, dict):
            return {"local_blacklist": {}}
        return payload


def _write_state(state: dict[str, Any]) -> None:
    with _LOCK:
        target = STATE_FILE.resolve()
        write_text(target, json.dumps(state, indent=2, ensure_ascii=False))
        target.chmod(STATE_FILE_MODE)


def _normalize_local_blacklist(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw_port, meta in dict(value or {}).items():
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            continue
        if port < 1 or port > 65535:
            continue
        record = dict(meta or {})
        out[str(port)] = {
            "reason": str(record.get("reason") or ""),
            "tag": str(record.get("tag") or ""),
            "name": str(record.get("name") or ""),
            "blacklisted_at": str(record.get("blacklisted_at") or ""),
            "until": str(record.get("until") or ""),
        }
    return out


def _normalize_last_selected_port(value: Any) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if port < 1 or port > 65535:
        return None
    return port


def normalize_easyproxy_settings(env: dict[str, Any] | None = None) -> dict[str, Any]:
    source = env or {}
    state = _read_state()

    management_url = str(source.get("EASYPROXY_MANAGEMENT_URL") or "").strip() or "http://127.0.0.1:9888"
    parsed = urlparse(management_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EasyProxyError("easyproxy.management_url 必须是完整的 http(s) URL，例如 http://127.0.0.1:9888")

    proxy_host = str(source.get("EASYPROXY_PROXY_HOST") or "").strip() or "127.0.0.1"
    if any(ch.isspace() for ch in proxy_host):
        raise EasyProxyError("easyproxy.proxy_host 不能包含空白字符")

    port_min = _normalize_int(source.get("EASYPROXY_PORT_MIN", 24000), field="port_min", minimum=1, maximum=65535)
    port_max = _normalize_int(source.get("EASYPROXY_PORT_MAX", 24100), field="port_max", minimum=1, maximum=65535)
    if port_min > port_max:
        raise EasyProxyError("easyproxy.port_min 不能大于 port_max")

    pool_port = _normalize_int(source.get("EASYPROXY_POOL_PORT", 2323), field="pool_port", minimum=1, maximum=65535)
    cooldown_minutes = _normalize_int(
        source.get("EASYPROXY_COOLDOWN_MINUTES", 60),
        field="cooldown_minutes",
        minimum=1,
        maximum=24 * 60,
    )

    master_mode = str(source.get("EASYPROXY_MASTER_MODE") or EASYPROXY_MASTER_MODE_DIRECT).strip().lower()
    if master_mode not in {EASYPROXY_MASTER_MODE_DIRECT, EASYPROXY_MASTER_MODE_POOL}:
        raise EasyProxyError("easyproxy.master_mode 只支持 direct / follow_pool")

    return {
        "enabled": _normalize_bool(source.get("EASYPROXY_ENABLED", False)),
        "management_url": management_url.rstrip("/"),
        "password": str(source.get("EASYPROXY_PASSWORD") or ""),
        "proxy_host": proxy_host,
        "pool_port": pool_port,
        "port_min": port_min,
        "port_max": port_max,
        "cooldown_minutes": cooldown_minutes,
        "master_mode": master_mode,
        "local_blacklist": _normalize_local_blacklist(state.get("local_blacklist") or {}),
        "last_selected_port": _normalize_last_selected_port(state.get("last_selected_port")),
    }


def _save_local_blacklist(blacklist: dict[str, Any]) -> None:
    state = _read_state()
    state["local_blacklist"] = _normalize_local_blacklist(blacklist)
    _write_state(state)


def _save_last_selected_port(port: int | None) -> None:
    state = _read_state()
    state["last_selected_port"] = _normalize_last_selected_port(port)
    _write_state(state)


def _prune_local_blacklist(cfg: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    changed = False
    kept: dict[str, dict[str, Any]] = {}
    for port, meta in dict(cfg.get("local_blacklist") or {}).items():
        until = _parse_iso(meta.get("until"))
        if until and until <= now:
            changed = True
            continue
        kept[port] = meta
    if changed:
        _save_local_blacklist(kept)
        cfg = {**cfg, "local_blacklist": kept}
    return cfg


class EasyProxyClient:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.base_url = cfg["management_url"].rstrip("/")
        self.password = str(cfg.get("password") or "")
        self.session = requests.Session()
        self.session.trust_env = False
        self._token: str | None = None

    def _auth_headers(self) -> dict[str, str]:
        if not self.password:
            raise EasyProxyError("easyproxy.password 未配置，无法访问管理 API")
        if not self._token:
            resp = self.session.post(
                urljoin(self.base_url + "/", "api/auth"),
                json={"password": self.password},
                timeout=10,
            )
            try:
                data = resp.json() or {}
            except Exception as exc:
                raise EasyProxyError(f"easyproxy 登录响应无法解析: HTTP {resp.status_code}") from exc
            if resp.status_code != 200:
                detail = data.get("error") or data.get("detail") or resp.text[:200]
                raise EasyProxyError(f"easyproxy 登录失败: {detail}")
            self._token = str(data.get("token") or "")
            if not self._token:
                raise EasyProxyError("easyproxy 登录成功，但未返回 token")
        return {"Authorization": f"Bearer {self._token}"}

    def get_json(self, path: str) -> dict[str, Any]:
        resp = self.session.get(urljoin(self.base_url + "/", path.lstrip("/")), headers=self._auth_headers(), timeout=10)
        try:
            data = resp.json() or {}
        except Exception as exc:
            raise EasyProxyError(f"easyproxy {path} 响应无法解析: HTTP {resp.status_code}") from exc
        if resp.status_code != 200:
            detail = data.get("error") or data.get("detail") or resp.text[:200]
            raise EasyProxyError(f"easyproxy {path} 请求失败: {detail}")
        return data

    def post_json(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self.session.post(
            urljoin(self.base_url + "/", path.lstrip("/")),
            headers=self._auth_headers(),
            json=payload or {},
            timeout=10,
        )
        try:
            data = resp.json() or {}
        except Exception as exc:
            raise EasyProxyError(f"easyproxy {path} 响应无法解析: HTTP {resp.status_code}") from exc
        if resp.status_code != 200:
            detail = data.get("error") or data.get("detail") or resp.text[:200]
            raise EasyProxyError(f"easyproxy {path} 请求失败: {detail}")
        return data


def _build_entries(cfg: dict[str, Any], nodes_payload: dict[str, Any]) -> list[dict[str, Any]]:
    local_blacklist = dict(cfg.get("local_blacklist") or {})
    entries: dict[int, dict[str, Any]] = {}
    for node in nodes_payload.get("nodes") or []:
        try:
            port = int(node.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if port < cfg["port_min"] or port > cfg["port_max"]:
            continue
        local = local_blacklist.get(str(port)) or {}
        entries[port] = {
            "port": port,
            "tag": str(node.get("tag") or ""),
            "name": str(node.get("name") or ""),
            "available": bool(node.get("available")),
            "remote_blacklisted": bool(node.get("blacklisted")),
            "last_error": str(node.get("last_error") or ""),
            "active_connections": int(node.get("active_connections") or 0),
            "last_latency_ms": int(node.get("last_latency_ms") or 0),
            "last_success": str(node.get("last_success") or ""),
            "last_failure": str(node.get("last_failure") or ""),
            "local_blacklisted": bool(local),
            "local_blacklist_until": str(local.get("until") or ""),
            "local_blacklist_reason": str(local.get("reason") or ""),
            "selectable": bool(node.get("available")) and not bool(node.get("blacklisted")) and not bool(local),
        }

    for port_raw, local in local_blacklist.items():
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            continue
        if port in entries or port < cfg["port_min"] or port > cfg["port_max"]:
            continue
        entries[port] = {
            "port": port,
            "tag": str(local.get("tag") or ""),
            "name": str(local.get("name") or ""),
            "available": False,
            "remote_blacklisted": False,
            "last_error": "",
            "active_connections": 0,
            "last_latency_ms": 0,
            "last_success": "",
            "last_failure": "",
            "local_blacklisted": True,
            "local_blacklist_until": str(local.get("until") or ""),
            "local_blacklist_reason": str(local.get("reason") or ""),
            "selectable": False,
        }
    return [entries[port] for port in sorted(entries)]


def _public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(cfg.get("enabled")),
        "management_url": cfg.get("management_url") or "",
        "proxy_host": cfg.get("proxy_host") or "127.0.0.1",
        "pool_port": int(cfg.get("pool_port") or 2323),
        "port_min": int(cfg.get("port_min") or 24000),
        "port_max": int(cfg.get("port_max") or 24100),
        "cooldown_minutes": int(cfg.get("cooldown_minutes") or 60),
        "master_mode": cfg.get("master_mode") or EASYPROXY_MASTER_MODE_DIRECT,
    }


def get_status(env: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _prune_local_blacklist(normalize_easyproxy_settings(env))
    try:
        payload = EasyProxyClient(cfg).get_json("/api/nodes")
        entries = _build_entries(cfg, payload)
    except Exception as exc:
        return {
            "ok": False,
            "enabled": bool(cfg.get("enabled")),
            "config": _public_config(cfg),
            "ports": [],
            "error": str(exc),
        }

    selectable = sum(1 for entry in entries if entry["selectable"])
    remote_available = sum(1 for entry in entries if entry["available"] and not entry["remote_blacklisted"])
    if not entries:
        return {
            "ok": False,
            "enabled": bool(cfg.get("enabled")),
            "config": _public_config(cfg),
            "ports": [],
            "error": "在设定端口范围内没有发现 hybrid 端口，请确认 easyproxy 已启用 hybrid/multi-port 并检查端口范围。",
        }

    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "config": _public_config(cfg),
        "ports": entries,
        "summary": {
            "total": len(entries),
            "remote_available": remote_available,
            "local_blacklisted": sum(1 for entry in entries if entry["local_blacklisted"]),
            "selectable": selectable,
        },
    }


def build_port_proxy_url(cfg: dict[str, Any], port: int) -> str:
    return f"http://{cfg['proxy_host']}:{int(port)}"


def build_pool_proxy_url(cfg: dict[str, Any]) -> str:
    return build_port_proxy_url(cfg, int(cfg.get("pool_port") or 2323))


def set_pending_assignment(assignment: dict[str, Any] | None) -> None:
    _TLS.pending_assignment = assignment or None


def get_pending_assignment() -> dict[str, Any] | None:
    assignment = getattr(_TLS, "pending_assignment", None)
    return dict(assignment) if isinstance(assignment, dict) else None


def clear_pending_assignment() -> None:
    if hasattr(_TLS, "pending_assignment"):
        _TLS.pending_assignment = None


def select_proxy_assignment(*, avoid_ports: set[int] | None = None, env: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _prune_local_blacklist(normalize_easyproxy_settings(env))
    if not cfg.get("enabled"):
        raise EasyProxyError("easyproxy 未启用")
    status = get_status(env)
    if not status.get("ok"):
        raise EasyProxyError(str(status.get("error") or "easyproxy 状态不可用"))
    avoid = set(avoid_ports or set())
    candidates = [entry for entry in status["ports"] if entry.get("selectable")]
    if not candidates:
        raise EasyProxyError("easyproxy 当前没有可用端口，请检查节点状态或释放本地黑名单")
    preferred = [entry for entry in candidates if int(entry["port"]) not in avoid]
    available = preferred or candidates
    last_selected_port = _normalize_last_selected_port(cfg.get("last_selected_port"))
    choice_pool = [entry for entry in available if int(entry["port"]) != last_selected_port]
    if not choice_pool:
        choice_pool = available

    logger.info(
        "[EasyProxy] 可选端口=%s | 上次端口=%s | 本轮候选=%s",
        [int(entry["port"]) for entry in candidates],
        last_selected_port if last_selected_port is not None else "-",
        [int(entry["port"]) for entry in choice_pool],
    )
    chosen = secrets.choice(choice_pool)
    _save_last_selected_port(int(chosen["port"]))
    assignment = {
        "proxy_url": build_port_proxy_url(cfg, int(chosen["port"])),
        "port": int(chosen["port"]),
        "tag": chosen.get("tag") or "",
        "name": chosen.get("name") or "",
    }
    set_pending_assignment(assignment)
    return assignment


def is_network_error(exc: Exception | str) -> bool:
    text = str(exc).lower()
    hints = (
        "econnreset",
        "timeout",
        "timed out",
        "no recent network activity",
        "connection reset",
        "bad gateway",
        "proxy_connection_failed",
        "connection refused",
        "i/o timeout",
        "net::err_proxy",
        "502",
        "503",
        "504",
    )
    return any(hint in text for hint in hints)


def mark_port_bad(port: int, reason: str, *, tag: str = "", name: str = "", env: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _prune_local_blacklist(normalize_easyproxy_settings(env))
    if not cfg.get("enabled"):
        return cfg
    blacklisted_at = _now()
    until = blacklisted_at + timedelta(minutes=int(cfg.get("cooldown_minutes") or 60))
    blacklist = dict(cfg.get("local_blacklist") or {})
    blacklist[str(int(port))] = {
        "reason": str(reason or "")[:300],
        "tag": str(tag or ""),
        "name": str(name or ""),
        "blacklisted_at": _iso(blacklisted_at),
        "until": _iso(until),
    }
    _save_local_blacklist(blacklist)
    cfg = {**cfg, "local_blacklist": blacklist}
    return cfg


def mark_pending_assignment_bad(reason: str, *, env: dict[str, Any] | None = None) -> dict[str, Any] | None:
    assignment = get_pending_assignment()
    clear_pending_assignment()
    if not assignment:
        return None
    return mark_port_bad(
        int(assignment["port"]),
        reason,
        tag=str(assignment.get("tag") or ""),
        name=str(assignment.get("name") or ""),
        env=env,
    )


def release_ports(ports: list[int] | None = None, *, remote: bool = True, env: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _prune_local_blacklist(normalize_easyproxy_settings(env))
    current_blacklist = dict(cfg.get("local_blacklist") or {})
    if ports is None:
        targets = sorted(int(port) for port in current_blacklist.keys())
    else:
        targets = sorted({int(port) for port in ports})

    new_blacklist = {port: meta for port, meta in current_blacklist.items() if int(port) not in set(targets)}
    if new_blacklist != current_blacklist:
        _save_local_blacklist(new_blacklist)
        cfg = {**cfg, "local_blacklist": new_blacklist}

    released_remote: list[int] = []
    remote_errors: list[dict[str, Any]] = []
    if remote and targets:
        try:
            client = EasyProxyClient(cfg)
            nodes = client.get_json("/api/nodes")
            tags_by_port = {
                int(node.get("port") or 0): str(node.get("tag") or "")
                for node in (nodes.get("nodes") or [])
                if node.get("port")
            }
            for port in targets:
                tag = tags_by_port.get(int(port)) or current_blacklist.get(str(port), {}).get("tag") or ""
                if not tag:
                    continue
                try:
                    client.post_json(f"/api/nodes/{tag}/release")
                    released_remote.append(int(port))
                except Exception as exc:
                    remote_errors.append({"port": int(port), "error": str(exc)})
        except Exception as exc:
            remote_errors.append({"port": 0, "error": str(exc)})

    status = get_status(env)
    status["released"] = {
        "local": targets,
        "remote": released_remote,
        "remote_errors": remote_errors,
    }
    return status
