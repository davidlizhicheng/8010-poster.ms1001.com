#!/usr/bin/env bash
# Poster 服务快捷管理（替代 systemctl restart/status poster）
#
#   bash deploy/posterctl.sh r      # 重启并检查
#   bash deploy/posterctl.sh s      # 查看状态
#   bash deploy/posterctl.sh l      # 最近日志
#   bash deploy/posterctl.sh t      # 自检
#
# 安装后可全局使用（install.sh 会写入 /usr/local/bin/poster）:
#   poster r
#   poster s

set -euo pipefail
APP_DIR="${APP_DIR:-/www/wwwroot/poster.ms1001.com}"
SERVICE="${POSTER_SERVICE:-poster}"
PY="${POSTER_PYTHON:-/usr/local/python311/bin/python3.11}"
BASE="${POSTER_BASE_URL:-http://127.0.0.1:8010}"

raw="${1:-s}"
case "$raw" in
  r|restart) cmd=restart ;;
  s|status)  cmd=status ;;
  l|logs)    cmd=logs ;;
  t|test)    cmd=test ;;
  *)         cmd="$raw" ;;
esac

case "$cmd" in
  restart)
    bash "$APP_DIR/deploy/restart.sh"
    ;;
  status)
    systemctl status "$SERVICE" --no-pager -l | head -n 12 || true
    ;;
  logs)
    journalctl -u "$SERVICE" -n 50 --no-pager
    ;;
  test)
    cd "$APP_DIR"
    "$PY" -c "from poster_platform import verify_auth_stack; verify_auth_stack(); print('password OK')"
    curl -sI "$BASE/" | head -n 5
    curl -sI "$BASE/styles.css" | head -n 3
    ;;
  *)
    echo "用法: poster [r|s|l|t]"
    echo "  r  重启并检查（等同 restart.sh）"
    echo "  s  查看状态"
    echo "  l  最近日志"
    echo "  t  自检"
    exit 1
    ;;
esac
