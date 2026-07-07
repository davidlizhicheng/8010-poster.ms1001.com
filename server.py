from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import hmac
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from poster_platform import (
    active_credit_bucket_count,
    admin_dashboard,
    approve_payment_claim,
    ensure_platform_tables,
    ensure_default_admin,
    ensure_user_from_unified_auth,
    get_generation_metrics,
    get_slot_status,
    get_user_by_token,
    halt_payment_claim,
    increment_slot_attempt,
    list_admin_events,
    list_invoice_eligible_payments,
    list_user_payments,
    list_user_credit_buckets,
    login_user,
    logout_token,
    parse_reference_images_list,
    payment_qr_for_plan,
    payment_screenshot_path,
    prompt_key,
    public_platform_config,
    prune_expired_sessions,
    register_user,
    reject_payment_claim,
    refund_credit_bucket,
    release_slot_credit,
    consume_batch_credits,
    resolve_slot,
    rollback_pack_modify_credit,
    save_reference_images,
    submit_invoice_request,
    create_wechat_native_payment,
    handle_wechat_pay_notify,
    sync_wechat_payment_status,
    submit_payment_claim,
    update_invoice_status,
    usage_summary,
    verify_auth_stack,
    wechat_pay_ready,
)

ROOT = Path(__file__).resolve().parent
SESSION_COOKIE = "poster_session"
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
DB_PATH = DATA_DIR / "poster.db"
CONFIG_PATH = DATA_DIR / "config.json"


def load_dotenv() -> None:
    """Load KEY=VALUE pairs from .env files without overwriting existing env vars."""
    candidates = [
        ROOT / ".env",
        ROOT.parent / "Gaokao" / ".env",
        ROOT.parent / "brand" / "ip-card-ai" / ".env",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            continue
        break


load_dotenv()


class LoginRequired(Exception):
    pass


class AdminRequired(Exception):
    pass


DEFAULT_CONFIG = {
    "base_url": "https://api.fenno.ai/v1",
    "api_key": "",
    "image_model": "gpt-image-2",
    "size": "1024x1536",
    "quality": "medium",
    "background": "opaque",
    "output_format": "png",
    "output_compression": 80,
    "unit_cost": 1.35,
    "suggested_price": 9.9,
    "brand_name": "AI品牌广告图文设计师与知识地图设计师",
    "max_items_per_job": 100,
    "auth_base_url": "https://ai.ms1001.com",
    "central_billing_url": "",
    "use_unified_auth": True,
    "minimax_base_url": "https://api.minimax.chat/v1",
    "minimax_api_key": "",
    "minimax_model": "MiniMax-M3",
}

POSTER_SIZE_OPTIONS = [
    {"value": "1024x1536", "label": "竖版海报", "note": "1024 x 1536"},
    {"value": "1024x1024", "label": "方形海报", "note": "1024 x 1024"},
    {"value": "1536x1024", "label": "横版封面", "note": "1536 x 1024"},
    {"value": "auto", "label": "自动匹配", "note": "由模型决定"},
    {"value": "custom", "label": "自定义尺寸", "note": "手动输入宽高"},
]
PRESET_IMAGE_SIZES = {item["value"] for item in POSTER_SIZE_OPTIONS if item["value"] != "custom"}
CUSTOM_SIZE_PATTERN = re.compile(r"^(\d{3,4})x(\d{3,4})$", re.I)
IMAGE_SIZE_RULES = {
    "min_pixels": 655_360,
    "max_pixels": 8_294_400,
    "max_side": 3840,
    "multiple": 16,
    "max_ratio": 3,
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)


def db() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS poster_jobs (
            id TEXT PRIMARY KEY,
            campaign_name TEXT NOT NULL,
            template_key TEXT NOT NULL,
            subject TEXT,
            audience TEXT,
            status TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            unit_cost REAL NOT NULL,
            suggested_price REAL NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS poster_items (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            title TEXT NOT NULL,
            prompt TEXT NOT NULL,
            status TEXT NOT NULL,
            image_path TEXT,
            error TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(job_id) REFERENCES poster_jobs(id)
        )
        """
    )
    ensure_platform_tables(conn)
    for statement in (
        "ALTER TABLE poster_jobs ADD COLUMN duration_ms INTEGER DEFAULT 0",
        "ALTER TABLE poster_jobs ADD COLUMN reference_count INTEGER DEFAULT 0",
        "ALTER TABLE poster_items ADD COLUMN duration_ms INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(statement)
            conn.commit()
        except sqlite3.OperationalError:
            pass
    return conn


def load_config(mask: bool = False) -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            config.update({k: v for k, v in saved.items() if v is not None})
        except json.JSONDecodeError:
            pass
    if mask and config.get("api_key"):
        key = str(config["api_key"])
        config["api_key"] = key[:6] + "..." + key[-4:]
        config["has_key"] = True
    else:
        config["has_key"] = bool(config.get("api_key"))
    env_auth = os.getenv("AUTH_BASE_URL", "").strip()
    if env_auth:
        config["auth_base_url"] = env_auth.rstrip("/")
    return config


def central_billing_url_resolved() -> str:
    return f"{public_auth_base_url()}/billing"


def public_config() -> dict[str, Any]:
    config = load_config(mask=False)
    metrics: dict[str, Any] = {}
    try:
        conn = db()
        metrics = get_generation_metrics(conn)
        conn.close()
    except Exception:
        pass
    platform = public_platform_config(config, metrics)
    auth_base = public_auth_base_url()
    use_unified = config.get("use_unified_auth")
    if use_unified is None:
        use_unified = DEFAULT_CONFIG["use_unified_auth"]
    minimax_key = str(config.get("minimax_api_key") or os.getenv("MINIMAX_API_KEY") or "").strip()
    explicit_billing = str(config.get("central_billing_url") or "").strip().rstrip("/")
    if use_unified:
        billing_url = central_billing_url_resolved()
    elif explicit_billing and not is_loopback_url(explicit_billing):
        billing_url = explicit_billing
    elif explicit_billing:
        billing_url = f"{auth_base}/billing"
    else:
        billing_url = str(DEFAULT_CONFIG.get("central_billing_url") or "").strip()
    return {
        "brand_name": platform["brand_name"],
        "image_model": config.get("image_model") or DEFAULT_CONFIG["image_model"],
        "size": normalize_config_size(config.get("size")),
        "size_options": POSTER_SIZE_OPTIONS,
        "size_rules": IMAGE_SIZE_RULES,
        "central_billing_url": billing_url,
        "unified_auth_url": auth_base,
        "use_unified_auth": bool(use_unified),
        "minimax_ready": bool(minimax_key),
        "max_items_per_job": int(config.get("max_items_per_job") or DEFAULT_CONFIG["max_items_per_job"]),
        **platform,
    }


def is_loopback_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(str(url or "")).hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "::1"}
    except Exception:
        return False


def public_auth_base_url() -> str:
    """URL exposed to browsers — never leak 127.0.0.1 on public sites."""
    env = os.getenv("AUTH_BASE_URL", "").strip().rstrip("/")
    config = load_config(mask=False)
    cfg_url = str(config.get("auth_base_url") or DEFAULT_CONFIG["auth_base_url"]).strip().rstrip("/")
    if env and not is_loopback_url(env):
        return env
    if cfg_url and not is_loopback_url(cfg_url):
        return cfg_url
    return "https://ai.ms1001.com"


def auth_base_url() -> str:
    env = os.getenv("AUTH_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    config = load_config(mask=False)
    return str(config.get("auth_base_url") or DEFAULT_CONFIG["auth_base_url"]).rstrip("/")


def unified_auth_enabled() -> bool:
    config = load_config(mask=False)
    value = config.get("use_unified_auth")
    if value is None:
        return bool(DEFAULT_CONFIG["use_unified_auth"])
    return bool(value)


def verify_unified_token_remote(token: str) -> dict[str, Any] | None:
    base = auth_base_url()
    if is_loopback_url(base):
        base = public_auth_base_url()
    url = f"{base}/api/auth/verify"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("valid"):
            return None
        user = data.get("user") or {}
        claims = data.get("claims") or {}
        return {
            "username": user.get("username") or claims.get("sub"),
            "name": user.get("name") or "",
            "phone": user.get("phone") or user.get("username") or "",
            "role": user.get("role") or claims.get("role") or "USER",
            "tier": user.get("tier") or claims.get("tier") or "standard",
            "isOwner": user.get("isOwner") if user.get("isOwner") is not None else claims.get("isOwner"),
            "platformPermissions": user.get("platformPermissions") or claims.get("platformPermissions") or {},
            "platformMemberships": user.get("platformMemberships") or claims.get("platformMemberships") or {},
        }
    except Exception:
        return verify_unified_jwt(token)


def resolve_unified_claims(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
    if not unified_auth_enabled():
        return None
    token = unified_token(handler)
    if not token:
        return None
    claims = verify_unified_token_remote(token)
    if not claims:
        return None
    phone = str(claims.get("phone") or "").strip()
    username = str(claims.get("username") or claims.get("sub") or "").strip()
    if not phone and re.fullmatch(r"1\d{10}", username):
        claims = {**claims, "phone": username}
    elif phone:
        digits = re.sub(r"\D", "", phone)
        if re.fullmatch(r"1\d{10}", digits):
            claims = {**claims, "phone": digits}
    return claims


def resolve_authenticated_user(handler: BaseHTTPRequestHandler) -> dict[str, Any] | None:
    conn = db()
    try:
        claims = resolve_unified_claims(handler)
        if claims:
            user, _created = ensure_user_from_unified_auth(conn, claims)
            conn.commit()
            return user
        user = get_user_by_token(conn, session_token(handler))
        return user
    finally:
        conn.close()


def cors_origin(handler: BaseHTTPRequestHandler) -> str | None:
    origin = (handler.headers.get("Origin") or "").strip()
    if not origin:
        return None
    if origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:"):
        return origin
    try:
        from urllib.parse import urlparse

        host = urlparse(origin).hostname or ""
        if host == "ms1001.com" or host.endswith(".ms1001.com"):
            return origin
    except Exception:
        pass
    auth = auth_base_url()
    if origin.rstrip("/") == auth:
        return origin
    return None


def cors_headers(handler: BaseHTTPRequestHandler) -> list[tuple[str, str]]:
    origin = cors_origin(handler)
    if not origin:
        return []
    return [
        ("Access-Control-Allow-Origin", origin),
        ("Access-Control-Allow-Credentials", "true"),
        ("Access-Control-Allow-Headers", "Content-Type, Authorization"),
        ("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS"),
    ]


def image_size_error_message() -> str:
    return "自定义尺寸需写成 宽x高，宽高为 16 的倍数，最长边不超过 3840，长短边比例不超过 3:1，总像素在 655360 到 8294400 之间。"


def is_valid_image_size(value: str) -> bool:
    size = str(value or "").strip().lower()
    if size in PRESET_IMAGE_SIZES:
        return True
    match = CUSTOM_SIZE_PATTERN.match(size)
    if not match:
        return False
    width, height = int(match.group(1)), int(match.group(2))
    pixels = width * height
    ratio = max(width, height) / min(width, height)
    return (
        width % IMAGE_SIZE_RULES["multiple"] == 0
        and height % IMAGE_SIZE_RULES["multiple"] == 0
        and max(width, height) <= IMAGE_SIZE_RULES["max_side"]
        and ratio <= IMAGE_SIZE_RULES["max_ratio"]
        and IMAGE_SIZE_RULES["min_pixels"] <= pixels <= IMAGE_SIZE_RULES["max_pixels"]
    )


def resolve_image_size(value: Any, default: str | None = None) -> str:
    size = str(value or "").strip().lower()
    fallback = str(default or DEFAULT_CONFIG["size"]).strip().lower()
    if size:
        if is_valid_image_size(size):
            return size
        raise ValueError(image_size_error_message())
    if is_valid_image_size(fallback):
        return fallback
    return DEFAULT_CONFIG["size"]


def normalize_config_size(value: Any) -> str:
    size = str(value or "").strip().lower()
    if is_valid_image_size(size):
        return size
    return DEFAULT_CONFIG["size"]


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    current = load_config(mask=False)
    allowed = set(DEFAULT_CONFIG)
    for key in allowed:
        if key in data:
            value = data[key]
            if key in {"unit_cost", "suggested_price"}:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    value = DEFAULT_CONFIG[key]
            elif key == "output_compression":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = DEFAULT_CONFIG[key]
            elif key == "size":
                value = resolve_image_size(value)
            current[key] = value
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_config(mask=True)


TEMPLATES: dict[str, dict[str, str]] = {
    "study-card": {
        "name": "学习训练卡",
        "style": "红金蓝品牌配色，清晰卡片分区，适合社群转发与家长分享",
        "structure": "题目区、要点提示、纠错思路、规范答案、关键提醒、变式训练",
    },
    "course-sale": {
        "name": "课程推广海报",
        "style": "高端品牌感，红金主视觉，强标题与大利益点，适合朋友圈和社群转化",
        "structure": "课程主题、适合人群、三大收获、限时权益、行动按钮、信任背书",
    },
    "community": {
        "name": "社群裂变海报",
        "style": "热闹但高级的活动视觉，红金冲击力，明确扫码转化位，适合微信群传播",
        "structure": "活动名、参与理由、奖励机制、时间、扫码位、传播口号",
    },
    "festival": {
        "name": "节日促销海报",
        "style": "节庆礼盒感，金色纸张质感，红色标题，适合促销和会员活动",
        "structure": "节日主题、核心优惠、产品亮点、倒计时、购买理由、行动按钮",
    },
    "brand-event": {
        "name": "品牌活动海报",
        "style": "庄重、科技、红金蓝，适合发布会、门店活动、品牌日",
        "structure": "活动主题、主视觉口号、核心议程、嘉宾/亮点、时间地点、报名提示",
    },
    "social-cover": {
        "name": "自媒体封面配图",
        "style": "竖版信息流视觉，标题醒目，适合短视频封面、社群配图与广告图",
        "structure": "主标题、副标题、人物/产品焦点、品牌标识、行动引导",
    },
    "flyer-print": {
        "name": "宣传单折页主视觉",
        "style": "印刷级排版，信息分区明确，适合招生宣传单、产品折页与画册封面",
        "structure": "主标题、核心卖点、服务模块、联系方式、二维码位",
    },
    "product-poster": {
        "name": "产品宣传海报",
        "style": "产品特写与场景结合，商业质感，适合新品发布与促销主视觉",
        "structure": "产品名、核心卖点、价格/权益、使用场景、购买理由",
    },
    "recruitment": {
        "name": "招聘招募海报",
        "style": "专业可信，层次清晰，适合企业招聘与团队招募",
        "structure": "岗位/团队名、核心要求、福利待遇、工作地点、报名方式",
    },
    "exhibition": {
        "name": "展会展架物料",
        "style": "远距离可读大标题，品牌色统一，适合易拉宝、展架与签到背景",
        "structure": "展会主题、参展亮点、时间地点、展位号、品牌标识",
    },
    "menu-price": {
        "name": "菜单价目表",
        "style": "整洁分区，价格突出，适合门店菜单、服务价目与套餐清单",
        "structure": "品类分区、项目名称、价格、备注说明、品牌页脚",
    },
    "certificate": {
        "name": "证书奖状",
        "style": "庄重典雅，边框装饰，适合荣誉证书、结业证书与活动奖状",
        "structure": "证书标题、授予对象、成就描述、颁发单位、日期落款",
    },
    "invitation": {
        "name": "邀请函",
        "style": "精致礼仪感，适合活动邀请、会议邀请与开业邀请",
        "structure": "邀请标题、活动主题、时间地点、着装/流程提示、回执方式",
    },
    "ecommerce": {
        "name": "电商主图详情图",
        "style": "商品突出、卖点标签化，适合电商主图、详情首图与促销图",
        "structure": "商品名、核心卖点标签、价格权益、促销信息、品牌标识",
    },
    "office-infographic": {
        "name": "职场信息长图",
        "style": "信息图解风格，流程清晰，适合汇报封面、流程说明与政策解读",
        "structure": "主题标题、分步模块、数据要点、总结结论、页脚标识",
    },
    "speech-outline": {
        "name": "演讲提纲",
        "style": "竖版信息图与演讲稿大纲结合，层级清晰，适合会议发言、课程分享和路演提纲",
        "structure": "演讲主题、开场观点、3-5个核心章节、关键论据、收尾金句、行动提醒",
    },
    "edu-illustration": {
        "name": "科普教育图解",
        "style": "知识图解与示意风格，清晰易懂，适合科普配图与安全宣教",
        "structure": "主题标题、知识模块、示意图示、要点总结、来源标注",
    },
    "ip-creative": {
        "name": "IP 文创视觉",
        "style": "角色/IP 延展，趣味与品牌感兼具，适合吉祥物、贴纸与周边概念",
        "structure": "IP 角色、场景延展、产品应用示意、品牌 slogan",
    },
    "livestream-bg": {
        "name": "直播间背景",
        "style": "竖版场景氛围，留出主播区域，适合直播背景与虚拟场景",
        "structure": "品牌主视觉、氛围装饰、产品陈列区、活动信息条",
    },
    "spatial-scene": {
        "name": "空间虚拟效果图",
        "style": "空间透视与氛围光，适合展厅、门店与活动空间概念展示",
        "structure": "空间主题、功能分区、氛围元素、品牌植入、尺寸示意",
    },
    "custom-vertical": {
        "name": "细分定制竖版",
        "style": "高度定制化竖版视觉，适合婚礼、宠物、文创等个性场景",
        "structure": "主题定制、情感表达、场景元素、个性化文案、品牌点缀",
    },
    "business-quote-card": {
        "name": "商业金句卡片",
        "style": "16:9横版商业金句插画，蓝白金色系，授课展览场景，一问一答结构",
        "structure": "顶部引导问题、中部加粗金句（关键字高亮）、底部方法论条、左上角编号",
    },
}

SINGLE_IMAGE_GUARD = (
    "【硬性输出要求】只生成一张完整海报，占满整个画布。"
    "禁止拼图、禁止多宫格、禁止分屏、禁止一张图里出现多个编号或多种版式。"
    "禁止把多张海报拼在一起。"
)

COLLAGE_TRIGGER_RE = re.compile(
    r"(一次生成|一次性生成|同时生成|合并输出|拼图|组图|宫格|"
    r"(\d+)\s*张(?:连续|编号)?|每张独立画面[^，。]*但)"
)


def sanitize_multi_image_prompt(prompt_text: str) -> str:
    """Remove wording that makes image models output collages."""
    text = str(prompt_text or "").strip()
    if not text:
        return text
    text = COLLAGE_TRIGGER_RE.sub("本张为系列中的单张独立海报", text)
    text = re.sub(r"输出[：:]\s*一次生成.*?图集", "输出：单张独立海报", text)
    return text


def parse_quote_card_line(title: str, batch_index: int) -> dict[str, str]:
    raw = str(title or "").strip()
    parts = [part.strip() for part in raw.split("|") if part.strip()]
    if len(parts) >= 4:
        return {
            "number": parts[0],
            "question": parts[1],
            "quote": parts[2],
            "method": parts[3],
        }
    if len(parts) == 3:
        return {
            "number": str(batch_index).zfill(2),
            "question": parts[0],
            "quote": parts[1],
            "method": parts[2],
        }
    number_match = re.match(r"^(\d{1,3})\s*[.、:：\-]\s*(.+)$", raw)
    if number_match:
        return {
            "number": number_match.group(1).zfill(2),
            "question": number_match.group(2).strip(),
            "quote": "",
            "method": "",
        }
    return {
        "number": str(batch_index).zfill(2),
        "question": raw,
        "quote": "",
        "method": "",
    }


def poster_prompt(
    *,
    campaign_name: str,
    template_key: str,
    title: str,
    subject: str,
    audience: str,
    brand_name: str,
    prompt_text: str = "",
    modify_notes: str = "",
    modification_index: int = 1,
    batch_mode: bool = False,
    batch_index: int = 1,
    batch_total: int = 1,
) -> str:
    template = TEMPLATES.get(template_key, TEMPLATES["study-card"])
    def short(value: str, limit: int) -> str:
        text = str(value or "").strip()
        return text[:limit] if text else ""

    campaign = short(campaign_name, 14) or short(brand_name, 14)
    title_raw = str(title or "").strip()
    title_text = short(title_raw, 120 if batch_mode else 22)
    subject_text = short(subject, 14) or "商业服务"
    audience_text = short(audience, 14) or "目标客户"
    template_name = short(template["name"], 10)
    structure_text = short(template["structure"], 32)
    prompt_extra = short(sanitize_multi_image_prompt(prompt_text), 280 if batch_mode else 180)
    if template_key == "business-quote-card":
        card = parse_quote_card_line(title_raw, batch_index)
        question = short(card["question"], 36)
        quote = short(card["quote"], 48) or question
        method = short(card["method"], 36)
        base = (
            f"单张16:9横版商业金句插画海报，编号{card['number']}。"
            f"系列:{campaign}。{SINGLE_IMAGE_GUARD}"
            f"固定版式：顶部引导问题「{question}」；"
            f"中部最大字号加粗金句「{quote}」，关键字用高亮色；"
            f"底部方法论条「{method}」。"
            f"真实商业场景插画（授课/展览/教导），风格专业。"
        )
    elif template_key == "speech-outline":
        base = (
            f"竖版中文演讲提纲信息图。项目:{campaign}。主题:{title_text}。"
            f"领域:{subject_text}。受众:{audience_text}。内容:{structure_text}。"
            f"层级清晰，含主标题、3-5个章节、关键要点、收尾总结和页脚标识。"
            f"{SINGLE_IMAGE_GUARD}"
        )
    else:
        base = (
            f"竖版中文商业海报。项目:{campaign}。主题:{title_text}。"
            f"类型:{template_name}。领域:{subject_text}。受众:{audience_text}。"
            f"内容:{structure_text}。大标题清晰，含行动按钮和二维码占位。"
            f"{SINGLE_IMAGE_GUARD}"
        )
    if prompt_extra:

        base += f"用户提示词：{prompt_extra}。"

    if batch_mode and batch_total > 1:
        base += (
            f"同系列海报第{batch_index}/{batch_total}张。"
            "整套系列必须统一视觉风格：相同主配色、字体气质、版式结构、装饰元素和留白节奏，"
            "仅更换本张主题文案与对应内容模块。"
            f"{SINGLE_IMAGE_GUARD}"
        )
        if batch_index > 1:
            base += (
                "严格参照系列首张成品的视觉风格，只改标题与内容，不要换风格。"
                "参考图（若有）是系列首张的真实成图，必须保持相同布局结构、主配色、字体气质与装饰元素。"
            )

    if modification_index > 1:
        base += f"第 {modification_index} 次优化，保持主题不变。"
    notes = str(modify_notes or "").strip()
    if notes:
        base += f"修改要求：{notes[:80]}。"
    return base


def load_slot_base_image(conn: sqlite3.Connection, slot_id: str, user_id: str) -> bytes | None:
    row = conn.execute(
        """
        SELECT pi.image_path FROM poster_items pi
        JOIN poster_jobs pj ON pj.id = pi.job_id
        WHERE pj.slot_id = ? AND pj.user_id = ?
          AND pi.status = 'completed' AND pi.image_path IS NOT NULL AND pi.image_path != ''
        ORDER BY pi.created_at DESC LIMIT 1
        """,
        (slot_id, user_id),
    ).fetchone()
    if not row:
        return None
    rel = str(row["image_path"]).removeprefix("/outputs/")
    path = OUTPUT_DIR / rel
    if path.is_file():
        return path.read_bytes()
    return None


def join_url(base: str, next_path: str) -> str:
    return base.rstrip("/") + "/" + next_path.lstrip("/")


def _ssl_available() -> bool:
    try:
        import _ssl  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_https_client() -> None:
    """CentOS7 源码 Python 若未编译 SSL，改用 curl 访问 HTTPS。"""
    if _ssl_available():
        return
    curl = shutil_which("curl")
    if curl:
        print(
            "警告: 当前 Python 未编译 SSL 模块(_ssl)，HTTPS 请求将使用 curl。"
            "建议稍后执行: bash deploy/rebuild-python-ssl.sh",
            flush=True,
        )
        return
    raise RuntimeError(
        "当前 Python 无 SSL 模块且系统无 curl，无法调用 HTTPS 图片接口。"
        "请执行: yum install -y curl openssl-devel && bash deploy/rebuild-python-ssl.sh"
    )


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 240,
) -> tuple[int, bytes]:
    headers = headers or {}
    use_curl = url.lower().startswith("https://") and not _ssl_available()
    if not use_curl:
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return int(resp.status or 200), resp.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read()
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            if "unknown url type" not in reason.lower() and "ssl" not in reason.lower():
                raise RuntimeError(f"无法连接图片接口: {reason}") from exc
            use_curl = True

    if use_curl:
        curl = shutil_which("curl")
        if not curl:
            raise RuntimeError("无法连接图片接口: Python 无 SSL 且系统无 curl")
        cmd = [curl, "-sS", "-X", method, url, "--max-time", str(timeout), "-w", "%{http_code}"]
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        if body is not None:
            cmd.extend(["--data-binary", "@-"])
        proc = subprocess.run(
            cmd,
            input=body,
            capture_output=True,
            timeout=timeout + 30,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip() or "curl 请求失败"
            raise RuntimeError(f"无法连接图片接口: {err}")
        out = proc.stdout
        if len(out) < 3:
            raise RuntimeError("图片接口返回为空")
        code = int(out[-3:].decode("ascii", errors="replace") or "0")
        return code, out[:-3]

    raise RuntimeError("无法连接图片接口")


def image_endpoint(base_url: str, *, edit: bool = False) -> str:
    base = str(base_url or DEFAULT_CONFIG["base_url"]).strip()
    action = "edits" if edit else "generations"
    other_action = "generations" if edit else "edits"
    if base.endswith(f"/images/{action}"):
        return base
    if base.endswith(f"/images/{other_action}"):
        return base.rsplit("/", 1)[0] + f"/{action}"
    if base.endswith("/v1"):
        return join_url(base, f"images/{action}")
    if base.endswith("/v1/images"):
        return join_url(base, action)
    return join_url(base, f"v1/images/{action}")


def _guess_image_mime(buffer: bytes) -> str:
    if buffer.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if buffer.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if buffer.startswith(b"RIFF") and buffer[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _multipart_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def build_multipart_image_edit(
    fields: dict[str, Any],
    reference_images: list[bytes],
    *,
    file_field_name: str = "image[]",
) -> tuple[bytes, str]:
    boundary = f"----posterBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        if value is None:
            continue
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            f'Content-Disposition: form-data; name="{_multipart_escape(str(key))}"\r\n\r\n'.encode("utf-8")
        )
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for index, image in enumerate(reference_images):
        mime = _guess_image_mime(image)
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        filename = f"reference_{index}.{ext}"
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{_multipart_escape(file_field_name)}"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(image)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def parse_provider_error(body: str) -> str:
    try:
        parsed = json.loads(body)
        error = parsed.get("error")
        if isinstance(error, str):
            return error
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    except json.JSONDecodeError:
        pass
    return body


def ensure_base64(value: str) -> str:
    match = re.search(r"^data:[^;]+;base64,(.+)$", value)
    return match.group(1) if match else value


def image_prompt_candidates(prompt: str) -> list[str]:
    full = str(prompt or "").strip()
    compact = re.sub(r"[。；;]\s*", "，", full).strip("，")
    if len(compact) > 80:
        compact = compact[:80].rstrip("，。；; ") + "。"
    fallback = "生成一张竖版中文演讲提纲信息图，要有主标题、3到5个章节、关键要点和收尾总结。" if "演讲提纲" in full else "生成一张竖版中文商业海报，要有大标题、行动按钮和二维码占位。"
    candidates: list[str] = []
    for item in (full, compact, fallback):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def call_image_api(
    prompt: str,
    config: dict[str, Any],
    reference_images: list[bytes] | None = None,
) -> bytes:
    api_key = config.get("api_key") or os.getenv("POSTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("后端尚未配置图片 API Key。请在 data/config.json 或 POSTER_API_KEY 环境变量中配置。")

    model = str(config.get("image_model") or DEFAULT_CONFIG["image_model"])
    output_format = str(config.get("output_format") or DEFAULT_CONFIG["output_format"])
    payload_base: dict[str, Any] = {
        "model": model,
        "size": config.get("size") or DEFAULT_CONFIG["size"],
        "quality": config.get("quality") or DEFAULT_CONFIG["quality"],
        "background": config.get("background") or DEFAULT_CONFIG["background"],
        "output_format": output_format,
        "n": 1,
    }
    if output_format in {"jpeg", "webp"}:
        payload_base["output_compression"] = int(
            config.get("output_compression") or DEFAULT_CONFIG["output_compression"]
        )
    if model.startswith("dall-e"):
        payload_base["response_format"] = "b64_json"

    has_reference_images = bool(reference_images)
    endpoint = image_endpoint(
        str(config.get("base_url") or DEFAULT_CONFIG["base_url"]),
        edit=has_reference_images,
    )
    headers_base = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    last_error: Exception | None = None
    data: dict[str, Any] | None = None
    for prompt_index, prompt_item in enumerate(image_prompt_candidates(prompt)):
        payload = dict(payload_base)
        payload["prompt"] = f"{prompt_item}\n\n{SINGLE_IMAGE_GUARD}"
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {**headers_base, "Content-Type": "application/json"}
        if has_reference_images:
            payload["prompt"] = (
                f"{prompt_item}\n\n"
                f"{SINGLE_IMAGE_GUARD}\n\n"
                "MANDATORY IMAGE REFERENCE RULES: Use the uploaded image(s) as real visual references. "
                "The final poster must be recognizably related to the input image content: preserve the main "
                "subject, product/person/logo/scene cues, important colors, and composition unless the user "
                "explicitly asks to change them. Do not ignore the image, do not invent an unrelated poster, "
                "and do not replace the core subject with a generic stock-style subject. "
                "If the reference shows ONE poster layout, output ONE poster only — never tile multiple posters."
            )
            body_bytes, content_type = build_multipart_image_edit(payload, reference_images or [])
            headers = {**headers_base, "Content-Type": content_type}
        max_attempts = 2 if prompt_index < 2 else 3
        for attempt in range(max_attempts):
            try:
                status, raw = _http_request(
                    endpoint,
                    method="POST",
                    headers=headers,
                    body=body_bytes,
                    timeout=240,
                )
                if status >= 400:
                    message = parse_provider_error(raw.decode("utf-8", errors="replace"))
                    last_error = RuntimeError(f"图片接口返回 {status}: {message[:500]}")
                    if status in {403, 429, 502, 503, 504} and attempt < max_attempts - 1:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise last_error
                data = json.loads(raw.decode("utf-8"))
                last_error = None
                break
            except (RuntimeError, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                break
        if data is not None:
            break

    if data is None:
        raise RuntimeError(f"图片接口连接不稳定，完整提示词与保底提示词均未成功：{last_error}")

    image_data = (data.get("data") or [{}])[0]
    if image_data.get("b64_json"):
        return base64.b64decode(ensure_base64(str(image_data["b64_json"]).strip()))
    if image_data.get("url"):
        img_url = str(image_data["url"])
        _, img_bytes = _http_request(img_url, timeout=240)
        return img_bytes
    raise RuntimeError("图片接口未返回 b64_json 或 url。")


def extract_chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part).strip()
    if isinstance(data.get("reply"), str):
        return str(data["reply"]).strip()
    return ""


def call_minimax_prompt_api(command: str, context: dict[str, str], config: dict[str, Any]) -> str:
    api_key = config.get("minimax_api_key") or os.getenv("MINIMAX_API_KEY", "")
    if not api_key:
        raise RuntimeError("尚未配置 Minimax API Key，请在 MINIMAX_API_KEY 环境变量或 data/config.json 中配置。")
    base_url = str(
        os.getenv("MINIMAX_BASE_URL")
        or config.get("minimax_base_url")
        or DEFAULT_CONFIG["minimax_base_url"]
    ).rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else join_url(base_url, "chat/completions")
    model = str(os.getenv("MINIMAX_MODEL") or config.get("minimax_model") or DEFAULT_CONFIG["minimax_model"])
    system_prompt = (
        "你是商业海报提示词总监。请把用户一句话需求改写成给 GPT-Image-2/Fenno 图片模型使用的中文最终提示词。"
        "只输出提示词正文，不要解释。要求：明确海报类型、主体、受众、构图、文字层级、配色、材质、镜头/插画风格、"
        "必须出现的中文文案、留白和二维码/行动按钮位置。输出一张完整海报，不要拼图，不要多张图。"
    )
    user_prompt = (
        f"用户命令：{command.strip()}\n"
        f"项目名称：{context.get('campaign_name') or '未指定'}\n"
        f"模板类型：{context.get('template_key') or '未指定'}\n"
        f"领域/科目：{context.get('subject') or '未指定'}\n"
        f"目标受众：{context.get('audience') or '未指定'}\n"
        f"尺寸：{context.get('size') or '未指定'}\n"
        "请生成可直接传给 GPT-Image-2 的最终提示词。"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 900,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    status, raw = _http_request(
        endpoint,
        method="POST",
        headers=headers,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=90,
    )
    if status >= 400:
        message = parse_provider_error(raw.decode("utf-8", errors="replace"))
        raise RuntimeError(f"Minimax 提示词接口返回 {status}: {message[:500]}")
    data = json.loads(raw.decode("utf-8"))
    text = extract_chat_text(data)
    if not text:
        raise RuntimeError("Minimax 未返回有效提示词。")
    return text[:1800]


def extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def call_minimax_batch_plan_api(command: str, context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    api_key = config.get("minimax_api_key") or os.getenv("MINIMAX_API_KEY", "")
    if not api_key:
        raise RuntimeError("尚未配置 Minimax API Key，请在 MINIMAX_API_KEY 环境变量或 data/config.json 中配置。")
    base_url = str(
        os.getenv("MINIMAX_BASE_URL")
        or config.get("minimax_base_url")
        or DEFAULT_CONFIG["minimax_base_url"]
    ).rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else join_url(base_url, "chat/completions")
    model = str(os.getenv("MINIMAX_MODEL") or config.get("minimax_model") or DEFAULT_CONFIG["minimax_model"])
    max_items = int(context.get("max_items") or DEFAULT_CONFIG["max_items_per_job"])
    requested_count = max(2, min(max_items, int(context.get("count") or 6)))
    system_prompt = (
        "你是商业海报系列策划总监。请把用户的一句话需求规划成多张独立海报，并为每张海报写出可交给 Fenno/GPT-Image-2 的中文图片提示词。"
        "必须只输出 JSON，不要 Markdown，不要解释。JSON 结构："
        "{\"series_style\":\"全系列统一视觉风格\",\"items\":[{\"title\":\"短标题\",\"prompt\":\"单张最终图片提示词\"}]}。"
        "要求：每张是一张独立海报，不是拼图；每张 prompt 要写清文案、构图、主视觉、配色、字体层级、留白、行动按钮或二维码位。"
        "全系列风格要统一，但每张内容要有明确差异。"
    )
    user_prompt = (
        f"用户需求：{command.strip()}\n"
        f"计划张数：{requested_count}\n"
        f"项目名称：{context.get('campaign_name') or '未指定'}\n"
        f"模板类型：{context.get('template_key') or '未指定'}\n"
        f"领域/科目：{context.get('subject') or '未指定'}\n"
        f"目标受众：{context.get('audience') or '未指定'}\n"
        f"尺寸：{context.get('size') or '未指定'}\n"
        f"最多允许：{max_items} 张。"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.72,
        "max_tokens": min(12000, max(2200, requested_count * 850)),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    status, raw = _http_request(
        endpoint,
        method="POST",
        headers=headers,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=120,
    )
    if status >= 400:
        message = parse_provider_error(raw.decode("utf-8", errors="replace"))
        raise RuntimeError(f"Minimax 批量规划接口返回 {status}: {message[:500]}")
    text = extract_chat_text(json.loads(raw.decode("utf-8")))
    if not text:
        raise RuntimeError("Minimax 未返回有效批量规划。")
    text = re.sub(r"<[^>]*thinking[^>]*>.*?</[^>]*thinking[^>]*>", "", text, flags=re.DOTALL | re.I).strip()
    try:
        plan = extract_json_object(text)
    except Exception as exc:
        raise RuntimeError("Minimax 批量规划不是有效 JSON，请重试。") from exc
    raw_items = plan.get("items") if isinstance(plan, dict) else []
    if not isinstance(raw_items, list):
        raise RuntimeError("Minimax 批量规划缺少 items。")
    items: list[dict[str, str]] = []
    for item in raw_items[:max_items]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if title and prompt:
            items.append({"title": title[:160], "prompt": prompt[:1800]})
    if len(items) < 2:
        raise RuntimeError("Minimax 至少需要规划 2 张海报。")
    return {
        "series_style": str(plan.get("series_style") or "").strip()[:1800],
        "items": items,
    }


def create_svg_preview(title: str, prompt: str) -> bytes:
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = [line.strip() for line in prompt.splitlines() if line.strip()][:6]
    body = "".join(
        f'<text x="72" y="{270 + i * 46}" font-size="28" fill="#32101a">{line[:26]}</text>'
        for i, line in enumerate(lines)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1536" viewBox="0 0 1024 1536">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#fff4df"/><stop offset="0.48" stop-color="#fffaf1"/><stop offset="1" stop-color="#d71920"/></linearGradient>
</defs>
<rect width="1024" height="1536" fill="url(#bg)"/>
<rect x="42" y="42" width="940" height="1452" rx="34" fill="rgba(255,255,255,.78)" stroke="#b40f1a" stroke-width="6"/>
<text x="72" y="136" font-size="38" font-weight="700" fill="#b40f1a">POSTER PREVIEW</text>
<text x="72" y="215" font-size="64" font-weight="900" fill="#1a1730">{safe_title[:16]}</text>
{body}
<rect x="72" y="1280" width="880" height="112" rx="24" fill="#b40f1a"/>
<text x="144" y="1351" font-size="38" font-weight="800" fill="#fff4df">配置 API Key 后一键生成正式海报</text>
</svg>""".encode("utf-8")


def create_job(data: dict[str, Any], user_id: str) -> dict[str, Any]:
    config = load_config(mask=False)
    campaign_name = (data.get("campaign_name") or f"自动项目-{time.strftime('%Y%m%d-%H%M')}").strip()
    template_key = (data.get("template_key") or "").strip() or "custom-vertical"
    subject = (data.get("subject") or "").strip()
    audience = (data.get("audience") or "").strip()
    slot_id = str(data.get("slot_id") or "").strip() or None
    is_modify_request = bool(data.get("modify")) or bool(slot_id)
    modify_notes = str(data.get("modify_notes") or "").strip()
    prompt_text = str(data.get("prompt_text") or "").strip()
    credit_bucket_id = str(data.get("credit_bucket_id") or "").strip() or None
    generation_mode = str(data.get("generation_mode") or "").strip().lower()

    planned_items = [
        item
        for item in (data.get("planned_items") or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    titles = [str(item).strip() for item in data.get("items", []) if str(item).strip()]
    if planned_items and not titles:
        titles = [str(item.get("title") or "").strip() for item in planned_items]
    if generation_mode == "batch":
        is_batch = True
    elif generation_mode == "single":
        is_batch = False
        if len(titles) > 1:
            titles = titles[:1]
    else:
        is_batch = len(titles) > 1

    if not titles:
        if is_batch:
            raise ValueError("请在系列清单中每行填写一张海报的主题（至少 2 行）。")
        titles = [(prompt_text[:28] or "未命名设计").strip()] if len(prompt_text) >= 2 else ["未命名设计"]

    max_items = int(config.get("max_items_per_job") or DEFAULT_CONFIG["max_items_per_job"])
    if len(titles) > max_items:
        raise ValueError(f"单次最多生成 {max_items} 张，请减少主题行数。")

    if not is_modify_request:
        if is_batch:
            if len(titles) < 2:
                raise ValueError("批量生成至少需要 2 行主题，每行一张独立海报。")
            if len(prompt_text) < 4:
                raise ValueError("请填写系列风格提示词，说明统一的配色、版式和结构。")
        else:
            title = titles[0]
            if len(prompt_text) < 4 and len(title) < 2:
                raise ValueError("请填写设计主题，或在补充说明中描述要生成的内容。")
            multi_image_intent = re.search(r"(\d+)\s*张", prompt_text)
            if multi_image_intent and int(multi_image_intent.group(1)) > 1:
                raise ValueError(
                    "检测到提示词要求一次生成多张海报，这容易输出拼图。"
                    "请切换到「批量生成」，在系列清单中每行填写一张的内容。"
                )

    requested_size = resolve_image_size(data.get("size"), config.get("size"))
    request_config = dict(config)
    if is_batch and (
        template_key == "business-quote-card"
        or any("|" in title for title in titles)
        or re.search(r"16\s*[：:]\s*9|16:9|横版|商业金句", prompt_text, re.I)
    ):
        if requested_size in PRESET_IMAGE_SIZES and requested_size not in {"1536x1024", "auto", "custom"}:
            requested_size = "1536x1024"
    elif not is_batch and (
        template_key == "business-quote-card" or re.search(r"16\s*[：:]\s*9|16:9|横版", prompt_text, re.I)
    ):
        if requested_size in PRESET_IMAGE_SIZES and requested_size not in {"1536x1024", "auto", "custom"}:
            requested_size = "1536x1024"
    request_config["size"] = requested_size

    if is_batch and is_modify_request:
        raise ValueError("批量生成不支持修改模式，请新建设计图后再批量提交。")

    conn = db()
    batch_credit_attempts: list[int] = []
    active_slot_id: str | None = None
    is_modify = False
    pack_credit_consumed = False
    slot_max_attempts = 5
    modification_index = 1

    if is_batch:
        if active_credit_bucket_count(conn, user_id) > 1 and not credit_bucket_id:
            conn.close()
            raise ValueError("您有多档可用额度，请先在生成页选择本次使用的套餐。")
        try:
            batch_credit_attempts = consume_batch_credits(conn, user_id, len(titles), credit_bucket_id)
        except ValueError as exc:
            conn.close()
            raise ValueError(str(exc) or "海报额度不足，请先购买套餐。") from exc
        conn.commit()
    else:
        title = titles[0]
        key = prompt_key(template_key, title, subject, audience)
        if is_modify_request and not slot_id:
            conn.close()
            raise ValueError("修改模式需要有效的主题会话，请从作品列表进入修改。")

        active_slot_id, is_modify, pack_credit_consumed = resolve_slot(
            conn, user_id, slot_id, key, credit_bucket_id
        )
        slot_row = conn.execute(
            "SELECT max_attempts, attempts_used FROM generation_slots WHERE id = ?", (active_slot_id,)
        ).fetchone()
        slot_max_attempts = int(slot_row["max_attempts"] or 5) if slot_row else 5
        modification_index = int(slot_row["attempts_used"] or 0) + 1 if slot_row else 1

    job_id = str(uuid.uuid4())
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO poster_jobs
        (id, campaign_name, template_key, subject, audience, status, item_count, unit_cost, suggested_price, created_at, user_id, slot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
        """,
        (
            job_id,
            campaign_name,
            template_key,
            subject,
            audience,
            "running",
            len(titles),
            now,
            user_id,
            active_slot_id,
        ),
    )
    conn.commit()

    reference_buffers = parse_reference_images_list(data.get("reference_images") or [])
    if reference_buffers:
        save_reference_images(job_id, reference_buffers)

    conn.execute(
        "UPDATE poster_jobs SET reference_count = ? WHERE id = ?",
        (len(reference_buffers), job_id),
    )
    conn.commit()

    items = []
    job_duration_ms = 0
    slot_released = False
    style_anchor: bytes | None = None
    planned_prompt_by_index = {
        index: str(item.get("prompt") or "").strip()
        for index, item in enumerate(planned_items[: len(titles)])
        if str(item.get("prompt") or "").strip()
    }
    for index, title in enumerate(titles):
        item_id = str(uuid.uuid4())
        item_prompt_text = prompt_text
        planned_prompt = planned_prompt_by_index.get(index)
        if planned_prompt:
            item_prompt_text = (
                f"{prompt_text}\n\n【本张AI规划提示词】\n{planned_prompt}"
                if prompt_text
                else planned_prompt
            )
        prompt = poster_prompt(
            campaign_name=campaign_name,
            template_key=template_key,
            title=title,
            subject=subject,
            audience=audience,
            brand_name=str(config.get("brand_name") or DEFAULT_CONFIG["brand_name"]),
            prompt_text=item_prompt_text,
            modify_notes=modify_notes if is_modify else "",
            modification_index=modification_index if is_modify else 1,
            batch_mode=is_batch,
            batch_index=index + 1,
            batch_total=len(titles),
        )
        status = "completed"
        error = None
        image_path: str | None = None
        output_format = str(config.get("output_format") or DEFAULT_CONFIG["output_format"])
        ext = output_format if output_format in {"png", "jpeg", "webp"} else "png"
        started = time.time()
        credit_refunded = False
        api_reference_buffers = list(reference_buffers)
        image_bytes: bytes | None = None
        if is_modify:
            base_image = load_slot_base_image(conn, active_slot_id, user_id)
            if base_image:
                api_reference_buffers = [base_image] + api_reference_buffers
        elif is_batch and style_anchor is not None:
            api_reference_buffers = [style_anchor] + api_reference_buffers
            prompt += (
                "【跟版要求】参考图是本系列首张已生成成品的真实样式，"
                "必须保持相同版式结构、主配色、字体层级与装饰元素，仅替换本张文案与编号。"
            )
        try:
            if not config.get("api_key"):
                raise RuntimeError("生成服务暂不可用，请稍后再试或联系客服。")
            image_bytes = call_image_api(
                prompt,
                request_config,
                api_reference_buffers or None,
            )
            if is_batch:
                if style_anchor is None:
                    style_anchor = image_bytes
            else:
                increment_slot_attempt(conn, active_slot_id)
                conn.commit()
        except Exception as exc:
            status = "failed"
            error = str(exc)
            if is_batch:
                if index < len(batch_credit_attempts):
                    refund_credit_bucket(conn, user_id, batch_credit_attempts[index])
                    credit_refunded = True
                    conn.commit()
            elif is_modify and pack_credit_consumed:
                rollback_pack_modify_credit(conn, user_id, active_slot_id)
                credit_refunded = True
                conn.commit()
            elif not is_modify:
                release_slot_credit(conn, user_id, active_slot_id)
                slot_released = True
                credit_refunded = True
                conn.execute("UPDATE poster_jobs SET slot_id = NULL WHERE id = ?", (job_id,))
                conn.commit()
        duration_ms = int((time.time() - started) * 1000)
        job_duration_ms += duration_ms
        if status == "completed" and image_bytes is not None:
            filename = f"{item_id}.{ext}"
            (OUTPUT_DIR / filename).write_bytes(image_bytes)
            image_path = f"/outputs/{filename}"
        conn.execute(
            """
            INSERT INTO poster_items
            (id, job_id, title, prompt, status, image_path, error, created_at, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                job_id,
                title,
                prompt,
                status,
                image_path,
                error,
                int(time.time()),
                duration_ms,
            ),
        )
        conn.commit()
        items.append(
            {
                "id": item_id,
                "title": title,
                "status": status,
                "image_path": image_path,
                "error": error,
                "prompt": prompt,
                "slot_id": None if slot_released or is_batch else active_slot_id,
                "is_modify": is_modify,
                "modification_index": modification_index,
                "max_attempts": slot_max_attempts,
                "duration_ms": duration_ms,
                "credit_refunded": credit_refunded,
                "batch_index": index + 1,
                "batch_total": len(titles),
            }
        )

    final_status = "completed" if all(item["status"] == "completed" for item in items) else "failed"
    if any(item["status"] == "completed" for item in items) and any(item["status"] == "failed" for item in items):
        final_status = "partial"
    conn.execute(
        "UPDATE poster_jobs SET status = ?, duration_ms = ? WHERE id = ?",
        (final_status, job_duration_ms, job_id),
    )
    conn.commit()
    slot_status = None if slot_released or is_batch else get_slot_status(conn, active_slot_id, user_id)
    usage = usage_summary(conn, user_id)
    credit_buckets = list_user_credit_buckets(conn, user_id)
    conn.close()
    job = get_job(job_id, user_id)
    job["slot_id"] = None if slot_released or is_batch else active_slot_id
    job["slot_status"] = slot_status
    job["usage"] = usage
    job["credit_buckets"] = credit_buckets
    job["is_batch"] = is_batch
    return job


def get_job(job_id: str, user_id: str | None = None) -> dict[str, Any]:
    conn = db()
    if user_id:
        job = conn.execute("SELECT * FROM poster_jobs WHERE id = ? AND user_id = ?", (job_id, user_id)).fetchone()
    else:
        job = conn.execute("SELECT * FROM poster_jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        raise KeyError("任务不存在")
    items = conn.execute(
        "SELECT * FROM poster_items WHERE job_id = ? ORDER BY created_at ASC", (job_id,)
    ).fetchall()
    conn.close()
    job_dict = dict(job)
    job_dict["template_name"] = TEMPLATES.get(job_dict["template_key"], TEMPLATES["study-card"])["name"]
    job_dict["items"] = [dict(item) for item in items]
    return job_dict


def list_history(user_id: str, job_limit: int = 200, item_limit: int = 500) -> dict[str, Any]:
    job_limit = max(1, min(job_limit, 500))
    item_limit = max(1, min(item_limit, 1000))
    conn = db()
    jobs = conn.execute(
        "SELECT * FROM poster_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, job_limit),
    ).fetchall()
    items = conn.execute(
        """
        SELECT
            poster_items.*,
            poster_jobs.campaign_name,
            poster_jobs.template_key,
            poster_jobs.slot_id,
            gs.attempts_used AS slot_attempts_used,
            gs.max_attempts AS slot_max_attempts
        FROM poster_items
        JOIN poster_jobs ON poster_jobs.id = poster_items.job_id
        LEFT JOIN generation_slots gs ON gs.id = poster_jobs.slot_id
        WHERE poster_jobs.user_id = ?
        ORDER BY poster_items.created_at DESC
        LIMIT ?
        """,
        (user_id, item_limit),
    ).fetchall()
    metrics = get_generation_metrics(conn)
    conn.close()
    completed = sum(1 for row in items if row["status"] == "completed")
    item_dicts = []
    for row in items:
        item = dict(row)
        used = int(item.get("slot_attempts_used") or 0)
        max_a = int(item.get("slot_max_attempts") or 0)
        remaining = max(0, max_a - used) if max_a else 0
        item["remaining_modifications"] = remaining
        item["can_modify"] = (
            item.get("status") == "completed"
            and item.get("slot_id")
            and used > 0
            and remaining > 0
        )
        item_dicts.append(item)
    return {
        "summary": {
            "poster_count": len(item_dicts),
            "completed_count": completed,
            "job_count": len(jobs),
        },
        "generation": {
            "typical_minutes": metrics.get("avg_duration_minutes") or 3.0,
            "failure_rate_percent": metrics.get("failure_rate_percent", 0),
            "credit_on_failure": "成功才计算额度",
        },
        "jobs": [dict(job) for job in jobs],
        "items": item_dicts,
    }


def read_raw_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", "0"))
    return handler.rfile.read(length) if length else b""


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    raw = read_raw_body(handler)
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise ValueError("请求体不是有效的 JSON。")


def session_token(handler: BaseHTTPRequestHandler) -> str | None:
    cookie = handler.headers.get("Cookie") or ""
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(f"{SESSION_COOKIE}="):
            return part.split("=", 1)[1].strip()
    return None


def cookie_secure(handler: BaseHTTPRequestHandler) -> bool:
    force = os.getenv("POSTER_SECURE_COOKIE", "").lower()
    if force in ("0", "false", "no"):
        return False
    if force in ("1", "true", "yes"):
        return True
    proto = (handler.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
    return proto == "https"


def set_session_cookie(handler: BaseHTTPRequestHandler, token: str) -> None:
    max_age = 30 * 86400
    secure = cookie_secure(handler)
    flags = "HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
    handler.send_header(
        "Set-Cookie",
        f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; {flags}",
    )


def clear_session_cookie(handler: BaseHTTPRequestHandler) -> None:
    secure = cookie_secure(handler)
    flags = "HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
    handler.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; {flags}")



def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_unified_jwt(payload: dict[str, Any]) -> str:
    secret = os.getenv(
        "JWT_SECRET",
        "YmFja2VuZC1rZXktZm9yLXN1YXQtZ3B0LXN0cnVjdHVyZS1leGFhbXBsZS1zZWNydC1oZXJlCg==",
    )
    key = base64.b64decode(secret)
    header_b64 = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(key, f"{header_b64}.{payload_b64}".encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def mint_unified_jwt_for_poster_user(user: dict[str, Any]) -> str:
    from poster_platform import OWNER_GREETING, is_owner_phone

    phone = str(user.get("phone") or "").strip()
    owner = is_owner_phone(phone)
    now = int(time.time())
    ttl = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(24 * 3600)))
    payload = {
        "sub": phone,
        "username": phone,
        "name": OWNER_GREETING if owner else str(user.get("org") or user.get("display_name") or phone),
        "role": "BETA" if owner else "USER",
        "tier": "vip" if owner else "standard",
        "platformPermissions": {"*": "full"} if owner else {"*": "read"},
        "platformMemberships": {"*": {"planId": "__MAX__"}} if owner else {},
        "grantPreset": "experience_all_max" if owner else "",
        "grantExpiresAt": "",
        "iss": os.getenv("AUTH_ISSUER", "suat-unified-auth"),
        "aud": os.getenv("AUTH_AUDIENCE", "suat-core-systems"),
        "iat": now,
        "exp": now + ttl,
    }
    return sign_unified_jwt(payload)


def verify_unified_jwt(token: str | None) -> dict[str, Any] | None:
    if not token or token.count(".") != 2:
        return None
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        secret = os.getenv(
            "JWT_SECRET",
            "YmFja2VuZC1rZXktZm9yLXN1YXQtZ3B0LXN0cnVjdHVyZS1leGFhbXBsZS1zZWNydC1oZXJlCg==",
        )
        key = base64.b64decode(secret)
        expected = hmac.new(key, f"{header_b64}.{payload_b64}".encode("ascii"), hashlib.sha256).digest()
        actual = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def unified_token(handler: BaseHTTPRequestHandler) -> str | None:
    auth = handler.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    cookie_header = handler.headers.get("Cookie") or ""
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("suat_auth="):
            return part.split("=", 1)[1].strip()
    return None


def require_user(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    user = resolve_authenticated_user(handler)
    if not user:
        raise LoginRequired("请先注册或登录。")
    return user


def require_admin(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    user = resolve_authenticated_user(handler)
    if not user:
        raise LoginRequired("请先注册或登录。")
    if user.get("role") != "admin":
        raise AdminRequired("需要管理员权限。")
    return user


def send_bytes(
    handler: BaseHTTPRequestHandler,
    data: bytes,
    content_type: str,
    status: int = 200,
    extra_headers: list[tuple[str, str]] | None = None,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    if extra_headers:
        for key, value in extra_headers:
            handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(data)


def parse_query_int(handler: BaseHTTPRequestHandler, key: str, default: int) -> int:
    query = handler.path.split("?", 1)[-1] if "?" in handler.path else ""
    for part in query.split("&"):
        if part.startswith(f"{key}="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return default
    return default


def send_json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200, extra_headers: list[tuple[str, str]] | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    merged = cors_headers(handler) + (extra_headers or [])
    for key, value in merged:
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


class PosterHandler(BaseHTTPRequestHandler):
    server_version = "PosterServer/1.0"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        for key, value in cors_headers(self):
            self.send_header(key, value)
        self.end_headers()

    def do_GET(self) -> None:
        try:
            path = self.path.split("?", 1)[0]
            if path == "/api/config":
                send_json(self, public_config())
                return
            if path == "/api/templates":
                send_json(self, {"templates": [{"key": key, **value} for key, value in TEMPLATES.items()]})
                return
            if path == "/api/auth/me":
                user = resolve_authenticated_user(self)
                if not user:
                    send_json(self, {"user": None})
                    return
                conn = db()
                usage = usage_summary(conn, user["id"])
                credit_buckets = list_user_credit_buckets(conn, user["id"])
                conn.close()
                send_json(self, {"user": user, "usage": usage, "credit_buckets": credit_buckets})
                return
            if path == "/api/credits/buckets":
                user = require_user(self)
                conn = db()
                buckets = list_user_credit_buckets(conn, user["id"])
                conn.close()
                send_json(self, {"buckets": buckets})
                return
            if path == "/api/payment/qr":
                plan_id = self.path.split("plan=", 1)[-1] if "plan=" in self.path else "single_50"
                config = load_config(mask=False)
                send_json(self, {"qr_url": payment_qr_for_plan(plan_id.split("&", 1)[0], config)})
                return
            if path.startswith("/api/payment/wechat/status/"):
                user = require_user(self)
                claim_id = path.rsplit("/", 1)[-1]
                config = load_config(mask=False)
                conn = db()
                result = sync_wechat_payment_status(conn, claim_id, user["id"], config)
                conn.commit()
                conn.close()
                send_json(self, result)
                return
            if path == "/api/history":
                user = require_user(self)
                job_limit = parse_query_int(self, "jobs", 200)
                item_limit = parse_query_int(self, "items", 500)
                send_json(self, list_history(user["id"], job_limit, item_limit))
                return
            if path == "/api/user/payments":
                user = require_user(self)
                conn = db()
                payments = list_user_payments(conn, user["id"])
                conn.close()
                send_json(self, {"payments": payments})
                return
            if path == "/api/invoice/eligible-payments":
                user = require_user(self)
                conn = db()
                payments = list_invoice_eligible_payments(conn, user["id"])
                conn.close()
                send_json(self, {"payments": payments})
                return
            if path.startswith("/api/slots/"):
                user = require_user(self)
                slot_id = path.rsplit("/", 1)[-1]
                conn = db()
                status = get_slot_status(conn, slot_id, user["id"])
                conn.close()
                send_json(self, status)
                return
            if path.startswith("/api/jobs/"):
                user = require_user(self)
                send_json(self, get_job(path.rsplit("/", 1)[-1], user["id"]))
                return
            if path == "/api/admin/events":
                require_admin(self)
                conn = db()
                events = list_admin_events(conn)
                conn.close()
                send_json(self, {"events": events})
                return
            if path == "/api/admin/dashboard":
                require_admin(self)
                conn = db()
                dashboard = admin_dashboard(conn)
                conn.close()
                send_json(self, dashboard)
                return
            if path == "/api/admin/config":
                require_admin(self)
                send_json(self, load_config(mask=True))
                return
            if path.startswith("/api/admin/payment-screenshot/"):
                require_admin(self)
                claim_id = path.rsplit("/", 1)[-1]
                screenshot = payment_screenshot_path(claim_id)
                if not screenshot:
                    send_json(self, {"error": "截图不存在"}, 404)
                    return
                content_type = mimetypes.guess_type(str(screenshot))[0] or "image/jpeg"
                send_bytes(self, screenshot.read_bytes(), content_type)
                return
            if path.startswith("/api/reference-images/"):
                rel = path.removeprefix("/api/reference-images/").strip("/")
                target = (DATA_DIR / "reference-images" / rel).resolve()
                root = (DATA_DIR / "reference-images").resolve()
                if not str(target).startswith(str(root)) or not target.exists() or not target.is_file():
                    send_json(self, {"error": "参考图不存在"}, 404)
                    return
                content_type = mimetypes.guess_type(str(target))[0] or "image/jpeg"
                send_bytes(
                    self,
                    target.read_bytes(),
                    content_type,
                    extra_headers=[("Cache-Control", "public, max-age=31536000, immutable")],
                )
                return
            self.serve_static()
        except LoginRequired as exc:
            send_json(self, {"error": str(exc)}, 401)
        except AdminRequired as exc:
            send_json(self, {"error": str(exc)}, 403)
        except KeyError as exc:
            send_json(self, {"error": str(exc)}, 404)
        except ValueError as exc:
            send_json(self, {"error": str(exc)}, 400)
        except Exception as exc:
            send_json(self, {"error": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            path = self.path.split("?", 1)[0]
            if path == "/api/auth/register":
                if unified_auth_enabled():
                    send_json(
                        self,
                        {
                            "error": "请前往 MS1001 统一认证注册。",
                            "redirect": f"{auth_base_url()}/login?tab=register&redirect={urllib.parse.quote(self.headers.get('Referer') or '/', safe='')}",
                            "use_unified_auth": True,
                        },
                        400,
                    )
                    return
                body = read_json(self)
                conn = db()
                user, token = register_user(
                    conn,
                    phone=body.get("phone", ""),
                    wechat=body.get("wechat", ""),
                    org=body.get("org", ""),
                    password=body.get("password", ""),
                    contract_accepted=bool(body.get("contract_accepted")),
                )
                usage = usage_summary(conn, user["id"])
                conn.commit()
                conn.close()
                payload = {"user": user, "usage": usage, "ok": True}
                body_out = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(201)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body_out)))
                set_session_cookie(self, token)
                self.end_headers()
                self.wfile.write(body_out)
                return
            if path == "/api/auth/login":
                if unified_auth_enabled():
                    send_json(
                        self,
                        {
                            "error": "请前往 MS1001 统一认证登录。",
                            "redirect": f"{auth_base_url()}/login?redirect={urllib.parse.quote(self.headers.get('Referer') or '/', safe='')}",
                            "use_unified_auth": True,
                        },
                        400,
                    )
                    return
                body = read_json(self)
                conn = db()
                user, token = login_user(conn, body.get("phone", ""), body.get("password", ""))
                conn.commit()
                usage = usage_summary(conn, user["id"])
                conn.close()
                payload = {"user": user, "usage": usage, "ok": True}
                body_out = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body_out)))
                set_session_cookie(self, token)
                self.end_headers()
                self.wfile.write(body_out)
                return
            if path == "/api/auth/unified/refresh-token":
                user = require_user(self)
                existing = unified_token(self)
                if existing and verify_unified_jwt(existing):
                    send_json(self, {"ok": True, "token": existing})
                    return
                token = mint_unified_jwt_for_poster_user(user)
                send_json(self, {"ok": True, "token": token})
                return
            if path == "/api/auth/logout":
                conn = db()
                logout_token(conn, session_token(self))
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                clear_session_cookie(self)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            if path == "/api/payment/claim":
                user = require_user(self)
                config = load_config(mask=False)
                if wechat_pay_ready(config):
                    send_json(self, {"error": "已启用微信官方支付，请使用微信扫码支付，无需上传截图。"}, 400)
                    return
                body = read_json(self)
                conn = db()
                claim = submit_payment_claim(
                    conn,
                    user,
                    plan_id=body.get("plan_id", ""),
                    screenshot_image=body.get("screenshot_image", ""),
                    phone=body.get("phone", user["phone"]),
                    contract_accepted=bool(body.get("contract_accepted")),
                    bulk_quantity=body.get("bulk_quantity"),
                )
                usage = usage_summary(conn, user["id"])
                conn.commit()
                conn.close()
                send_json(self, {"claim": claim, "usage": usage})
                return
            if path == "/api/payment/wechat/native/create":
                user = require_user(self)
                body = read_json(self)
                config = load_config(mask=False)
                conn = db()
                order = create_wechat_native_payment(
                    conn,
                    user,
                    plan_id=body.get("plan_id", ""),
                    contract_accepted=bool(body.get("contract_accepted")),
                    bulk_quantity=body.get("bulk_quantity"),
                    config=config,
                )
                conn.commit()
                conn.close()
                send_json(self, order, 201)
                return
            if path == "/api/payment/wechat/notify":
                raw = read_raw_body(self)
                body_text = raw.decode("utf-8")
                headers = {k: v for k, v in self.headers.items()}
                config = load_config(mask=False)
                conn = db()
                try:
                    result = handle_wechat_pay_notify(conn, headers, body_text, config)
                except Exception as exc:
                    conn.close()
                    send_json(self, {"code": "FAIL", "message": str(exc)}, 400)
                    return
                conn.commit()
                conn.close()
                send_json(self, result)
                return
            if path == "/api/invoice/request":
                user = require_user(self)
                body = read_json(self)
                conn = db()
                result = submit_invoice_request(
                    conn,
                    user,
                    company_name=body.get("company_name", ""),
                    tax_id=body.get("tax_id", ""),
                    contact_email=body.get("contact_email", ""),
                    invoice_amount=body.get("invoice_amount", 0),
                    note=body.get("note", ""),
                    payment_claim_id=body.get("payment_claim_id"),
                )
                conn.commit()
                conn.close()
                send_json(self, result)
                return
            if path == "/api/jobs":
                user = require_user(self)
                body = read_json(self)
                body.setdefault("generation_mode", "single")
                send_json(self, create_job(body, user["id"]), 201)
                return
            if path == "/api/jobs/ai-batch":
                user = require_user(self)
                body = read_json(self)
                command = str(body.get("command") or body.get("prompt_text") or "").strip()
                if len(command) < 2:
                    raise ValueError("请先输入批量海报需求。")
                config = load_config(mask=False)
                max_items = int(config.get("max_items_per_job") or DEFAULT_CONFIG["max_items_per_job"])
                plan = call_minimax_batch_plan_api(
                    command,
                    {
                        "campaign_name": str(body.get("campaign_name") or ""),
                        "template_key": str(body.get("template_key") or ""),
                        "subject": str(body.get("subject") or ""),
                        "audience": str(body.get("audience") or ""),
                        "size": str(body.get("size") or ""),
                        "count": int(body.get("count") or 6),
                        "max_items": max_items,
                    },
                    config,
                )
                body["generation_mode"] = "batch"
                body["items"] = [item["title"] for item in plan["items"]]
                body["planned_items"] = plan["items"]
                body["prompt_text"] = plan.get("series_style") or command
                job = create_job(body, user["id"])
                job["ai_plan"] = plan
                send_json(self, job, 201)
                return
            if path == "/api/jobs/batch":
                user = require_user(self)
                body = read_json(self)
                body["generation_mode"] = "batch"
                send_json(self, create_job(body, user["id"]), 201)
                return
            if path == "/api/prompts/auto":
                require_user(self)
                body = read_json(self)
                command = str(body.get("command") or "").strip()
                if len(command) < 2:
                    raise ValueError("请先输入一句生成海报的命令。")
                config = load_config(mask=False)
                prompt = call_minimax_prompt_api(
                    command,
                    {
                        "campaign_name": str(body.get("campaign_name") or ""),
                        "template_key": str(body.get("template_key") or ""),
                        "subject": str(body.get("subject") or ""),
                        "audience": str(body.get("audience") or ""),
                        "size": str(body.get("size") or ""),
                    },
                    config,
                )
                send_json(self, {"prompt": prompt})
                return
            if path == "/api/prompts/batch-plan":
                require_user(self)
                body = read_json(self)
                command = str(body.get("command") or "").strip()
                if len(command) < 2:
                    raise ValueError("请先输入批量海报需求。")
                config = load_config(mask=False)
                max_items = int(config.get("max_items_per_job") or DEFAULT_CONFIG["max_items_per_job"])
                plan = call_minimax_batch_plan_api(
                    command,
                    {
                        "campaign_name": str(body.get("campaign_name") or ""),
                        "template_key": str(body.get("template_key") or ""),
                        "subject": str(body.get("subject") or ""),
                        "audience": str(body.get("audience") or ""),
                        "size": str(body.get("size") or ""),
                        "count": int(body.get("count") or 6),
                        "max_items": max_items,
                    },
                    config,
                )
                send_json(self, plan)
                return
            if path == "/api/admin/config":
                require_admin(self)
                send_json(self, save_config(read_json(self)))
                return
            if path.startswith("/api/admin/payments/") and path.endswith("/approve"):
                admin = require_admin(self)
                claim_id = path.split("/")[-2]
                conn = db()
                result = approve_payment_claim(conn, claim_id, admin)
                conn.commit()
                conn.close()
                send_json(self, result)
                return
            if path.startswith("/api/admin/payments/") and path.endswith("/reject"):
                admin = require_admin(self)
                claim_id = path.split("/")[-2]
                body = read_json(self)
                conn = db()
                result = reject_payment_claim(conn, claim_id, admin, reason=body.get("reason", ""))
                conn.commit()
                conn.close()
                send_json(self, result)
                return
            if path.startswith("/api/admin/payments/") and path.endswith("/halt"):
                admin = require_admin(self)
                claim_id = path.split("/")[-2]
                body = read_json(self)
                conn = db()
                result = halt_payment_claim(conn, claim_id, admin, reason=body.get("reason", ""))
                conn.commit()
                conn.close()
                send_json(self, result)
                return
            if path.startswith("/api/admin/invoices/") and path.endswith("/status"):
                admin = require_admin(self)
                request_id = path.split("/")[-2]
                body = read_json(self)
                conn = db()
                result = update_invoice_status(conn, request_id, str(body.get("status", "")), admin)
                conn.commit()
                conn.close()
                send_json(self, result)
                return
            send_json(self, {"error": "Not found"}, 404)
        except LoginRequired as exc:
            send_json(self, {"error": str(exc)}, 401)
        except AdminRequired as exc:
            send_json(self, {"error": str(exc)}, 403)
        except ValueError as exc:
            send_json(self, {"error": str(exc)}, 400)
        except Exception as exc:
            send_json(self, {"error": str(exc)}, 500)

    def serve_static(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            target = WEB_DIR / "index.html"
        elif path.startswith("/outputs/"):
            target = OUTPUT_DIR / path.removeprefix("/outputs/")
        elif path.startswith("/assets/"):
            target = WEB_DIR / path.lstrip("/")
        else:
            target = WEB_DIR / path.lstrip("/")
        target = target.resolve()
        allowed = [WEB_DIR.resolve(), OUTPUT_DIR.resolve()]
        if not any(str(target).startswith(str(root)) for root in allowed) or not target.exists():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix.lower() == ".svg":
            content_type = "image/svg+xml"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    ensure_dirs()
    verify_auth_stack()
    ensure_https_client()
    conn = db()
    prune_expired_sessions(conn)
    ensure_default_admin(conn)
    conn.commit()
    conn.close()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8010"))
    server = ThreadingHTTPServer((host, port), PosterHandler)
    print(f"Poster server running at http://{host}:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()

