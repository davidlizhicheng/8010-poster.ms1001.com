"""User accounts, credits, QR payments, invoices — production platform layer."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PAYMENT_SCREENSHOT_DIR = DATA_DIR / "payment-screenshots"
REFERENCE_UPLOAD_DIR = DATA_DIR / "reference-images"
ALERTS_PATH = DATA_DIR / "admin_alerts.log"
MAX_REFERENCE_IMAGES = max(1, int(os.getenv("MAX_REFERENCE_IMAGES", "30")))

ATTEMPTS_SINGLE = 5
MODIFICATIONS_PER_THEME = 5
ATTEMPTS_PER_THEME = MODIFICATIONS_PER_THEME + 1
ATTEMPTS_PACK = 1

BUCKET_SOURCE_LABELS: dict[str, str] = {
    "trial": "免费体验",
    "trial_001": "免费体验",
    "single_50": "单张设计包",
    "pack_20": "月度套餐",
    "pack_100": "季度套餐",
    "consult_5000": "包年·品牌咨询",
    "vip_10000": "包年·尊享定制",
    "bulk_10": "企业批量",
    "admin_grant": "管理员补开",
    "legacy": "历史额度",
    "owner_vip": "老板 VIP",
}


def max_attempts_for_credit(credit_attempts: int) -> int:
    """Single/trial buckets allow modify; pack buckets are one-shot per theme."""
    if credit_attempts >= ATTEMPTS_SINGLE:
        return ATTEMPTS_PER_THEME
    return max(1, int(credit_attempts or 1))


def allows_bundle_modify(credit_attempts: int) -> bool:
    return int(credit_attempts or 0) >= ATTEMPTS_SINGLE


def bucket_modify_rule_label(attempts_per_slot: int) -> str:
    if allows_bundle_modify(attempts_per_slot):
        return "同主题可修改5次（含首次生成）"
    return "每次修改另计1次额度"


def active_credit_bucket_count(conn: sqlite3.Connection, user_id: str) -> int:
    if is_owner_user_id(conn, user_id):
        return 0
    _refresh_monthly_buckets(conn, user_id)
    now = _now()
    row = conn.execute(
        """
        SELECT COUNT(*) AS total FROM credit_buckets
        WHERE user_id = ? AND credits_remaining > 0
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (user_id, now),
    ).fetchone()
    count = int(row["total"] or 0)
    if count:
        return count
    legacy = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
    if legacy and int(legacy["credits"] or 0) > 0:
        return 1
    return 0


def list_user_credit_buckets(conn: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    if is_owner_user_id(conn, user_id):
        return [
            {
                "id": "owner_vip",
                "source": "owner_vip",
                "label": BUCKET_SOURCE_LABELS["owner_vip"],
                "credits_remaining": OWNER_CREDITS_DISPLAY,
                "attempts_per_slot": OWNER_SLOT_ATTEMPTS,
                "allows_bundle_modify": True,
                "modify_rule": "无限生成 · 同主题可无限修改",
                "expires_at": None,
                "expires_text": None,
            }
        ]
    _refresh_monthly_buckets(conn, user_id)
    now = _now()
    rows = conn.execute(
        """
        SELECT id, source, credits_remaining, attempts_per_slot, expires_at, created_at
        FROM credit_buckets
        WHERE user_id = ? AND credits_remaining > 0
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY created_at ASC
        """,
        (user_id, now),
    ).fetchall()
    buckets: list[dict[str, Any]] = []
    for row in rows:
        attempts = int(row["attempts_per_slot"] or ATTEMPTS_PACK)
        source = str(row["source"] or "")
        label = BUCKET_SOURCE_LABELS.get(source, source or "套餐额度")
        expiry = int(row["expires_at"]) if row["expires_at"] else None
        buckets.append(
            {
                "id": row["id"],
                "source": source,
                "label": label,
                "credits_remaining": int(row["credits_remaining"]),
                "attempts_per_slot": attempts,
                "allows_bundle_modify": allows_bundle_modify(attempts),
                "modify_rule": bucket_modify_rule_label(attempts),
                "expires_at": expiry,
                "expires_text": datetime.fromtimestamp(expiry).strftime("%Y-%m-%d %H:%M") if expiry else None,
            }
        )
    legacy = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
    legacy_credits = int(legacy["credits"] or 0) if legacy else 0
    if legacy_credits > 0:
        buckets.append(
            {
                "id": "legacy",
                "source": "legacy",
                "label": BUCKET_SOURCE_LABELS["legacy"],
                "credits_remaining": legacy_credits,
                "attempts_per_slot": ATTEMPTS_SINGLE,
                "allows_bundle_modify": True,
                "modify_rule": bucket_modify_rule_label(ATTEMPTS_SINGLE),
                "expires_at": None,
                "expires_text": None,
            }
        )
    return buckets
SESSION_DAYS = 30
INVOICE_SERVICE_FEE = 10
PACK_100_VALID_DAYS = 90
ANNUAL_VALID_DAYS = 365
OWNER_PHONE = "18665898305"
OWNER_COMPANY = "深圳市了不起品牌管理有限公司"
OWNER_GREETING = f"李总您好！（{OWNER_COMPANY}）"
OWNER_PRIVILEGE_MESSAGE = f"{OWNER_GREETING}您享有内部测试无限生成额度；购买套餐须与其它用户相同正常支付。"
OWNER_CREDITS_DISPLAY = 999999
OWNER_SLOT_ATTEMPTS = 1000000

PAYMENT_PLANS: dict[str, dict[str, Any]] = {
    "trial_001": {
        "id": "trial_001",
        "name": "免费体验",
        "amount": 0,
        "credits": 1,
        "attempts_per_slot": ATTEMPTS_SINGLE,
        "payment_disabled": True,
        "desc": "新用户免费体验 1 张成品海报，同主题可修改 5 次",
    },
    "single_50": {
        "id": "single_50",
        "name": "单张设计包",
        "amount": 50,
        "credits": 1,
        "attempts_per_slot": ATTEMPTS_SINGLE,
        "desc": "1 张成品海报，同主题可修改 5 次",
    },
    "pack_20": {
        "id": "pack_20",
        "name": "月度套餐",
        "amount": 300,
        "credits": 20,
        "attempts_per_slot": ATTEMPTS_PACK,
        "desc": "20 张海报额度，适合月均活动与社群传播",
    },
    "pack_100": {
        "id": "pack_100",
        "name": "季度套餐",
        "amount": 1000,
        "credits": 100,
        "attempts_per_slot": ATTEMPTS_PACK,
        "valid_days": PACK_100_VALID_DAYS,
        "desc": "100 张海报额度，须在 3 个月内用完",
    },
    "consult_5000": {
        "id": "consult_5000",
        "name": "包年会员 · 品牌咨询",
        "amount": 5000,
        "credits": 500,
        "attempts_per_slot": ATTEMPTS_PACK,
        "monthly_sessions": 1,
        "valid_days": ANNUAL_VALID_DAYS,
        "desc": "包年 500 次设计额度 + AI 品牌咨询顾问，须在一年内用完",
    },
    "vip_10000": {
        "id": "vip_10000",
        "name": "包年会员 · 尊享定制",
        "amount": 10000,
        "credits": 20,
        "monthly_credits": 20,
        "attempts_per_slot": ATTEMPTS_PACK,
        "valid_days": ANNUAL_VALID_DAYS,
        "desc": "包年尊享定制，每月 20 次设计额度 + 个性化定制服务",
    },
    "bulk": {
        "id": "bulk",
        "name": "企业批量",
        "amount": 0,
        "credits": 0,
        "attempts_per_slot": ATTEMPTS_PACK,
        "unit_price": 10,
        "min_quantity": 20,
        "min_amount": 200,
        "desc": "大规模投放与定制批次，支持 API 与参考图工作流",
    },
}

PUBLIC_PLANS = [
    {
        "id": "single_50",
        "name": "单张设计包",
        "price_label": "¥50",
        "credits": 1,
        "highlight": "灵活试水",
        "desc": "1 张成品，同主题可修改 5 次",
        "features": ["单张付费即用", "适合紧急物料", "支持下载 PNG"],
    },
    {
        "id": "pack_20",
        "name": "月度套餐",
        "price_label": "¥300/月",
        "credits": 20,
        "highlight": "热门",
        "desc": "20 张海报，适合月均活动与社群传播",
        "features": ["20 次独立生成", "企业机构首选", "按月灵活续费"],
    },
    {
        "id": "pack_100",
        "name": "季度套餐",
        "price_label": "¥1000/季度",
        "credits": 100,
        "highlight": "储备",
        "desc": "100 张额度，须在 3 个月内用完",
        "features": ["100 次独立生成", "适合集中投放季", "支持企业开票"],
    },
    {
        "id": "consult_5000",
        "name": "包年会员 · 品牌咨询",
        "price_label": "¥5000/年",
        "credits": 500,
        "highlight": "包年",
        "desc": "一年 500 次额度 + 品牌咨询",
        "features": ["500 次设计生成", "须在一年内用完", "线上每月 1 次咨询服务"],
    },
    {
        "id": "vip_10000",
        "name": "包年会员 · 尊享定制",
        "price_label": "¥10000/年",
        "credits": 20,
        "highlight": "尊享",
        "desc": "每月 20 次额度 + 个性化定制",
        "features": ["每月 20 次设计生成", "365 天服务期内每月刷新", "额外个性化定制服务"],
    },
    {
        "id": "bulk",
        "name": "企业批量",
        "price_label": "¥10/张",
        "credits": 0,
        "highlight": "20 张起",
        "desc": "大规模投放与定制批次",
        "features": ["20 张以上 ¥10/张", "公司转账最低 ¥200", "统一收银台处理"],
    },
]


def _now() -> int:
    return int(time.time())


_PWD_SCHEME = "pbkdf2-sha256"
_PBKDF2_ITERATIONS = 100000
_PBKDF2_LEGACY_ITERATIONS = 260000


def _pbkdf2_hex(password: str, salt_bytes: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iterations,
        dklen=32,
    ).hex()


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    password = str(password or "").strip()
    if len(password) < 6:
        raise ValueError("密码至少 6 位。")
    if salt and len(salt) == 32 and re.fullmatch(r"[0-9a-f]+", salt):
        salt_bytes = bytes.fromhex(salt)
    else:
        salt_bytes = secrets.token_bytes(16)
    salt_hex = salt_bytes.hex()
    digest_hex = _pbkdf2_hex(password, salt_bytes, _PBKDF2_ITERATIONS)
    stored = f"{_PWD_SCHEME}${_PBKDF2_ITERATIONS}${salt_hex}${digest_hex}"
    return salt_hex, stored


def _verify_legacy_pbkdf2(password: str, salt: str, stored: str) -> bool:
    """旧版：salt 列 + 128 位 hex（salt 按 utf-8 编码）。"""
    try:
        legacy = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            _PBKDF2_LEGACY_ITERATIONS,
            dklen=64,
        ).hex()
        return hmac.compare_digest(legacy, stored)
    except Exception:
        return False


def _verify_legacy_scrypt(password: str, salt: str, stored: str) -> bool:
    if not hasattr(hashlib, "scrypt"):
        return False
    try:
        legacy = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=16384,
            r=8,
            p=1,
            dklen=64,
        ).hex()
        return hmac.compare_digest(legacy, stored)
    except Exception:
        return False


def _verify_password(password: str, salt: str, stored: str) -> bool:
    password = str(password or "").strip()
    stored = str(stored or "").strip()
    salt = str(salt or "").strip()
    if not password or not stored:
        return False

    if stored.startswith(f"{_PWD_SCHEME}$"):
        parts = stored.split("$")
        if len(parts) == 4:
            try:
                iterations = int(parts[1])
                salt_bytes = bytes.fromhex(parts[2])
                expected = parts[3]
                digest_hex = _pbkdf2_hex(password, salt_bytes, iterations)
                return hmac.compare_digest(digest_hex, expected)
            except (ValueError, TypeError):
                return False

    if len(stored) == 128 and re.fullmatch(r"[0-9a-f]+", stored):
        if _verify_legacy_pbkdf2(password, salt, stored):
            return True
        if _verify_legacy_scrypt(password, salt, stored):
            return True
    return False


def verify_auth_stack() -> None:
    """启动自检：密码哈希与校验必须一致。"""
    salt, stored = _hash_password("poster-self-test-ok")
    if not _verify_password("poster-self-test-ok", salt, stored):
        raise RuntimeError("密码模块自检失败，请检查 Python/OpenSSL 环境。")


def reset_user_password(conn: sqlite3.Connection, phone: str, password: str) -> None:
    phone_n = normalize_phone(phone)
    row = conn.execute("SELECT id FROM users WHERE phone = ?", (phone_n,)).fetchone()
    if not row:
        raise ValueError("该手机号未注册。")
    salt, stored = _hash_password(str(password).strip())
    conn.execute(
        "UPDATE users SET password_salt = ?, password_hash = ? WHERE phone = ?",
        (salt, stored, phone_n),
    )


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not re.fullmatch(r"1\d{10}", digits):
        raise ValueError("请填写正确的 11 位手机号。")
    return digits


def prompt_key(template_key: str, title: str, subject: str, audience: str) -> str:
    raw = f"{template_key}|{title.strip()}|{subject.strip()}|{audience.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_platform_tables(conn: sqlite3.Connection) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PAYMENT_SCREENSHOT_DIR.mkdir(exist_ok=True)
    REFERENCE_UPLOAD_DIR.mkdir(exist_ok=True)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            wechat TEXT NOT NULL,
            org TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            credits INTEGER NOT NULL DEFAULT 0,
            free_trial_used INTEGER NOT NULL DEFAULT 0,
            role TEXT NOT NULL DEFAULT 'user',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS generation_slots (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            prompt_key TEXT NOT NULL,
            attempts_used INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            credit_attempts INTEGER NOT NULL DEFAULT 5,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS credit_buckets (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            credits_remaining INTEGER NOT NULL,
            attempts_per_slot INTEGER NOT NULL DEFAULT 5,
            source TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS payment_claims (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            amount REAL NOT NULL,
            credits INTEGER NOT NULL,
            bulk_quantity INTEGER,
            phone TEXT NOT NULL,
            screenshot_file TEXT,
            screenshot_hash TEXT,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS invoice_requests (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            company_name TEXT NOT NULL,
            tax_id TEXT NOT NULL,
            contact_email TEXT NOT NULL,
            invoice_amount REAL NOT NULL,
            service_fee REAL NOT NULL DEFAULT 10,
            total_amount REAL NOT NULL,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS admin_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT,
            created_at INTEGER NOT NULL
        );
        """
    )
    try:
        conn.execute("ALTER TABLE poster_jobs ADD COLUMN user_id TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE poster_jobs ADD COLUMN slot_id TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE generation_slots ADD COLUMN credit_attempts INTEGER NOT NULL DEFAULT 5")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    _migrate_generation_slots(conn)
    try:
        conn.execute("ALTER TABLE credit_buckets ADD COLUMN expires_at INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE credit_buckets ADD COLUMN monthly_credits INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE credit_buckets ADD COLUMN period_start INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE invoice_requests ADD COLUMN payment_claim_id TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    for statement in (
        "ALTER TABLE payment_claims ADD COLUMN payment_channel TEXT DEFAULT 'screenshot'",
        "ALTER TABLE payment_claims ADD COLUMN wechat_transaction_id TEXT",
        "ALTER TABLE users ADD COLUMN unified_username TEXT",
    ):
        try:
            conn.execute(statement)
            conn.commit()
        except sqlite3.OperationalError:
            pass
    _migrate_legacy_credits(conn)


def _migrate_legacy_credits(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, credits FROM users WHERE credits > 0").fetchall()
    for row in rows:
        has_bucket = conn.execute(
            "SELECT 1 FROM credit_buckets WHERE user_id = ? LIMIT 1",
            (row["id"],),
        ).fetchone()
        if has_bucket:
            continue
        conn.execute(
            """
            INSERT INTO credit_buckets (id, user_id, credits_remaining, attempts_per_slot, source, created_at)
            VALUES (?, ?, ?, ?, 'legacy', ?)
            """,
            (secrets.token_hex(16), row["id"], int(row["credits"]), ATTEMPTS_SINGLE, _now()),
        )
        conn.execute("UPDATE users SET credits = 0 WHERE id = ?", (row["id"],))


def _migrate_generation_slots(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE generation_slots SET max_attempts = 1 WHERE credit_attempts <= 1 AND max_attempts > 1"
    )
    conn.execute(
        """
        UPDATE generation_slots
        SET max_attempts = ?
        WHERE credit_attempts >= ? AND max_attempts < ?
        """,
        (ATTEMPTS_PER_THEME, ATTEMPTS_SINGLE, ATTEMPTS_PER_THEME),
    )
    conn.commit()


def prune_expired_sessions(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))


def _month_start(ts: int) -> int:
    dt = datetime.fromtimestamp(ts)
    return int(datetime(dt.year, dt.month, 1).timestamp())


def _refresh_monthly_buckets(conn: sqlite3.Connection, user_id: str) -> None:
    now = _now()
    current_period = _month_start(now)
    rows = conn.execute(
        """
        SELECT * FROM credit_buckets
        WHERE user_id = ? AND monthly_credits IS NOT NULL AND monthly_credits > 0
        """,
        (user_id,),
    ).fetchall()
    for row in rows:
        period_start = int(row["period_start"] or row["created_at"] or now)
        if current_period > _month_start(period_start):
            conn.execute(
                """
                UPDATE credit_buckets
                SET credits_remaining = monthly_credits, period_start = ?
                WHERE id = ?
                """,
                (current_period, row["id"]),
            )


def is_owner_phone(phone: str | None) -> bool:
    return str(phone or "").strip() == OWNER_PHONE


def phone_from_unified_claims(claims: dict[str, Any]) -> str:
    """Extract 11-digit phone from unified-auth JWT claims."""
    for key in ("phone", "username", "sub"):
        raw = str(claims.get(key) or "").strip()
        digits = re.sub(r"\D", "", raw)
        if re.fullmatch(r"1\d{10}", digits):
            return digits
    return ""


def unified_username_from_claims(claims: dict[str, Any]) -> str:
    return str(claims.get("username") or claims.get("sub") or "").strip()


def is_owner_from_unified_claims(claims: dict[str, Any] | None) -> bool:
    if not claims:
        return False
    if is_owner_phone(phone_from_unified_claims(claims)):
        return True
    if is_owner_phone(unified_username_from_claims(claims)):
        return True
    if claims.get("isOwner") is True:
        return True
    return False


def sync_owner_from_unified_auth(
    conn: sqlite3.Connection,
    user_id: str,
    claims: dict[str, Any] | None = None,
) -> None:
    """Ensure boss account keeps owner phone + admin role when logging in via unified auth."""
    if not is_owner_from_unified_claims(claims) and not is_owner_user_id(conn, user_id):
        return
    row = conn.execute("SELECT phone, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return
    updates: list[str] = []
    params: list[Any] = []
    if not is_owner_phone(row["phone"]):
        updates.append("phone = ?")
        params.append(OWNER_PHONE)
    if str(row["role"] or "") != "admin":
        updates.append("role = 'admin'")
    if not updates:
        return
    params.append(user_id)
    conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)


def is_owner_user(user: dict[str, Any] | sqlite3.Row | None) -> bool:
    return bool(user) and is_owner_phone(dict(user).get("phone"))


def is_owner_user_id(conn: sqlite3.Connection, user_id: str) -> bool:
    row = conn.execute("SELECT phone FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and is_owner_phone(row["phone"]))


def total_user_credits(conn: sqlite3.Connection, user_id: str) -> int:
    if is_owner_user_id(conn, user_id):
        return OWNER_CREDITS_DISPLAY
    _refresh_monthly_buckets(conn, user_id)
    now = _now()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(credits_remaining), 0) AS total FROM credit_buckets
        WHERE user_id = ? AND credits_remaining > 0
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (user_id, now),
    ).fetchone()
    legacy = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,)).fetchone()
    return int(row["total"] or 0) + int(legacy["credits"] or 0 if legacy else 0)


def add_credit_bucket(
    conn: sqlite3.Connection,
    user_id: str,
    credits: int,
    attempts_per_slot: int,
    source: str,
    *,
    expires_at: int | None = None,
    monthly_credits: int | None = None,
) -> None:
    if credits <= 0 and not monthly_credits and source != "consult_5000":
        return
    now = _now()
    period_start = _month_start(now) if monthly_credits else None
    conn.execute(
        """
        INSERT INTO credit_buckets
        (id, user_id, credits_remaining, attempts_per_slot, source, created_at, expires_at, monthly_credits, period_start)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            secrets.token_hex(16),
            user_id,
            credits,
            attempts_per_slot,
            source,
            now,
            expires_at,
            monthly_credits,
            period_start,
        ),
    )


def consume_credit_bucket(
    conn: sqlite3.Connection,
    user_id: str,
    bucket_id: str | None = None,
) -> int:
    """Deduct one credit and return allowed attempts for that slot."""
    if is_owner_user_id(conn, user_id):
        return OWNER_SLOT_ATTEMPTS
    _refresh_monthly_buckets(conn, user_id)
    now = _now()
    if bucket_id == "legacy":
        conn.execute("UPDATE users SET credits = credits - 1 WHERE id = ? AND credits > 0", (user_id,))
        if conn.execute("SELECT changes()").fetchone()[0]:
            return ATTEMPTS_SINGLE
        raise ValueError("所选额度不可用或已用完，请重新选择。")
    bucket = None
    if bucket_id:
        bucket = conn.execute(
            """
            SELECT * FROM credit_buckets
            WHERE id = ? AND user_id = ? AND credits_remaining > 0
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (bucket_id, user_id, now),
        ).fetchone()
        if not bucket:
            raise ValueError("所选额度不可用或已用完，请重新选择。")
    else:
        bucket = conn.execute(
            """
            SELECT * FROM credit_buckets
            WHERE user_id = ? AND credits_remaining > 0
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, now),
        ).fetchone()
    if bucket:
        conn.execute(
            "UPDATE credit_buckets SET credits_remaining = credits_remaining - 1 WHERE id = ? AND credits_remaining > 0",
            (bucket["id"],),
        )
        if conn.execute("SELECT changes()").fetchone()[0]:
            return int(bucket["attempts_per_slot"])
    conn.execute("UPDATE users SET credits = credits - 1 WHERE id = ? AND credits > 0", (user_id,))
    if conn.execute("SELECT changes()").fetchone()[0]:
        return ATTEMPTS_SINGLE
    raise ValueError("海报额度不足，请先购买套餐。")


def consume_batch_credits(
    conn: sqlite3.Connection,
    user_id: str,
    count: int,
    bucket_id: str | None = None,
) -> list[int]:
    """Consume multiple credits for a batch job. Returns attempts_per_slot for each credit (for refunds)."""
    if count < 1:
        return []
    if is_owner_user_id(conn, user_id):
        return [OWNER_SLOT_ATTEMPTS for _ in range(count)]
    attempts_list: list[int] = []
    try:
        for _ in range(count):
            attempts_list.append(consume_credit_bucket(conn, user_id, bucket_id))
    except ValueError:
        for attempts in attempts_list:
            refund_credit_bucket(conn, user_id, attempts)
        raise
    return attempts_list


def refund_credit_bucket(conn: sqlite3.Connection, user_id: str, attempts_per_slot: int) -> None:
    bucket = conn.execute(
        """
        SELECT * FROM credit_buckets
        WHERE user_id = ? AND attempts_per_slot = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, attempts_per_slot),
    ).fetchone()
    if bucket:
        conn.execute(
            "UPDATE credit_buckets SET credits_remaining = credits_remaining + 1 WHERE id = ?",
            (bucket["id"],),
        )
    else:
        conn.execute("UPDATE users SET credits = credits + 1 WHERE id = ?", (user_id,))


def log_admin_event(conn: sqlite3.Connection, event_type: str, summary: str, payload: dict[str, Any] | None = None) -> None:
    event_id = secrets.token_hex(16)
    conn.execute(
        "INSERT INTO admin_events (id, event_type, summary, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_id, event_type, summary, json.dumps(payload or {}, ensure_ascii=False), _now()),
    )
    line = f"[{_now()}] {event_type}: {summary}\n"
    with ALERTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line)
    notify_url = os.getenv("ADMIN_NOTIFY_URL", "").strip()
    if notify_url:
        try:
            import urllib.request

            body = json.dumps({"event_type": event_type, "summary": summary, "payload": payload or {}}).encode("utf-8")
            req = urllib.request.Request(
                notify_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=8)
        except Exception:
            pass


def sanitize_user(row: sqlite3.Row | dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    data = dict(row)
    user_id = data["id"]
    credits = total_user_credits(conn, user_id) if conn else int(data.get("credits") or 0)
    owner_vip = is_owner_phone(data.get("phone"))
    return {
        "id": user_id,
        "phone": data["phone"],
        "wechat": data["wechat"],
        "org": data["org"],
        "display_name": OWNER_GREETING if owner_vip else data["org"],
        "owner_vip": owner_vip,
        "owner_greeting": OWNER_GREETING if owner_vip else "",
        "credits": credits,
        "free_trial_used": bool(data.get("free_trial_used")),
        "role": data.get("role") or "user",
        "created_at": data.get("created_at"),
    }


def get_user_by_token(conn: sqlite3.Connection, token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT users.* FROM users
        JOIN sessions ON sessions.user_id = users.id
        WHERE sessions.token = ? AND sessions.expires_at > ?
        """,
        (token, _now()),
    ).fetchone()
    return sanitize_user(row, conn) if row else None


def ensure_user_from_unified_auth(
    conn: sqlite3.Connection,
    claims: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Map unified-auth JWT claims to a local poster user. Returns (user, created)."""
    phone = phone_from_unified_claims(claims)
    username = unified_username_from_claims(claims)
    if phone:
        row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
        if row:
            if username and username != phone:
                try:
                    conn.execute(
                        "UPDATE users SET unified_username = ? WHERE id = ? AND (unified_username IS NULL OR unified_username = '')",
                        (username, row["id"]),
                    )
                except sqlite3.OperationalError:
                    pass
            sync_owner_from_unified_auth(conn, row["id"], claims)
            row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            return sanitize_user(row, conn), False
    elif username:
        try:
            row = conn.execute("SELECT * FROM users WHERE unified_username = ?", (username,)).fetchone()
            if row:
                sync_owner_from_unified_auth(conn, row["id"], claims)
                row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
                return sanitize_user(row, conn), False
        except sqlite3.OperationalError:
            pass

    if not phone:
        raise ValueError(
            "该统一账号未绑定手机号，无法购买套餐。"
            "请使用手机号登录（如老板账号 18665898305），或在 ai.ms1001.com 会员中心补充手机号。"
        )

    name = str(claims.get("name") or phone).strip() or phone
    user_id = secrets.token_hex(16)
    salt, pwd_hash = _hash_password(secrets.token_hex(16))
    conn.execute(
        """
        INSERT INTO users (id, phone, wechat, org, password_salt, password_hash, credits, free_trial_used, role, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'user', ?)
        """,
        (user_id, phone, phone, name, salt, pwd_hash, _now()),
    )
    grant_free_trial(conn, user_id)
    sync_owner_from_unified_auth(conn, user_id, claims)
    user = sanitize_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone(), conn)
    log_admin_event(
        conn,
        "user_registered",
        f"统一认证同步新用户：{name} / {phone}",
        {"user_id": user_id, "phone": phone, "source": "unified_auth"},
    )
    return user, True


def register_user(
    conn: sqlite3.Connection,
    *,
    phone: str,
    wechat: str,
    org: str,
    password: str,
    contract_accepted: bool = False,
) -> tuple[dict[str, Any], str]:
    if not contract_accepted:
        raise ValueError("请先阅读并同意《用户使用须知》。")
    phone_n = normalize_phone(phone)
    wechat_n = str(wechat or "").strip()
    org_n = str(org or "").strip()
    if len(wechat_n) < 2:
        raise ValueError("请填写微信号。")
    if len(org_n) < 2:
        raise ValueError("请填写单位/机构名称。")
    password_n = str(password or "").strip()
    if len(password_n) < 6:
        raise ValueError("密码至少 6 位。")
    if conn.execute("SELECT 1 FROM users WHERE phone = ?", (phone_n,)).fetchone():
        raise ValueError("该手机号已注册，请直接登录。")

    salt, pwd_hash = _hash_password(password_n)
    user_id = secrets.token_hex(16)
    conn.execute(
        """
        INSERT INTO users (id, phone, wechat, org, password_salt, password_hash, credits, free_trial_used, role, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'user', ?)
        """,
        (user_id, phone_n, wechat_n, org_n, salt, pwd_hash, _now()),
    )
    user = sanitize_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone(), conn)
    log_admin_event(
        conn,
        "user_registered",
        f"新用户注册：{org_n} / {phone_n} / 微信 {wechat_n}",
        {"user_id": user_id, "phone": phone_n, "wechat": wechat_n, "org": org_n},
    )
    token = create_session(conn, user_id)
    return user, token


def grant_free_trial(conn: sqlite3.Connection, user_id: str) -> None:
    row = conn.execute("SELECT free_trial_used FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or row["free_trial_used"]:
        return
    add_credit_bucket(conn, user_id, 1, ATTEMPTS_SINGLE, "trial")
    conn.execute("UPDATE users SET free_trial_used = 1 WHERE id = ?", (user_id,))


def create_session(conn: sqlite3.Connection, user_id: str) -> str:
    prune_expired_sessions(conn)
    token = secrets.token_hex(32)
    expires = _now() + SESSION_DAYS * 86400
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires),
    )
    return token


def login_user(conn: sqlite3.Connection, phone: str, password: str) -> tuple[dict[str, Any], str]:
    phone_n = normalize_phone(phone)
    pwd = str(password or "").strip()
    row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone_n,)).fetchone()
    if not row:
        raise ValueError("手机号或密码错误。")
    if not _verify_password(pwd, row["password_salt"], row["password_hash"]):
        raise ValueError("手机号或密码错误。")
    stored = str(row["password_hash"] or "")
    if not stored.startswith("pbkdf2-sha256$"):
        salt, new_hash = _hash_password(pwd)
        conn.execute(
            "UPDATE users SET password_salt = ?, password_hash = ? WHERE id = ?",
            (salt, new_hash, row["id"]),
        )
    token = create_session(conn, row["id"])
    return sanitize_user(row, conn), token


def logout_token(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def usage_summary(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    credits = total_user_credits(conn, user_id)
    row = conn.execute("SELECT free_trial_used FROM users WHERE id = ?", (user_id,)).fetchone()
    owner_vip = is_owner_user_id(conn, user_id)
    now = _now()
    expiry_row = conn.execute(
        """
        SELECT MIN(expires_at) AS nearest FROM credit_buckets
        WHERE user_id = ? AND credits_remaining > 0 AND expires_at IS NOT NULL AND expires_at > ?
        """,
        (user_id, now),
    ).fetchone()
    consult_row = conn.execute(
        """
        SELECT expires_at FROM credit_buckets
        WHERE user_id = ? AND source = 'consult_5000' AND expires_at IS NOT NULL AND expires_at > ?
        ORDER BY expires_at DESC LIMIT 1
        """,
        (user_id, now),
    ).fetchone()
    nearest_expiry = int(expiry_row["nearest"]) if expiry_row and expiry_row["nearest"] else None
    consult_expiry = int(consult_row["expires_at"]) if consult_row and consult_row["expires_at"] else None
    display_expiry = nearest_expiry or consult_expiry
    labels = ["老板 VIP · 无限权限"] if owner_vip else [f"剩余 {credits} 次"]
    if display_expiry:
        days_left = max(0, (display_expiry - now + 86399) // 86400)
        expiry_text = datetime.fromtimestamp(display_expiry).strftime("%Y-%m-%d %H:%M")
        labels.append(f"有效期还剩 {days_left} 天")
        labels.append(f"至 {expiry_text}")
    return {
        "credits": credits,
        "attempts_per_theme": MODIFICATIONS_PER_THEME,
        "max_attempts_per_theme": ATTEMPTS_PER_THEME,
        "pack_attempts_per_theme": ATTEMPTS_PACK,
        "free_trial_used": bool(row and row["free_trial_used"]),
        "credits_expires_at": display_expiry or nearest_expiry,
        "days_remaining": max(0, (display_expiry - now + 86399) // 86400) if display_expiry else None,
        "has_consult_membership": bool(consult_row),
        "owner_vip": owner_vip,
        "owner_greeting": OWNER_GREETING if owner_vip else "",
        "payment_privilege_message": OWNER_PRIVILEGE_MESSAGE if owner_vip else "",
        "plan_label": " · ".join(labels),
    }


def resolve_slot(
    conn: sqlite3.Connection,
    user_id: str,
    slot_id: str | None,
    key: str,
    bucket_id: str | None = None,
) -> tuple[str, bool, bool]:
    """Return (slot_id, is_modify, pack_credit_consumed_for_modify)."""
    pack_credit_consumed = False
    if slot_id:
        slot = conn.execute(
            "SELECT * FROM generation_slots WHERE id = ? AND user_id = ?",
            (slot_id, user_id),
        ).fetchone()
        if not slot:
            raise ValueError("生成会话无效，请重新创建。")
        if slot["prompt_key"] != key:
            raise ValueError("主题不可变更。如需新主题请点「新建海报」。")
        if is_owner_user_id(conn, user_id):
            conn.execute("UPDATE generation_slots SET max_attempts = ? WHERE id = ?", (OWNER_SLOT_ATTEMPTS, slot_id))
            return slot_id, True, False
        slot_credit_attempts = int(slot["credit_attempts"] or ATTEMPTS_SINGLE)
        max_attempts = int(slot["max_attempts"] or ATTEMPTS_PER_THEME)
        attempts_used = int(slot["attempts_used"] or 0)
        if attempts_used >= max_attempts:
            if allows_bundle_modify(slot_credit_attempts):
                raise ValueError(
                    f"该主题已用完 {max_attempts} 次生成/修改机会，请新建海报或购买新额度。"
                )
            if not bucket_id and active_credit_bucket_count(conn, user_id) > 1:
                raise ValueError("继续修改将另计1次额度，请先选择本次使用的套餐。")
            new_attempts = consume_credit_bucket(conn, user_id, bucket_id)
            if allows_bundle_modify(new_attempts):
                raise ValueError(
                    "该主题由套餐类额度创建，继续修改须使用月度/季度/包年/批量类额度；"
                    "免费体验或单张包额度不能用于此类修改。"
                )
            conn.execute(
                "UPDATE generation_slots SET max_attempts = max_attempts + 1 WHERE id = ?",
                (slot_id,),
            )
            pack_credit_consumed = True
        elif attempts_used <= 0:
            raise ValueError("请先生成首张海报，再使用修改功能。")
        return slot_id, True, pack_credit_consumed

    if active_credit_bucket_count(conn, user_id) > 1 and not bucket_id:
        raise ValueError("您有多档可用额度，请先在生成页选择本次使用的套餐。")

    if is_owner_user_id(conn, user_id):
        credit_attempts = ATTEMPTS_PACK
        max_attempts = OWNER_SLOT_ATTEMPTS
    else:
        try:
            credit_attempts = consume_credit_bucket(conn, user_id, bucket_id)
        except ValueError as exc:
            raise ValueError(str(exc) or "credit not enough")
    max_attempts = OWNER_SLOT_ATTEMPTS if is_owner_user_id(conn, user_id) else max_attempts_for_credit(credit_attempts)

    new_id = secrets.token_hex(16)
    conn.execute(
        """
        INSERT INTO generation_slots
        (id, user_id, prompt_key, attempts_used, max_attempts, credit_attempts, created_at)
        VALUES (?, ?, ?, 0, ?, ?, ?)
        """,
        (new_id, user_id, key, max_attempts, credit_attempts, _now()),
    )
    return new_id, False, False


def rollback_pack_modify_credit(conn: sqlite3.Connection, user_id: str, slot_id: str) -> None:
    conn.execute(
        """
        UPDATE generation_slots
        SET max_attempts = max_attempts - 1
        WHERE id = ? AND user_id = ? AND credit_attempts < ?
          AND max_attempts > attempts_used
        """,
        (slot_id, user_id, ATTEMPTS_SINGLE),
    )
    if conn.execute("SELECT changes()").fetchone()[0]:
        refund_credit_bucket(conn, user_id, ATTEMPTS_PACK)


def get_slot_status(conn: sqlite3.Connection, slot_id: str, user_id: str) -> dict[str, Any]:
    slot = conn.execute(
        "SELECT * FROM generation_slots WHERE id = ? AND user_id = ?",
        (slot_id, user_id),
    ).fetchone()
    if not slot:
        raise ValueError("生成会话无效。")
    attempts_used = int(slot["attempts_used"] or 0)
    max_attempts = int(slot["max_attempts"] or ATTEMPTS_PER_THEME)
    slot_credit_attempts = int(slot["credit_attempts"] or ATTEMPTS_SINGLE)
    remaining = max(0, max_attempts - attempts_used)
    bundle_modify = allows_bundle_modify(slot_credit_attempts)
    pack_modify_available = not bundle_modify and attempts_used > 0 and total_user_credits(conn, user_id) > 0
    job = conn.execute(
        """
        SELECT * FROM poster_jobs
        WHERE slot_id = ? AND user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (slot_id, user_id),
    ).fetchone()
    locked: dict[str, str] | None = None
    title = ""
    if job:
        item = conn.execute(
            "SELECT title FROM poster_items WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job["id"],),
        ).fetchone()
        title = str(item["title"] or "") if item else ""
        locked = {
            "campaign_name": str(job["campaign_name"] or ""),
            "template_key": str(job["template_key"] or ""),
            "subject": str(job["subject"] or ""),
            "audience": str(job["audience"] or ""),
            "title": title,
        }
    return {
        "slot_id": slot_id,
        "attempts_used": attempts_used,
        "max_attempts": max_attempts,
        "remaining_modifications": remaining,
        "can_modify": attempts_used > 0 and (remaining > 0 or pack_modify_available),
        "allows_bundle_modify": bundle_modify,
        "needs_credit_for_modify": pack_modify_available and remaining <= 0,
        "modify_rule": bucket_modify_rule_label(slot_credit_attempts),
        "locked": locked,
    }


def release_slot_credit(conn: sqlite3.Connection, user_id: str, slot_id: str) -> None:
    slot = conn.execute(
        """
        SELECT credit_attempts, max_attempts FROM generation_slots
        WHERE id = ? AND user_id = ? AND attempts_used = 0
        """,
        (slot_id, user_id),
    ).fetchone()
    if not slot:
        return
    conn.execute("DELETE FROM generation_slots WHERE id = ? AND user_id = ?", (slot_id, user_id))
    refund_attempts = int(slot["credit_attempts"] or slot["max_attempts"] or ATTEMPTS_SINGLE)
    refund_credit_bucket(conn, user_id, refund_attempts)


def increment_slot_attempt(conn: sqlite3.Connection, slot_id: str) -> None:
    conn.execute(
        """
        UPDATE generation_slots
        SET attempts_used = attempts_used + 1
        WHERE id = ? AND attempts_used < max_attempts
        """,
        (slot_id,),
    )
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        raise ValueError("该主题的生成/修改次数已用完。")


def parse_screenshot(data_url: str) -> tuple[bytes, str, str]:
    raw = str(data_url or "").strip()
    match = re.match(r"^data:(image/(?:jpeg|jpg|png|webp));base64,([A-Za-z0-9+/=]+)$", raw, re.I)
    if not match:
        raise ValueError("请上传 JPG / PNG / WebP 格式的支付截图。")
    buffer = base64.b64decode(match.group(2))
    if len(buffer) > 4 * 1024 * 1024:
        raise ValueError("截图不能超过 4MB。")
    if len(buffer) < 800:
        raise ValueError("截图文件过小，请上传清晰截图。")
    mime = match.group(1).lower().replace("jpg", "jpeg")
    file_hash = hashlib.sha256(buffer).hexdigest()
    return buffer, mime, file_hash


def _payment_success_message(plan_id: str, plan: dict[str, Any], credits: int) -> str:
    if plan_id == "consult_5000":
        return f"已开通 ¥5000 包年会员，一年内 {credits} 次设计额度，并含品牌咨询顾问服务（每月 1 次），请在一年内用完。"
    if plan_id == "vip_10000":
        monthly = int(plan.get("monthly_credits") or 20)
        return f"已开通 ¥10000 包年尊享定制会员，每月 {monthly} 次设计额度（365 天服务期），并享个性化定制服务。"
    if plan_id == "pack_100":
        return f"支付已确认，已增加 {credits} 次设计额度，请在 3 个月内使用完毕。"
    return f"支付已确认，已增加 {credits} 次设计额度。"


def _fulfill_payment_claim(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    claim_id: str,
    plan_id: str,
    plan: dict[str, Any],
    credits: int,
    amount: float,
) -> dict[str, Any]:
    attempts_per_slot = int(plan.get("attempts_per_slot") or ATTEMPTS_PACK)
    expires_at: int | None = None
    monthly_credits: int | None = None
    valid_days = int(plan.get("valid_days") or 0)
    if valid_days > 0:
        expires_at = _now() + valid_days * 86400
    if plan.get("monthly_credits"):
        monthly_credits = int(plan["monthly_credits"])

    if credits > 0 or monthly_credits or plan_id == "consult_5000":
        add_credit_bucket(
            conn,
            user["id"],
            credits,
            attempts_per_slot,
            plan_id,
            expires_at=expires_at,
            monthly_credits=monthly_credits,
        )

    message = _payment_success_message(plan_id, plan, credits)
    log_admin_event(
        conn,
        "payment_received",
        f"用户 {user['org']} 支付 ¥{amount}，套餐 {plan['name']}"
        + (f"，+{credits} 次" if credits else ""),
        {
            "user_id": user["id"],
            "claim_id": claim_id,
            "amount": amount,
            "credits": credits,
            "plan_id": plan_id,
        },
    )
    return {
        "id": claim_id,
        "plan_id": plan_id,
        "amount": amount,
        "credits_added": credits,
        "status": "approved",
        "message": message,
    }


def approve_payment_claim(conn: sqlite3.Connection, claim_id: str, admin_user: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM payment_claims WHERE id = ?", (claim_id,)).fetchone()
    if not row:
        raise ValueError("支付记录不存在。")
    if row["status"] == "approved":
        raise ValueError("该支付已审核通过。")
    if row["status"] == "rejected":
        raise ValueError("该支付已驳回，无法通过。")
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if not user:
        raise ValueError("用户不存在。")
    plan = PAYMENT_PLANS.get(row["plan_id"])
    if not plan:
        raise ValueError("套餐无效。")
    conn.execute("UPDATE payment_claims SET status = 'approved' WHERE id = ?", (claim_id,))
    result = _fulfill_payment_claim(
        conn,
        dict(user),
        claim_id,
        str(row["plan_id"]),
        plan,
        int(row["credits"] or 0),
        float(row["amount"] or 0),
    )
    log_admin_event(
        conn,
        "payment_approved",
        f"管理员 {admin_user.get('org', 'admin')} 通过支付 {claim_id}",
        {"claim_id": claim_id, "admin_id": admin_user["id"]},
    )
    return result


def reject_payment_claim(
    conn: sqlite3.Connection,
    claim_id: str,
    admin_user: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM payment_claims WHERE id = ?", (claim_id,)).fetchone()
    if not row:
        raise ValueError("支付记录不存在。")
    if row["status"] != "pending":
        raise ValueError("仅待审核的支付可驳回。")
    conn.execute("UPDATE payment_claims SET status = 'rejected' WHERE id = ?", (claim_id,))
    note = str(reason or "").strip()[:200]
    log_admin_event(
        conn,
        "payment_rejected",
        f"管理员驳回支付 {claim_id}" + (f"：{note}" if note else ""),
        {"claim_id": claim_id, "admin_id": admin_user["id"], "reason": note},
    )
    return {"id": claim_id, "status": "rejected", "message": "已驳回该支付申请。"}


def halt_payment_claim(
    conn: sqlite3.Connection,
    claim_id: str,
    admin_user: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM payment_claims WHERE id = ?", (claim_id,)).fetchone()
    if not row:
        raise ValueError("支付记录不存在。")
    if row["status"] == "halted":
        raise ValueError("该支付已叫停。")
    note = str(reason or "").strip()[:200]
    conn.execute("UPDATE payment_claims SET status = 'halted' WHERE id = ?", (claim_id,))
    log_admin_event(
        conn,
        "payment_halted",
        f"管理员紧急叫停支付 {claim_id}" + (f"：{note}" if note else ""),
        {"claim_id": claim_id, "admin_id": admin_user["id"], "reason": note},
    )
    return {"id": claim_id, "status": "halted", "message": "已将该支付记录标记为紧急叫停。"}


def update_invoice_status(
    conn: sqlite3.Connection,
    request_id: str,
    status: str,
    admin_user: dict[str, Any],
) -> dict[str, Any]:
    allowed = {"pending", "processed", "rejected"}
    if status not in allowed:
        raise ValueError("无效的状态。")
    row = conn.execute("SELECT * FROM invoice_requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError("开票申请不存在。")
    conn.execute("UPDATE invoice_requests SET status = ? WHERE id = ?", (status, request_id))
    log_admin_event(
        conn,
        "invoice_status",
        f"开票 {request_id} → {status}（{admin_user.get('org', 'admin')}）",
        {"request_id": request_id, "status": status},
    )
    return {"id": request_id, "status": status}


def save_screenshot(claim_id: str, buffer: bytes, mime: str) -> str:
    ext = "png" if "png" in mime else "webp" if "webp" in mime else "jpg"
    filename = f"{claim_id}.{ext}"
    (PAYMENT_SCREENSHOT_DIR / filename).write_bytes(buffer)
    return filename


def resolve_plan_pricing(
    plan_id: str,
    plan: dict[str, Any],
    bulk_quantity: int | None = None,
) -> tuple[int, float, int | None]:
    credits = int(plan.get("credits") or 0)
    amount = float(plan.get("amount") or 0)
    bulk_qty: int | None = None
    if plan_id == "bulk":
        qty = int(bulk_quantity or 0)
        if qty < int(plan.get("min_quantity") or 20):
            raise ValueError("企业批量至少购买 20 张（公司转账最低 200 元）。")
        unit = float(plan.get("unit_price") or 10)
        amount = round(qty * unit, 2)
        min_amount = float(plan.get("min_amount") or 0)
        if amount < min_amount:
            raise ValueError(f"公司转账最低 ¥{int(min_amount)}。")
        credits = qty
        bulk_qty = qty
    return credits, amount, bulk_qty


def complete_wechat_payment(
    conn: sqlite3.Connection,
    claim_id: str,
    transaction_id: str = "",
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM payment_claims WHERE id = ?", (claim_id,)).fetchone()
    if not row:
        raise ValueError("支付订单不存在。")
    if row["status"] == "approved":
        user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        return {
            "id": claim_id,
            "plan_id": row["plan_id"],
            "amount": row["amount"],
            "credits_added": 0,
            "status": "approved",
            "message": "订单已到账。",
            "already_completed": True,
            "user_id": row["user_id"],
        }
    if row["status"] not in {"pending", "paying"}:
        raise ValueError(f"订单状态不可完成：{row['status']}")
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if not user:
        raise ValueError("用户不存在。")
    plan = PAYMENT_PLANS.get(str(row["plan_id"]))
    if not plan:
        raise ValueError("套餐不存在。")
    if transaction_id:
        conn.execute(
            "UPDATE payment_claims SET wechat_transaction_id = ? WHERE id = ?",
            (transaction_id, claim_id),
        )
    conn.execute("UPDATE payment_claims SET status = 'approved' WHERE id = ?", (claim_id,))
    return _fulfill_payment_claim(
        conn,
        dict(user),
        claim_id,
        str(row["plan_id"]),
        plan,
        int(row["credits"] or 0),
        float(row["amount"] or 0),
    )


def create_wechat_native_payment(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    *,
    plan_id: str,
    contract_accepted: bool,
    bulk_quantity: int | None = None,
    config: dict[str, Any],
) -> dict[str, Any]:
    if not contract_accepted:
        raise ValueError("请先阅读并同意《用户使用须知》。")
    plan = PAYMENT_PLANS.get(plan_id)
    if not plan:
        raise ValueError("无效的套餐。")
    if plan.get("payment_disabled") is True:
        raise ValueError("该套餐暂未开放在线付款，请联系商务咨询。")
    credits, amount, bulk_qty = resolve_plan_pricing(plan_id, plan, bulk_quantity)

    from wechat_pay_v3 import WeChatPayError, build_wechat_config, create_native_order, qr_image_url, validate_wechat_config

    try:
        import cryptography  # noqa: F401
    except ImportError as exc:
        raise ValueError("服务器未安装 cryptography，请执行 pip install -r requirements.txt 后重启服务。") from exc
    if not wechat_pay_ready(config):
        raise ValueError("微信官方支付尚未配置完成，请联系管理员。")

    claim_id = secrets.token_hex(16)
    cfg = build_wechat_config(config)
    validate_wechat_config(cfg)
    description = f"{plan['name']} · {user.get('org') or 'Poster'}"
    amount_fen = int(round(amount * 100))
    if amount_fen < 1:
        raise ValueError("订单金额无效（微信最低 0.01 元）。")

    conn.execute(
        """
        INSERT INTO payment_claims
        (id, user_id, plan_id, amount, credits, bulk_quantity, phone, screenshot_file, screenshot_hash, status, created_at, payment_channel)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'pending', ?, 'wechat_native')
        """,
        (
            claim_id,
            user["id"],
            plan_id,
            amount,
            credits,
            bulk_qty,
            user.get("phone") or "",
            _now(),
        ),
    )
    conn.commit()

    try:
        code_url, request_id = create_native_order(
            cfg,
            description=description,
            out_trade_no=claim_id,
            amount_fen=amount_fen,
        )
    except WeChatPayError as exc:
        conn.execute("UPDATE payment_claims SET status = 'failed' WHERE id = ?", (claim_id,))
        conn.commit()
        raise ValueError(str(exc)) from exc

    conn.execute("UPDATE payment_claims SET status = 'paying' WHERE id = ?", (claim_id,))
    conn.commit()
    log_admin_event(
        conn,
        "wechat_order_created",
        f"用户 {user['org']} 创建微信 Native 订单 ¥{amount}，套餐 {plan['name']}",
        {"user_id": user["id"], "claim_id": claim_id, "amount": amount, "plan_id": plan_id, "request_id": request_id},
    )
    return {
        "id": claim_id,
        "plan_id": plan_id,
        "amount": amount,
        "credits": credits,
        "status": "paying",
        "code_url": code_url,
        "qr_image_url": qr_image_url(code_url),
        "message": "请使用微信扫一扫完成支付，支付成功后额度将自动到账。",
    }


def sync_wechat_payment_status(
    conn: sqlite3.Connection,
    claim_id: str,
    user_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    from wechat_pay_v3 import WeChatPayError, build_wechat_config, query_order_by_out_trade_no

    row = conn.execute(
        "SELECT * FROM payment_claims WHERE id = ? AND user_id = ?",
        (claim_id, user_id),
    ).fetchone()
    if not row:
        raise ValueError("支付订单不存在。")
    if row["status"] == "approved":
        usage = usage_summary(conn, user_id)
        return {
            "claim": {
                "id": claim_id,
                "status": "approved",
                "amount": row["amount"],
                "credits_added": row["credits"],
                "message": "支付已完成，额度已到账。",
            },
            "usage": usage,
        }
    if row["payment_channel"] != "wechat_native":
        raise ValueError("该订单不是微信支付订单。")
    if row["status"] not in {"pending", "paying"}:
        return {
            "claim": {
                "id": claim_id,
                "status": row["status"],
                "amount": row["amount"],
                "message": "订单已关闭或失败，请重新下单。",
            },
            "usage": usage_summary(conn, user_id),
        }

    cfg = build_wechat_config(config)
    try:
        data, request_id = query_order_by_out_trade_no(cfg, claim_id)
    except WeChatPayError as exc:
        raise ValueError(str(exc)) from exc

    trade_state = str(data.get("trade_state") or "")
    if trade_state == "SUCCESS":
        transaction_id = str(data.get("transaction_id") or "")
        claim = complete_wechat_payment(conn, claim_id, transaction_id)
        usage = usage_summary(conn, user_id)
        return {"claim": claim, "usage": usage, "request_id": request_id}
    if trade_state in {"CLOSED", "REVOKED", "PAYERROR"}:
        conn.execute("UPDATE payment_claims SET status = 'failed' WHERE id = ?", (claim_id,))
        conn.commit()
    return {
        "claim": {
            "id": claim_id,
            "status": "paying" if trade_state in {"NOTPAY", "USERPAYING"} else "failed",
            "amount": row["amount"],
            "trade_state": trade_state,
            "message": "等待支付" if trade_state in {"NOTPAY", "USERPAYING"} else "订单已关闭，请重新下单。",
        },
        "usage": usage_summary(conn, user_id),
        "request_id": request_id,
    }


def handle_wechat_pay_notify(conn: sqlite3.Connection, headers: dict[str, str], body: str, config: dict[str, Any]) -> dict[str, str]:
    from wechat_pay_v3 import WeChatPayError, build_wechat_config, decrypt_notify_resource, verify_notify_signature

    cfg = build_wechat_config(config)
    verify_notify_signature(cfg, headers, body)
    payload = json.loads(body)
    resource = decrypt_notify_resource(cfg, payload.get("resource") or {})
    if resource.get("trade_state") != "SUCCESS":
        return {"code": "SUCCESS", "message": "成功"}
    claim_id = str(resource.get("out_trade_no") or "")
    transaction_id = str(resource.get("transaction_id") or "")
    if not claim_id:
        raise WeChatPayError("回调缺少 out_trade_no")
    complete_wechat_payment(conn, claim_id, transaction_id)
    conn.commit()
    return {"code": "SUCCESS", "message": "成功"}


def submit_payment_claim(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    *,
    plan_id: str,
    screenshot_image: str,
    phone: str,
    contract_accepted: bool,
    bulk_quantity: int | None = None,
) -> dict[str, Any]:
    if not contract_accepted:
        raise ValueError("请先阅读并同意《用户使用须知》。")
    plan = PAYMENT_PLANS.get(plan_id)
    if not plan:
        raise ValueError("无效的套餐。")
    credits, amount, bulk_qty = resolve_plan_pricing(plan_id, plan, bulk_quantity)

    if plan.get("payment_disabled") is True:
        raise ValueError("该套餐暂未开放在线付款，请联系商务咨询。")

    phone_n = normalize_phone(phone or user.get("phone") or "")
    buffer, mime, file_hash = parse_screenshot(screenshot_image)
    auto_approve = os.getenv("PAYMENT_AUTO_APPROVE", "1").lower() in ("1", "true", "yes")
    initial_status = "approved" if auto_approve else "pending"

    claim_id = secrets.token_hex(16)
    screenshot_file = save_screenshot(claim_id, buffer, mime)
    conn.execute(
        """
        INSERT INTO payment_claims
        (id, user_id, plan_id, amount, credits, bulk_quantity, phone, screenshot_file, screenshot_hash, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            claim_id,
            user["id"],
            plan_id,
            amount,
            credits,
            bulk_qty,
            phone_n,
            screenshot_file,
            file_hash,
            initial_status,
            _now(),
        ),
    )
    if initial_status != "approved":
        log_admin_event(
            conn,
            "payment_pending",
            f"用户 {user['org']} 提交 ¥{amount} 支付截图，套餐 {plan['name']}，待审核",
            {"user_id": user["id"], "claim_id": claim_id, "amount": amount, "plan_id": plan_id},
        )
        return {
            "id": claim_id,
            "plan_id": plan_id,
            "amount": amount,
            "credits_added": 0,
            "status": "pending",
            "message": "支付截图已提交，管理员审核通过后将自动开通额度（通常 1 个工作日内）。",
        }

    return _fulfill_payment_claim(
        conn,
        user,
        claim_id,
        plan_id,
        plan,
        credits,
        amount,
    )


def list_invoice_eligible_payments(conn: sqlite3.Connection, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT pc.*
        FROM payment_claims pc
        WHERE pc.user_id = ? AND pc.status = 'approved'
          AND NOT EXISTS (
            SELECT 1 FROM invoice_requests ir
            WHERE ir.payment_claim_id = pc.id AND ir.status != 'rejected'
          )
        ORDER BY pc.created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        plan = PAYMENT_PLANS.get(str(item.get("plan_id") or ""), {})
        item["plan_name"] = plan.get("name") or item.get("plan_id")
        result.append(item)
    return result


def submit_invoice_request(
    conn: sqlite3.Connection,
    user: dict[str, Any],
    *,
    company_name: str,
    tax_id: str,
    contact_email: str,
    invoice_amount: float,
    note: str = "",
    payment_claim_id: str | None = None,
) -> dict[str, Any]:
    company = str(company_name or "").strip()
    tax = str(tax_id or "").strip()
    email = str(contact_email or "").strip()
    claim_id = str(payment_claim_id or "").strip() or None
    if len(company) < 4:
        raise ValueError("请填写完整企业名称。")
    if len(tax) < 15:
        raise ValueError("请填写正确的纳税人识别号。")
    if "@" not in email:
        raise ValueError("请填写有效邮箱。")
    if not claim_id:
        raise ValueError("请选择要开票的支付订单。")

    claim = conn.execute(
        """
        SELECT * FROM payment_claims
        WHERE id = ? AND user_id = ? AND status = 'approved'
        """,
        (claim_id, user["id"]),
    ).fetchone()
    if not claim:
        raise ValueError("所选订单不存在或未到账，无法开票。")
    dup = conn.execute(
        """
        SELECT 1 FROM invoice_requests
        WHERE payment_claim_id = ? AND status != 'rejected'
        """,
        (claim_id,),
    ).fetchone()
    if dup:
        raise ValueError("该订单已有开票申请，请勿重复提交。")

    claim_amount = round(float(claim["amount"] or 0), 2)
    amount = round(float(invoice_amount), 2) if invoice_amount else claim_amount
    if amount <= 0:
        raise ValueError("开票金额须大于 0。")
    if abs(amount - claim_amount) > 0.01:
        raise ValueError(f"开票金额须与订单金额 ¥{claim_amount} 一致。")

    plan = PAYMENT_PLANS.get(str(claim["plan_id"] or ""), {})
    plan_name = plan.get("name") or claim["plan_id"]
    order_note = f"关联订单 {claim_id[:8]}… · {plan_name} · ¥{claim_amount}"
    merged_note = str(note or "").strip()
    if merged_note:
        merged_note = f"{order_note}；{merged_note}"
    else:
        merged_note = order_note

    service_fee = INVOICE_SERVICE_FEE
    total = round(amount + service_fee, 2)
    req_id = secrets.token_hex(16)
    conn.execute(
        """
        INSERT INTO invoice_requests
        (id, user_id, company_name, tax_id, contact_email, invoice_amount, service_fee, total_amount, note, status, created_at, payment_claim_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            req_id,
            user["id"],
            company,
            tax,
            email,
            amount,
            service_fee,
            total,
            merged_note[:500],
            _now(),
            claim_id,
        ),
    )
    log_admin_event(
        conn,
        "invoice_request",
        f"{company} 申请开票 ¥{total}（订单 {claim_id[:8]}… · {plan_name}）",
        {
            "request_id": req_id,
            "user_id": user["id"],
            "total": total,
            "payment_claim_id": claim_id,
            "plan_id": claim["plan_id"],
            "order_amount": claim_amount,
        },
    )
    return {
        "id": req_id,
        "payment_claim_id": claim_id,
        "invoice_amount": amount,
        "service_fee": service_fee,
        "total_amount": total,
        "message": f"开票申请已提交（关联订单 {plan_name} · ¥{amount}），发票总额 ¥{total}（含 ¥{service_fee} 人工服务费）。",
    }


def list_admin_events(conn: sqlite3.Connection, limit: int = 80) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM admin_events ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def parse_reference_images_list(data_urls: list[Any]) -> list[bytes]:
    buffers: list[bytes] = []
    for raw in (data_urls or []):
        text = str(raw or "").strip()
        if not text:
            continue
        match = re.match(
            r"^data:(image/(?:jpeg|jpg|png|webp));base64,([A-Za-z0-9+/=]+)$",
            text,
            re.I,
        )
        if not match:
            raise ValueError("参考图须为 JPG / PNG / WebP 格式。")
        buffer = base64.b64decode(match.group(2))
        if len(buffer) > 2 * 1024 * 1024:
            raise ValueError("每张参考图不能超过 2MB。")
        if len(buffer) < 400:
            raise ValueError("参考图文件过小，请上传清晰图片。")
        buffers.append(buffer)
        if len(buffers) >= MAX_REFERENCE_IMAGES:
            break
    return buffers


def save_reference_images(job_id: str, buffers: list[bytes], mimes: list[str] | None = None) -> list[str]:
    REFERENCE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job_dir = REFERENCE_UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for index, buffer in enumerate(buffers):
        mime = (mimes or [])[index] if mimes and index < len(mimes) else "image/jpeg"
        ext = "png" if "png" in mime else "webp" if "webp" in mime else "jpg"
        path = job_dir / f"ref_{index}.{ext}"
        path.write_bytes(buffer)
        paths.append(str(path.relative_to(ROOT)))
    return paths


def get_generation_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    empty = {
        "total_items": 0,
        "completed_count": 0,
        "failed_count": 0,
        "failure_rate_percent": 0.0,
        "avg_duration_ms": 0,
        "avg_duration_minutes": None,
    }
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                AVG(CASE WHEN status = 'completed' AND duration_ms > 0 THEN duration_ms END) AS avg_duration_ms
            FROM poster_items
            """
        ).fetchone()
    except sqlite3.OperationalError:
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                    NULL AS avg_duration_ms
                FROM poster_items
                """
            ).fetchone()
        except sqlite3.OperationalError:
            return empty
    if not row:
        return empty
    total = int(row["total"] or 0)
    completed = int(row["completed"] or 0)
    failed = int(row["failed"] or 0)
    avg_ms = float(row["avg_duration_ms"] or 0)
    failure_rate = round(failed / total * 100, 1) if total else 0.0
    return {
        "total_items": total,
        "completed_count": completed,
        "failed_count": failed,
        "failure_rate_percent": failure_rate,
        "avg_duration_ms": int(avg_ms),
        "avg_duration_minutes": round(avg_ms / 60000, 1) if avg_ms else None,
    }


def list_users_admin(conn: sqlite3.Connection, limit: int = 300) -> list[dict[str, Any]]:
    now = _now()
    rows = conn.execute(
        """
        SELECT
            u.id, u.phone, u.wechat, u.org, u.credits, u.free_trial_used, u.role, u.created_at,
            COALESCE((
                SELECT SUM(credits_remaining) FROM credit_buckets cb
                WHERE cb.user_id = u.id AND (cb.expires_at IS NULL OR cb.expires_at > ?)
            ), 0) AS bucket_credits,
            (SELECT COUNT(*) FROM poster_jobs WHERE user_id = u.id) AS job_count,
            (SELECT COUNT(*) FROM payment_claims WHERE user_id = u.id AND status = 'approved') AS paid_orders,
            COALESCE((
                SELECT SUM(amount) FROM payment_claims
                WHERE user_id = u.id AND status = 'approved'
            ), 0) AS paid_total
        FROM users u
        ORDER BY u.created_at DESC
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["total_credits"] = int(item["credits"] or 0) + int(item["bucket_credits"] or 0)
        result.append(item)
    return result


def list_payments_admin(conn: sqlite3.Connection, limit: int = 300) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT pc.*, u.org, u.wechat, u.phone AS account_phone
        FROM payment_claims pc
        JOIN users u ON u.id = pc.user_id
        ORDER BY pc.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_invoices_admin(conn: sqlite3.Connection, limit: int = 150) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ir.*, u.org, u.phone AS account_phone,
               pc.plan_id AS order_plan_id, pc.amount AS order_amount, pc.credits AS order_credits,
               pc.bulk_quantity AS order_bulk_quantity, pc.created_at AS order_created_at
        FROM invoice_requests ir
        JOIN users u ON u.id = ir.user_id
        LEFT JOIN payment_claims pc ON pc.id = ir.payment_claim_id
        ORDER BY ir.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        plan_id = str(item.get("order_plan_id") or "")
        plan = PAYMENT_PLANS.get(plan_id, {})
        item["order_plan_name"] = plan.get("name") or plan_id or "—"
        result.append(item)
    return result


def list_user_payments(conn: sqlite3.Connection, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM payment_claims WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def admin_dashboard(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "metrics": get_generation_metrics(conn),
        "users": list_users_admin(conn),
        "payments": list_payments_admin(conn),
        "invoices": list_invoices_admin(conn),
        "events": list_admin_events(conn, 60),
        "user_count": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "payment_total": conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payment_claims WHERE status = 'approved'"
        ).fetchone()[0],
    }


def payment_screenshot_path(claim_id: str) -> Path | None:
    row_dir = PAYMENT_SCREENSHOT_DIR
    for ext in ("jpg", "jpeg", "png", "webp"):
        candidate = row_dir / f"{claim_id}.{ext}"
        if candidate.exists():
            return candidate
    return None


def payment_qr_for_plan(plan_id: str, config: dict[str, Any]) -> str:
    qr_map = config.get("payment_qr") or {}
    if plan_id == "bulk":
        return str(qr_map.get("bulk") or qr_map.get("1000") or qr_map.get("default") or "/assets/qr-pay.svg")
    if plan_id == "vip_10000":
        return str(qr_map.get("10000") or qr_map.get("default") or "/assets/qr-pay.svg")
    if plan_id == "consult_5000":
        return str(qr_map.get("5000") or qr_map.get("default") or "/assets/qr-pay.svg")
    if plan_id == "pack_100":
        return str(qr_map.get("1000") or qr_map.get("default") or "/assets/qr-pay.svg")
    if plan_id == "pack_20":
        return str(qr_map.get("300") or qr_map.get("default") or "/assets/qr-pay.svg")
    if plan_id == "single_50":
        return str(qr_map.get("50") or qr_map.get("default") or "/assets/qr-pay.svg")
    return str(qr_map.get("default") or "/assets/qr-pay.svg")


def ensure_default_admin(conn: sqlite3.Connection) -> None:
    admin_phone = os.getenv("ADMIN_PHONE", "13800000000")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123456")
    sync_pwd = os.getenv("ADMIN_SYNC_PASSWORD", "").lower() in ("1", "true", "yes")

    if sync_pwd:
        row = conn.execute("SELECT id FROM users WHERE phone = ?", (admin_phone,)).fetchone()
        if row:
            salt, pwd_hash = _hash_password(admin_pass)
            conn.execute(
                """
                UPDATE users SET password_salt = ?, password_hash = ?, role = 'admin'
                WHERE phone = ?
                """,
                (salt, pwd_hash, admin_phone),
            )
            return

    owner_row = conn.execute("SELECT id FROM users WHERE phone = ?", (OWNER_PHONE,)).fetchone()
    if owner_row:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (owner_row["id"],))
    row = conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if row:
        return
    if conn.execute("SELECT 1 FROM users WHERE phone = ?", (admin_phone,)).fetchone():
        conn.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (admin_phone,))
        return
    salt, pwd_hash = _hash_password(admin_pass)
    conn.execute(
        """
        INSERT INTO users (id, phone, wechat, org, password_salt, password_hash, credits, free_trial_used, role, created_at)
        VALUES (?, ?, 'admin', '平台管理', ?, ?, 9999, 1, 'admin', ?)
        """,
        (secrets.token_hex(16), admin_phone, salt, pwd_hash, _now()),
    )


def wechat_pay_mode(config: dict[str, Any]) -> str:
    wechat = config.get("wechat_pay") or {}
    if not wechat.get("enabled"):
        return "qr_screenshot"
    trade = str(wechat.get("trade_type") or "native").lower()
    if trade == "jsapi":
        return "wechat_jsapi"
    return "wechat_native"


def wechat_pay_ready(config: dict[str, Any]) -> bool:
    wechat = config.get("wechat_pay") or {}
    if not wechat.get("enabled"):
        return False
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    required = ("mch_id", "app_id", "api_v3_key", "serial_no", "notify_url")
    if not all(str(wechat.get(key) or "").strip() for key in required):
        return False
    key_path = ROOT / str(wechat.get("private_key_path") or "data/apiclient_key.pem")
    return key_path.is_file()


def public_platform_config(config: dict[str, Any], metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    metrics = metrics or {}
    avg_min = metrics.get("avg_duration_minutes")
    failure_rate = metrics.get("failure_rate_percent", 0)
    return {
        "brand_name": config.get("brand_name") or "AI品牌广告图文设计师与知识地图设计师",
        "plans": PUBLIC_PLANS,
        "payment_plans": PAYMENT_PLANS,
        "attempts_per_theme": MODIFICATIONS_PER_THEME,
        "max_attempts_per_theme": ATTEMPTS_PER_THEME,
        "pack_attempts_per_theme": ATTEMPTS_PACK,
        "invoice_service_fee": INVOICE_SERVICE_FEE,
        "payment_mode": wechat_pay_mode(config),
        "wechat_pay_ready": wechat_pay_ready(config),
        "support_wechat": str(config.get("support_wechat") or ""),
        "support_phone": str(config.get("support_phone") or ""),
        "max_reference_images": MAX_REFERENCE_IMAGES,
        "supports_reference_images": True,
        "generation": {
            "typical_minutes": avg_min or 3.0,
            "failure_rate_percent": failure_rate,
            "credit_on_failure": "成功才计算额度",
            "modifications_per_theme": MODIFICATIONS_PER_THEME,
            "note": (
                "单张海报通常 1-3 分钟出图；免费体验与单张包同主题可修改5次；"
                "月度/季度/包年/批量套餐每次修改另计1次；有多档额度时请手动选择本次使用的套餐。"
            ),
        },
    }







