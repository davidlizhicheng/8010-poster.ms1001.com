#!/usr/bin/env bash
# 上传代码后在服务器执行一次即可
set -euo pipefail
cd "$(dirname "$0")/.."

cp deploy/production.env .env
cp deploy/config.production.json data/config.json

if [[ ! -f data/apiclient_key.pem ]]; then
  echo "警告: 缺少 data/apiclient_key.pem（微信支付私钥），请从本机 data/ 上传"
fi

chown -R www:www data outputs .env
chmod 640 .env
bash deploy/install.sh
