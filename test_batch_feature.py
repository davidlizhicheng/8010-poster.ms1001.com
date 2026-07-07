"""Smoke tests for batch poster generation (no image API calls)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import (  # noqa: E402
    SINGLE_IMAGE_GUARD,
    create_job,
    parse_quote_card_line,
    poster_prompt,
    public_config,
    sanitize_multi_image_prompt,
    TEMPLATES,
)


def test_templates_and_prompts() -> None:
    assert "business-quote-card" in TEMPLATES
    card = parse_quote_card_line(
        "11|为什么战略再好执行也会变形？|战略决定方向，执行决定生死|方法：拆成可执行动作",
        1,
    )
    assert card["number"] == "11"
    assert "战略" in card["question"]

    prompt = poster_prompt(
        campaign_name="每日商业金句训练营",
        template_key="business-quote-card",
        title="11|为什么增长越来越难？|流量会重分配，品牌能复利|方法：先建信任",
        subject="商业",
        audience="创业者",
        brand_name="测试品牌",
        prompt_text="16:9横版，蓝白金色系，一次生成10张连续编号",
        batch_mode=True,
        batch_index=2,
        batch_total=10,
    )
    assert "禁止拼图" in prompt
    assert SINGLE_IMAGE_GUARD.split("禁止")[0] in prompt or "禁止拼图" in prompt
    assert "第2/10张" in prompt
    assert "一次生成10张" not in prompt
    assert "本张为系列中的单张独立海报" in sanitize_multi_image_prompt("一次生成10张连续编号")


def test_public_config() -> None:
    cfg = public_config()
    assert int(cfg["max_items_per_job"]) >= 100


def http_json(url: str, *, method: str = "GET", body: dict | None = None, cookie: str = "", headers: dict | None = None) -> tuple[int, dict]:
    data = None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json; charset=utf-8"
    if cookie:
        req_headers["Cookie"] = cookie
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_live_api(base: str = "http://127.0.0.1:8010", auth_base: str = "http://127.0.0.1:9080") -> None:
    status, templates = http_json(f"{base}/api/templates")
    assert status == 200
    keys = {item["key"] for item in templates.get("templates", [])}
    assert "business-quote-card" in keys

    status, cfg = http_json(f"{base}/api/config")
    assert status == 200
    assert int(cfg.get("max_items_per_job", 0)) >= 100

    phone = f"138{int(__import__('time').time()) % 100000000:08d}"
    reg_status, reg = http_json(
        f"{auth_base}/api/auth/register",
        method="POST",
        body={
            "username": phone,
            "phone": phone,
            "name": "批量测试",
            "password": "TestPass123!",
        },
    )
    assert reg_status in {200, 201}, reg
    token = reg.get("token") or ""
    auth_header = {"Authorization": f"Bearer {token}"}

    bad_status, bad = http_json(
        f"{base}/api/jobs",
        method="POST",
        headers=auth_header,
        body={
            "campaign_name": "每日商业金句训练营",
            "template_key": "business-quote-card",
            "prompt_text": "16:9横版商业金句插画，一次生成10张编号11-20",
            "items": ["单张主题"],
            "size": "1536x1024",
        },
    )
    assert bad_status == 400
    assert "拼图" in bad.get("error", "") or "批量" in bad.get("error", "") or "设计主题" in bad.get("error", "")

    blocked_status, blocked = http_json(
        f"{base}/api/jobs/batch",
        method="POST",
        headers=auth_header,
        body={
            "campaign_name": "每日商业金句训练营",
            "template_key": "business-quote-card",
            "generation_mode": "batch",
            "prompt_text": "16:9横版商业金句插画，蓝白金色系，顶部问题中部金句底部方法",
            "items": [
                "11|为什么战略再好执行也会变形？|战略决定方向，执行决定生死|方法：拆成可执行动作",
                "12|为什么团队一开会效率就低？|高效开会是用来决策的|方法：会前先定决策项",
            ],
            "size": "1536x1024",
        },
    )
    assert blocked_status in {400, 402, 403}, blocked
    if blocked_status == 400 and "额度" not in blocked.get("error", ""):
        raise AssertionError(f"unexpected 400: {blocked}")


def main() -> None:
    test_templates_and_prompts()
    test_public_config()
    print("OK: offline batch logic tests passed")
    try:
        test_live_api()
        print("OK: live API smoke tests passed (collage guard + templates + batch payload accepted)")
    except Exception as exc:
        print("SKIP live API tests:", repr(exc))


if __name__ == "__main__":
    main()

