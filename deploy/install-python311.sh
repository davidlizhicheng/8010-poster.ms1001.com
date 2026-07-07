#!/usr/bin/env bash
# CentOS 7 等老系统：源码编译 Python 3.11（Miniconda 需要 glibc>=2.28）
# 新系统可用 Miniconda 版: deploy/install-python311.sh
# 用法: bash deploy/install-python311-centos7.sh

set -euo pipefail

if [[ -f /etc/redhat-release ]] && grep -q "release 7" /etc/redhat-release 2>/dev/null; then
  echo "==> 检测到 CentOS/RHEL 7，使用源码编译方式"
  exec bash "$(dirname "$0")/install-python311-centos7.sh"
fi

CONDA_PREFIX="${POSTER_PYTHON_PREFIX:-/opt/poster-py}"
MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"

echo "==> 目标路径: $CONDA_PREFIX"

if [[ -x "$CONDA_PREFIX/bin/python" ]]; then
  echo "==> 已存在: $($CONDA_PREFIX/bin/python --version)"
  exit 0
fi

echo "==> 下载 Miniconda..."
curl -fsSL "$MINICONDA_URL" -o /tmp/miniconda-poster.sh
bash /tmp/miniconda.sh -b -p "$CONDA_PREFIX"
rm -f /tmp/miniconda-poster.sh

echo "==> 安装完成: $($CONDA_PREFIX/bin/python --version)"
echo "==> 下一步: cd /www/wwwroot/poster.ms1001.com && bash deploy/install.sh"
