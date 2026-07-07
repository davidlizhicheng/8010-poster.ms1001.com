"""End-to-end smoke tests: unified-auth + poster integration."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

AUTH_BASE = os.getenv("AUTH_BASE_URL", "http://127.0.0.1:9080").rstrip("/")
POSTER_BASE = os.getenv("POSTER_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
OWNER_PHONE = "18665898305"
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "test123456")


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict]:
    data = None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload


def test_auth_health() -> None:
    status, data = http_json(f"{AUTH_BASE}/api/auth/health")
    assert status == 200 and data.get("ok"), data
    print("OK: unified-auth health")


def test_owner_login_and_policy() -> None:
    status, login = http_json(
        f"{AUTH_BASE}/api/auth/login",
        method="POST",
        body={"username": OWNER_PHONE, "password": OWNER_PASSWORD},
    )
    assert status == 200 and login.get("ok"), login
    token = login["token"]
    status, policy = http_json(
        f"{AUTH_BASE}/api/payment/policy",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, policy
    assert policy["policy"]["isOwner"] is True
    assert "李总您好" in policy["policy"]["ownerGreeting"]
    print("OK: owner login + payment policy")
    return token


def test_poster_config() -> None:
    status, cfg = http_json(f"{POSTER_BASE}/api/config")
    assert status == 200, cfg
    assert int(cfg.get("max_items_per_job", 0)) >= 100
    assert cfg.get("use_unified_auth") is True
    print("OK: poster config unified auth enabled, max batch 100")


def test_poster_unified_me(token: str) -> None:
    status, me = http_json(
        f"{POSTER_BASE}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, me
    user = me.get("user") or {}
    assert user.get("phone") == OWNER_PHONE
    assert user.get("owner_vip") is True
    assert "李总您好" in (user.get("owner_greeting") or "")
    usage = me.get("usage") or {}
    assert usage.get("owner_vip") is True
    print("OK: poster resolves unified JWT for owner")


def test_owner_payment_charged(token: str) -> None:
    status, cfg = http_json(f"{POSTER_BASE}/api/config")
    if cfg.get("wechat_pay_ready"):
        status, claim = http_json(
            f"{POSTER_BASE}/api/payment/wechat/native/create",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
            body={"plan_id": "pack_20", "contract_accepted": True},
        )
    else:
        status, res = http_json(
            f"{POSTER_BASE}/api/payment/claim",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
            body={
                "plan_id": "pack_20",
                "screenshot_image": "",
                "phone": OWNER_PHONE,
                "contract_accepted": True,
            },
        )
        claim = res.get("claim") or {}
    assert status in {200, 201}, claim if cfg.get("wechat_pay_ready") else res
    assert float(claim.get("amount", -1)) > 0, claim
    if not cfg.get("wechat_pay_ready"):
        assert claim.get("status") == "approved"
    print("OK: owner payment uses normal amount")


def test_billing_page() -> None:
    req = urllib.request.Request(f"{AUTH_BASE}/billing?platform=poster.ms1001.com&plan=pack_20", method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8")
    assert resp.status == 200
    assert "统一收银台" in html
    print("OK: billing page served")


def test_billing_config() -> None:
    status, data = http_json(f"{AUTH_BASE}/api/billing/config")
    assert status == 200 and data.get("ok"), data
    assert "posterApi" in data
    assert "8010" in data["posterApi"], data
    print("OK: billing config API")


def test_billing_poster_api_with_token(token: str) -> None:
    status, cfg = http_json(f"{AUTH_BASE}/api/billing/config")
    poster_api = cfg["posterApi"].rstrip("/")
    status, me = http_json(
        f"{poster_api}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200, me
    assert me.get("user", {}).get("phone") == OWNER_PHONE
    print("OK: billing -> poster auth with unified JWT")


def main() -> None:
    test_auth_health()
    token = test_owner_login_and_policy()
    test_poster_config()
    test_poster_unified_me(token)
    test_owner_payment_charged(token)
    test_billing_page()
    test_billing_config()
    test_billing_poster_api_with_token(token)
    print("\nAll unified integration smoke tests passed.")


if __name__ == "__main__":
    main()
