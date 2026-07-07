#!/usr/bin/env bash
# 修复 data/ poster.db 只读导致服务无法启动
# 用法: bash deploy/fix-data-perms.sh

set -euo pipefail
APP_DIR="${APP_DIR:-/www/wwwroot/poster.ms1001.com}"
RUN_USER="${RUN_USER:-www}"

mkdir -p \
  "$APP_DIR/data" \
  "$APP_DIR/outputs" \
  "$APP_DIR/data/payment-screenshots" \
  "$APP_DIR/data/reference-images"

chown -R "$RUN_USER:$RUN_USER" "$APP_DIR/data" "$APP_DIR/outputs"
chmod 775 "$APP_DIR/data" "$APP_DIR/outputs"
find "$APP_DIR/data" "$APP_DIR/outputs" -type d -exec chmod 775 {} \; 2>/dev/null || true
find "$APP_DIR/data" "$APP_DIR/outputs" -type f -exec chmod 664 {} \; 2>/dev/null || true

echo "==> 已修复权限: $APP_DIR/data 与 outputs → $RUN_USER:$RUN_USER (775/664)"
