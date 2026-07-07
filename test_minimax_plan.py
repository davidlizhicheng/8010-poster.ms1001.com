"""Smoke test Minimax batch planning via live poster API."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

AUTH = os.getenv("AUTH_BASE_URL", "http://127.0.0.1:9080").rstrip("/")
POSTER = os.getenv("POSTER_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
OWNER = os.getenv("OWNER_PHONE", "18665898305")
PASSWORD = os.getenv("OWNER_PASSWORD", "test123456")


def req(url: str, *, method="GET", body=None, token=""):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> None:
    status, cfg = req(f"{POSTER}/api/config")
    assert status == 200, cfg
    assert cfg.get("minimax_ready"), "minimax_ready=false — check MINIMAX_API_KEY / Gaokao .env"
    print("OK: minimax_ready=true")

    status, login = req(
        f"{AUTH}/api/auth/login",
        method="POST",
        body={"username": OWNER, "password": PASSWORD},
    )
    assert status == 200 and login.get("ok"), login
    token = login["token"]
    print("OK: owner login")

    status, plan = req(
        f"{POSTER}/api/prompts/batch-plan",
        method="POST",
        token=token,
        body={
            "command": "春季招生培训海报，蓝白金色系，突出课程亮点与限时优惠",
            "campaign_name": "春季招生",
            "template_key": "course-sale",
            "count": 3,
        },
    )
    assert status == 200, plan
    items = plan.get("items") or []
    assert len(items) >= 2, plan
    assert all(item.get("title") and item.get("prompt") for item in items)
    print(f"OK: Minimax batch plan returned {len(items)} items")
    print("Sample title length:", len(items[0]["title"]))


if __name__ == "__main__":
    main()
