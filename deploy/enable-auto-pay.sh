#!/usr/bin/env bash
# 开启支付截图自动开通，并重启服务
# 用法: bash deploy/enable-auto-pay.sh

set -euo pipefail
APP_DIR="${APP_DIR:-/www/wwwroot/poster.ms1001.com}"
ENV_FILE="$APP_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$APP_DIR/deploy/env.example" "$ENV_FILE"
fi

if grep -q '^PAYMENT_AUTO_APPROVE=' "$ENV_FILE"; then
  sed -i 's/^PAYMENT_AUTO_APPROVE=.*/PAYMENT_AUTO_APPROVE=1/' "$ENV_FILE"
else
  echo 'PAYMENT_AUTO_APPROVE=1' >> "$ENV_FILE"
fi

echo "==> 已设置 PAYMENT_AUTO_APPROVE=1"
bash "$APP_DIR/deploy/posterctl.sh" r
