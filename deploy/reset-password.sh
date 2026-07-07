#!/usr/bin/env bash
# 重置指定用户密码
# 用法: bash deploy/reset-password.sh 13800000000 你的新密码

set -euo pipefail
APP_DIR="${APP_DIR:-/www/wwwroot/poster.ms1001.com}"
PY="${POSTER_PYTHON:-/usr/local/python311/bin/python3.11}"

if [[ $# -lt 2 ]]; then
  echo "用法: bash deploy/reset-password.sh <手机号> <新密码>"
  exit 1
fi

cd "$APP_DIR"
"$PY" deploy/reset_password.py "$1" "$2"
