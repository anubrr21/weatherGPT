import asyncio
import base64
import json

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.services import push as push_module


def _account():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return key, {"client_email": "svc@demo.iam.gserviceaccount.com", "private_key": pem, "project_id": "weathergpt-demo", "token_uri": push_module.TOKEN_URL}


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_assertion_is_signed_by_the_service_account_key():
    key, account = _account()
    header, claims, signature = push_module.signed_assertion(account, 1_800_000_000).split(".")
    key.public_key().verify(_unb64(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = json.loads(_unb64(claims))
    assert body["iss"] == account["client_email"]
    assert body["scope"] == push_module.SCOPE
    assert body["exp"] - body["iat"] == 3600


def test_message_priority_and_data_are_fcm_compatible():
    alert = {"id": "1790434317019013", "severity": "Severe", "event": "Flood", "headline": "River above danger mark", "expires": "2099-01-01T00:00:00+05:30"}
    message = push_module.build_message("tok" * 10, alert, {"name": "Bahraich", "lat": 27.574, "lon": 81.595})["message"]
    assert message["android"]["priority"] == "high"
    assert message["android"]["notification"]["channel_id"] == "warnings"
    assert message["android"]["ttl"] == f"{28 * 86400}s"
    assert all(isinstance(v, str) for v in message["data"].values())
    minor = push_module.build_message("tok" * 10, alert | {"severity": "Minor"}, {"name": "X", "lat": 0, "lon": 0})["message"]
    assert minor["android"]["priority"] == "normal"


def test_uninstalled_app_token_is_reported_gone(monkeypatch):
    _, account = _account()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer ya29.test"
        return httpx.Response(404, json={"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(push_module, "client", lambda: mock)
    monkeypatch.setattr(push_module, "load_account", lambda: account)
    sender = push_module.Push()
    ok, _, gone = asyncio.run(sender.send(push_module.build_message("t" * 40, {"id": "a1", "headline": "h"}, {"name": "P", "lat": 0, "lon": 0})))
    assert not ok and gone
    assert calls[-1].endswith("/projects/weathergpt-demo/messages:send")
