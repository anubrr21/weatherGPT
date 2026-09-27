import base64
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import Device, Session
from app.services.http import client

log = logging.getLogger("weathergpt.push")

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load_account() -> dict[str, Any] | None:
    raw = get_settings().fcm_service_account.strip()
    if not raw:
        return None
    if raw.startswith("{"):
        return json.loads(raw)
    path = Path(raw)
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def signed_assertion(account: dict[str, Any], now: int) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": account["client_email"], "scope": SCOPE, "aud": account.get("token_uri", TOKEN_URL), "iat": now, "exp": now + 3600}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(claims, separators=(',', ':')).encode())}"
    key = serialization.load_pem_private_key(account["private_key"].encode(), password=None)
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64(signature)}"


def _ttl_seconds(expires: str | None) -> int:
    if not expires:
        return 6 * 3600
    try:
        end = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return 6 * 3600
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return int(max(60, min(28 * 86400, (end - datetime.now(timezone.utc)).total_seconds())))


def build_notice_message(token: str, notice: dict[str, Any]) -> dict[str, Any]:
    place = notice["place"]
    data = {
        "kind": notice["kind"],
        "notice_id": str(notice["id"]),
        "title": notice["title"][:120],
        "body": notice["body"][:600],
        "severity": notice["severity"],
        "channel": notice.get("channel", "alerts"),
        "place": place["name"],
        "lat": f"{place['lat']:.4f}",
        "lon": f"{place['lon']:.4f}",
    }
    alert_id = (notice.get("data") or {}).get("alert_id")
    if alert_id:
        data["alert_id"] = str(alert_id)
    return {"message": {"token": token, "data": data, "android": {"priority": "high", "ttl": f"{notice.get('ttl', 6 * 3600)}s", "collapse_key": data["notice_id"]}}}


def build_message(token: str, alert: dict[str, Any], place: dict[str, Any]) -> dict[str, Any]:
    severity = alert.get("severity") or "Alert"
    event = alert.get("event") or "Weather warning"
    title = f"{severity} · {event} — {place['name']}"
    return {
        "message": {
            "token": token,
            "data": {
                "kind": "alert",
                "title": title[:120],
                "body": (alert.get("headline") or "")[:600],
                "alert_id": str(alert["id"]),
                "place": place["name"],
                "lat": f"{place['lat']:.4f}",
                "lon": f"{place['lon']:.4f}",
                "severity": severity,
            },
            "android": {
                "priority": "high",
                "ttl": f"{_ttl_seconds(alert.get('expires'))}s",
                "collapse_key": str(alert["id"])[:64],
            },
        }
    }


class Push:
    def __init__(self) -> None:
        self._access: tuple[str, float] | None = None
        self.sent = 0
        self.failed = 0
        self.removed_tokens = 0
        self.last_error: str | None = None

    @property
    def account(self) -> dict[str, Any] | None:
        try:
            return load_account()
        except (OSError, ValueError) as exc:
            self.last_error = f"service account unreadable: {exc}"
            return None

    @property
    def enabled(self) -> bool:
        return self.account is not None

    async def access_token(self, account: dict[str, Any]) -> str:
        if self._access and self._access[1] - time.time() > 120:
            return self._access[0]
        response = await client().post(
            account.get("token_uri", TOKEN_URL),
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": signed_assertion(account, int(time.time()))},
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
        self._access = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
        return self._access[0]

    async def send(self, message: dict[str, Any]) -> tuple[bool, str | None, bool]:
        account = self.account
        if not account:
            return False, "push not configured", False
        token = await self.access_token(account)
        response = await client().post(
            SEND_URL.format(project=account["project_id"]),
            json=message,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if response.status_code == 200:
            self.sent += 1
            return True, None, False
        self.failed += 1
        detail = response.text[:300]
        self.last_error = f"{response.status_code}: {detail}"
        gone = response.status_code == 404 or "UNREGISTERED" in detail or (response.status_code == 400 and "registration token" in detail.lower())
        return False, detail, gone

    async def _forget(self, tokens: set[str]) -> None:
        if not tokens:
            return
        async with Session() as s:
            await s.execute(delete(Device).where(Device.token.in_(tokens)))
            await s.commit()
        self.removed_tokens += len(tokens)

    async def deliver(self, notices: list[dict[str, Any]]) -> set[int]:
        if not notices or not self.enabled:
            return set()
        clients = {n["client_id"] for n in notices}
        async with Session() as s:
            devices = (await s.scalars(select(Device).where(Device.client_id.in_(clients)))).all()
        by_client: dict[str, list[Device]] = {}
        for device in devices:
            by_client.setdefault(device.client_id, []).append(device)
        delivered: set[int] = set()
        gone: set[str] = set()
        for notice in notices:
            for device in by_client.get(notice["client_id"], []):
                if device.token in gone:
                    continue
                ok, _, is_gone = await self.send(build_notice_message(device.token, notice))
                if ok:
                    delivered.add(notice["id"])
                if is_gone:
                    gone.add(device.token)
        await self._forget(gone)
        return delivered

    async def test(self, client_id: str) -> dict[str, Any]:
        if not self.enabled:
            return {"configured": False, "sent": 0, "devices": 0}
        async with Session() as s:
            devices = (await s.scalars(select(Device).where(Device.client_id == client_id))).all()
        sample = {
            "id": f"test-{int(time.time())}",
            "severity": "Moderate",
            "event": "Test notification",
            "headline": "Push alerts are working. Official IMD and NDMA warnings for your saved places will arrive here.",
        }
        sent, gone = 0, set()
        for device in devices:
            ok, _, is_gone = await self.send(build_message(device.token, sample, {"name": "WeatherGPT", "lat": 0.0, "lon": 0.0}))
            sent += ok
            if is_gone:
                gone.add(device.token)
        await self._forget(gone)
        return {"configured": True, "sent": sent, "devices": len(devices)}

    def status(self) -> dict[str, Any]:
        account = self.account
        return {
            "configured": account is not None,
            "project": account.get("project_id") if account else None,
            "sent": self.sent,
            "failed": self.failed,
            "removed_tokens": self.removed_tokens,
            "last_error": self.last_error,
        }


push = Push()
