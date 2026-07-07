#!/usr/bin/env bash
# 一键重启 Poster 服务
# 用法: bash deploy/restart.sh

set -euo pipefail
APP_DIR="${APP_DIR:-/www/wwwroot/poster.ms1001.com}"
SERVICE="${POSTER_SERVICE:-poster}"

echo "==> 重启 $SERVICE ..."
bash "$APP_DIR/deploy/fix-data-perms.sh"
systemctl restart "$SERVICE"
sleep 1

if systemctl is-active --quiet "$SERVICE"; then
  echo "==> 运行正常"
  systemctl status "$SERVICE" --no-pager -l | head -n 8
  if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8010/ || echo "000")
  echo "==> 本机访问 http://127.0.0.1:8010/ → HTTP $code"
  fi
else
  echo "==> 启动失败，最近日志："
  journalctl -u "$SERVICE" -n 20 --no-pager
  exit 1
fi
