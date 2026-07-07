"""本地验证微信 Native 下单（需 data/config.json + apiclient_key.pem）。"""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"


def request(method: str, path: str, body: dict | None = None, cookie: str = "") -> tuple[int, dict, str]:
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if cookie:
        headers["Cookie"] = cookie
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            set_cookie = resp.headers.get("Set-Cookie", "")
            return resp.status, json.loads(resp.read().decode("utf-8")), set_cookie
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return exc.code, parsed, exc.headers.get("Set-Cookie", "")


def main() -> None:
    phone = f"138{secrets.randbelow(10**8):08d}"
    password = "TestPass123!"
    print(f"==> 注册测试用户 {phone}")
    status, reg, cookie = request(
        "POST",
        "/api/auth/register",
        {
            "phone": phone,
            "wechat": "pay_test",
            "org": "本地支付测试",
            "password": password,
            "contract_accepted": True,
        },
    )
    if status not in (200, 201):
        print("注册失败:", status, reg)
        return
    session = cookie.split(";")[0] if cookie else ""
    print("注册成功, user:", reg.get("user", {}).get("org"))

    print("==> 创建 trial_001 微信 Native 订单")
    status, order, _ = request(
        "POST",
        "/api/payment/wechat/native/create",
        {"plan_id": "trial_001", "contract_accepted": True},
        cookie=session,
    )
    print("HTTP", status)
    print(json.dumps(order, ensure_ascii=False, indent=2))
    if status in (200, 201) and order.get("code_url"):
        print("\nOK: 已拿到 code_url，本地微信支付链路正常。")
    else:
        print("\nFAIL: 未拿到 code_url。")


if __name__ == "__main__":
    main()
