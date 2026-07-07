#!/usr/bin/env python3
"""重置用户密码（服务器端 pbkdf2，解决 CentOS7 无法校验旧 scrypt 哈希）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlite3

from poster_platform import DATA_DIR, reset_user_password


def main() -> None:
    if len(sys.argv) != 3:
        print("用法: python3 deploy/reset_password.py <手机号> <新密码>")
        raise SystemExit(1)
    phone, password = sys.argv[1], sys.argv[2]
    db_path = DATA_DIR / "poster.db"
    conn = sqlite3.connect(db_path)
    reset_user_password(conn, phone, password)
    conn.commit()
    conn.close()
    print(f"已重置 {phone} 的密码，请重新登录。")


if __name__ == "__main__":
    main()
