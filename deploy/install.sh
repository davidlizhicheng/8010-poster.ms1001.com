#!/usr/bin/env bash
# Poster 一键安装脚本（在宝塔服务器上以 root 执行）
# 用法: cd /www/wwwroot/poster.ms1001.com && bash deploy/install.sh

set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SERVICE_NAME="poster"
RUN_USER="${RUN_USER:-www}"

echo "==> 安装目录: $APP_DIR"

find_python() {
  local candidates=(
    "${POSTER_PYTHON_BIN:-}"
    /usr/local/python311/bin/python3.11
    /opt/poster-py/bin/python
    /usr/local/python311/bin/python3.11
    /usr/bin/python3.11
    /usr/bin/python3.10
    python3.11
    python3.10
    python3
  )
  for bin in "${candidates[@]}"; do
    [[ -z "$bin" ]] && continue
    if command -v "$bin" >/dev/null 2>&1; then
      local ver
      ver=$("$bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
      local major minor
      major=${ver%%.*}
      minor=${ver#*.}
      if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
        echo "$bin"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN=""
if find_python >/dev/null 2>&1; then
  PYTHON_BIN=$(find_python)
else
  echo "错误: 需要 Python 3.10+，当前系统 python3 过旧（CentOS7 多为 3.6）。"
  echo "请先执行（CentOS 7）: bash deploy/install-python311-centos7.sh"
  echo "或: bash deploy/install-python311.sh"
  echo "然后重新运行: bash deploy/install.sh"
  exit 1
fi

PY_VERSION=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "==> 使用 $PYTHON_BIN (Python $PY_VERSION)"

if [[ -f "$APP_DIR/requirements.txt" ]]; then
  echo "==> 安装 Python 依赖..."
  "$PYTHON_BIN" -m pip install -r "$APP_DIR/requirements.txt" -q
  "$PYTHON_BIN" -c "import cryptography" || {
    echo "错误: cryptography 安装失败，微信支付不可用。"
    exit 1
  }
fi

mkdir -p "$APP_DIR/data" "$APP_DIR/outputs" "$APP_DIR/data/payment-screenshots" "$APP_DIR/data/reference-images"
bash "$APP_DIR/deploy/fix-data-perms.sh"

if [[ ! -f "$APP_DIR/data/config.json" ]]; then
  if [[ -f "$APP_DIR/data/config.example.json" ]]; then
    cp "$APP_DIR/data/config.example.json" "$APP_DIR/data/config.json"
    echo "==> 已生成 data/config.json，请编辑 API Key"
  fi
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  if [[ -f "$APP_DIR/deploy/production.env" ]]; then
    cp "$APP_DIR/deploy/production.env" "$APP_DIR/.env"
    echo "==> 已从 deploy/production.env 生成 .env，请修改 ADMIN_PASSWORD 与 MINIMAX_API_KEY"
  else
    cp "$APP_DIR/deploy/env.example" "$APP_DIR/.env"
    echo "==> 已生成 .env，请修改管理员密码与 POSTER_SECURE_COOKIE"
  fi
fi

POSTER_PORT=8010
if [[ -f "$APP_DIR/.env" ]]; then
  POSTER_PORT=$(grep -E '^PORT=' "$APP_DIR/.env" | tail -1 | cut -d= -f2- | tr -d '\r"'"'"' ' || true)
  POSTER_PORT=${POSTER_PORT:-8010}
  if grep -qE '^AUTH_BASE_URL=.*(127\.0\.0\.1|localhost)' "$APP_DIR/.env"; then
    echo "警告: .env 中 AUTH_BASE_URL 指向本机，线上应使用 https://ai.ms1001.com"
    sed -i 's|^AUTH_BASE_URL=.*|AUTH_BASE_URL=https://ai.ms1001.com|' "$APP_DIR/.env"
    echo "==> 已修正 AUTH_BASE_URL=https://ai.ms1001.com"
  fi
fi
if [[ "$POSTER_PORT" != "8010" ]]; then
  echo "警告: .env 中 PORT=$POSTER_PORT，Nginx 默认反代 8010，请改为 PORT=8010 或同步改 Nginx"
fi

UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__PYTHON_BIN__|$PYTHON_BIN|g" \
  "$APP_DIR/deploy/poster.service" > "$UNIT_DST"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 2
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${POSTER_PORT}/api/config" || echo "000")
  echo "==> 本机 http://127.0.0.1:${POSTER_PORT}/api/config → HTTP $code"
  if [[ "$code" != "200" ]]; then
    echo "错误: 后端未在 ${POSTER_PORT} 端口响应，查看日志:"
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager
    exit 1
  fi
fi
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "错误: poster 服务启动失败，查看日志:"
  journalctl -u "$SERVICE_NAME" -n 20 --no-pager
  exit 1
fi
systemctl --no-pager status "$SERVICE_NAME" || true

echo ""
echo "=============================================="
echo "  Poster 后端已启动 (systemd: $SERVICE_NAME)"
echo "  Python: $PYTHON_BIN ($PY_VERSION)"
echo "  本机测试: curl -I http://127.0.0.1:${POSTER_PORT}/"
echo ""
echo "  快捷命令（已安装 poster → deploy/posterctl.sh）:"
echo "    poster r    重启并检查"
echo "    poster s    查看状态"
echo "    poster l    查看日志"
echo "=============================================="

# 全局快捷命令 poster（任意目录可用）
POSTER_BIN="/usr/local/bin/poster"
cat > "$POSTER_BIN" <<EOF
#!/usr/bin/env bash
export APP_DIR="$APP_DIR"
exec bash "$APP_DIR/deploy/posterctl.sh" "\$@"
EOF
chmod +x "$POSTER_BIN"
echo "==> 已安装: poster r | poster s | poster l"
