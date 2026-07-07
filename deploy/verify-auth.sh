#!/usr/bin/env bash
# 在服务器上验证注册/登录链路
set -euo pipefail
APP_DIR="${APP_DIR:-/www/wwwroot/poster.ms1001.com}"
PY="${POSTER_PYTHON:-/usr/local/python311/bin/python3.11}"
BASE="${POSTER_BASE_URL:-http://127.0.0.1:8010}"

cd "$APP_DIR"
"$PY" -c "from poster_platform import verify_auth_stack; verify_auth_stack(); print('password self-test OK')"

PHONE="139$(date +%s | tail -c 8)"
PASS="test$(date +%s | tail -c 6)99"

echo "==> register $PHONE"
curl -sS -c /tmp/poster-cookie.txt -H 'Content-Type: application/json' \
  -d "{\"phone\":\"$PHONE\",\"wechat\":\"testwx\",\"org\":\"测试单位\",\"password\":\"$PASS\"}" \
  "$BASE/api/auth/register" | head -c 200
echo ""

echo "==> login $PHONE"
curl -sS -b /tmp/poster-cookie.txt -c /tmp/poster-cookie.txt -H 'Content-Type: application/json' \
  -d "{\"phone\":\"$PHONE\",\"password\":\"$PASS\"}" \
  "$BASE/api/auth/login" | head -c 200
echo ""

echo "==> me"
curl -sS -b /tmp/poster-cookie.txt "$BASE/api/auth/me" | head -c 200
echo ""
