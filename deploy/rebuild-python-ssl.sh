#!/usr/bin/env bash
# 重新编译 Python 3.11 并启用 SSL（修复 No module named '_ssl'）
# 用法: bash deploy/rebuild-python-ssl.sh
# 耗时约 10–20 分钟

set -euo pipefail

PREFIX="${POSTER_PYTHON_PREFIX:-/usr/local/python311}"
PY_VERSION="3.11.9"
SRC_DIR="/usr/src/Python-${PY_VERSION}"
PY_BIN="$PREFIX/bin/python3.11"
TARBALL="/usr/src/Python-${PY_VERSION}.tgz"
MIRROR="https://mirrors.huaweicloud.com/python/${PY_VERSION}/Python-${PY_VERSION}.tgz"

echo "==> 安装编译依赖..."
yum install -y gcc gcc-c++ make curl \
  openssl openssl-devel bzip2-devel libffi-devel zlib-devel \
  readline-devel sqlite-devel xz-devel wget tar

if [[ ! -f "$TARBALL" ]]; then
  echo "==> 下载源码..."
  wget -c "$MIRROR" -O "$TARBALL"
fi

rm -rf "$SRC_DIR"
tar xf "$TARBALL" -C /usr/src

cd "$SRC_DIR"
echo "==> 配置（启用 OpenSSL）..."
./configure \
  --prefix="$PREFIX" \
  --with-ensurepip=install \
  --with-openssl=/usr \
  --enable-loadable-sqlite-extensions

echo "==> 编译安装（请耐心等待）..."
make -j"$(nproc 2>/dev/null || echo 2)"
make altinstall

echo "==> 验证 SSL..."
"$PY_BIN" -c "import ssl; print('SSL OK:', ssl.OPENSSL_VERSION)"

echo "==> 重启 Poster..."
systemctl restart poster
sleep 1
systemctl status poster --no-pager -l | head -n 10
