"""Unit tests for owner VIP + unified auth linkage."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from poster_platform import (  # noqa: E402
    OWNER_PHONE,
    ensure_user_from_unified_auth,
    ensure_platform_tables,
    is_owner_from_unified_claims,
    list_user_credit_buckets,
    sync_owner_from_unified_auth,
    usage_summary,
)


def test_owner_claims_by_phone() -> None:
    claims = {"username": OWNER_PHONE, "role": "USER", "tier": "standard"}
    assert is_owner_from_unified_claims(claims) is True


def test_owner_claims_by_is_owner_flag() -> None:
    claims = {"username": "other", "isOwner": True}
    assert is_owner_from_unified_claims(claims) is True


def test_sync_owner_updates_phone_and_admin() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_platform_tables(conn)
    user_id = "u1"
    conn.execute(
        """
        INSERT INTO users (id, phone, wechat, org, password_salt, password_hash, credits, free_trial_used, role, created_at)
        VALUES (?, '13800000001', 'wx', '测试', 's', 'h', 0, 0, 'user', 1)
        """,
        (user_id,),
    )
    sync_owner_from_unified_auth(conn, user_id, {"username": OWNER_PHONE, "role": "BETA", "tier": "vip"})
    row = conn.execute("SELECT phone, role FROM users WHERE id = ?", (user_id,)).fetchone()
    assert row["phone"] == OWNER_PHONE
    assert row["role"] == "admin"
    usage = usage_summary(conn, user_id)
    assert usage["owner_vip"] is True
    assert "无限权限" in usage["plan_label"]


def test_ensure_user_from_unified_auth_owner() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_platform_tables(conn)
    claims = {
        "username": OWNER_PHONE,
        "phone": OWNER_PHONE,
        "name": "李总",
        "role": "BETA",
        "tier": "vip",
        "platformPermissions": {"*": "full"},
    }
    user, created = ensure_user_from_unified_auth(conn, claims)
    assert created is True
    assert user["phone"] == OWNER_PHONE
    assert user["owner_vip"] is True
    usage = usage_summary(conn, user["id"])
    assert usage["owner_vip"] is True


def test_owner_credit_buckets() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_platform_tables(conn)
    claims = {"username": OWNER_PHONE, "phone": OWNER_PHONE, "role": "USER"}
    user, _created = ensure_user_from_unified_auth(conn, claims)
    conn.commit()
    buckets = list_user_credit_buckets(conn, user["id"])
    assert len(buckets) == 1
    assert buckets[0]["id"] == "owner_vip"
    assert buckets[0]["label"] == "老板 VIP"
    assert "免费体验" not in buckets[0]["label"]


def main() -> None:
    test_owner_claims_by_phone()
    test_owner_claims_by_is_owner_flag()
    test_sync_owner_updates_phone_and_admin()
    test_ensure_user_from_unified_auth_owner()
    test_owner_credit_buckets()
    print("OK: owner unified auth tests passed")


if __name__ == "__main__":
    main()
