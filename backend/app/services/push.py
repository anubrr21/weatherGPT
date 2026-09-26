import base64
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import Alert, Device, PushDelivery, Session, Subscription, utcnow
from app.services import alerts as alert_service
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


def content_key(alert: dict[str, Any]) -> tuple[str, str]:
    return (" ".join((alert.get("headline") or "").lower().split()), str(alert.get("expires") or "")[:16])


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

    async def notify_new_alerts(self, alerts: list[dict[str, Any]]) -> int:
        if not alerts or not self.enabled:
            return 0
        async with Session() as s:
            devices = (await s.scalars(select(Device))).all()
            if not devices:
                return 0
            clients = {d.client_id for d in devices}
            subs = (await s.scalars(select(Subscription).where(Subscription.client_id.in_(clients)))).all()
            since = utcnow() - timedelta(days=3)
            history = (await s.execute(
                select(PushDelivery.token, Alert.headline, Alert.expires)
                .join(Alert, Alert.id == PushDelivery.alert_id)
                .where(PushDelivery.sent_at >= since, PushDelivery.ok.is_(True))
            )).all()
            pushed_ids = set((await s.execute(select(PushDelivery.alert_id, PushDelivery.token).where(PushDelivery.sent_at >= since))).all())
        places: dict[str, list[dict[str, Any]]] = {}
        for sub in subs:
            places.setdefault(sub.client_id, []).append({"name": sub.name, "district": sub.district, "state": sub.state, "lat": sub.lat, "lon": sub.lon})
        seen: dict[str, set[tuple[str, str]]] = {}
        for token, headline, expires in history:
            seen.setdefault(token, set()).add(content_key({"headline": headline, "expires": expires.isoformat() if expires else None}))
        sent = 0
        gone: set[str] = set()
        records: list[PushDelivery] = []
        for device in devices:
            keys = seen.setdefault(device.token, set())
            for place in places.get(device.client_id, []):
                for alert in alert_service.alerts_for_place(alerts, place):
                    key = content_key({"headline": alert.get("headline"), "expires": _normalise(alert.get("expires"))})
                    if (alert["id"], device.token) in pushed_ids or key in keys or device.token in gone:
                        continue
                    keys.add(key)
                    pushed_ids.add((alert["id"], device.token))
                    ok, detail, is_gone = await self.send(build_message(device.token, alert, place))
                    records.append(PushDelivery(alert_id=alert["id"], token=device.token, client_id=device.client_id, ok=ok, detail=detail))
                    sent += ok
                    if is_gone:
                        gone.add(device.token)
        async with Session() as s:
            s.add_all(records)
            await s.commit()
        await self._forget(gone)
        return sent

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


def _normalise(expires: str | None) -> str | None:
    if not expires:
        return None
    try:
        value = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return expires
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


push = Push()
