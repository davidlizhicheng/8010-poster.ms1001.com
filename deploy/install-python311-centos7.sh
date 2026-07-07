#!/usr/bin/env bash
# CentOS 7 / 老 glibc 系统：源码编译 Python 3.11（不依赖 Miniconda）
# 用法: bash deploy/install-python311-centos7.sh
# 耗时约 5–15 分钟，安装到 /usr/local/python311

set -euo pipefail

PREFIX="${POSTER_PYTHON_PREFIX:-/usr/local/python311}"
PY_VERSION="3.11.9"
SRC_DIR="/usr/src/Python-${PY_VERSION}"
PY_BIN="$PREFIX/bin/python3.11"

if [[ -x "$PY_BIN" ]]; then
  if "$PY_BIN" -c "import _ssl" 2>/dev/null; then
    echo "==> 已存在且 SSL 正常: $($PY_BIN --version)"
    exit 0
  fi
  echo "==> 检测到 Python 无 SSL，将重新编译。也可直接运行: bash deploy/rebuild-python-ssl.sh"
fi

echo "==> 安装编译依赖..."
yum install -y gcc gcc-c++ make \
  openssl-devel bzip2-devel libffi-devel zlib-devel \
  readline-devel sqlite-devel xz-devel wget tar

echo "==> 下载 Python ${PY_VERSION} 源码..."
mkdir -p /usr/src
cd /usr/src
if [[ ! -f "Python-${PY_VERSION}.tgz" ]]; then
  wget -q "https://www.python.org/ftp/python/${PY_VERSION}/Python-${PY_VERSION}.tgz"
fi
rm -rf "$SRC_DIR"
tar xf "Python-${PY_VERSION}.tgz"

echo "==> 编译安装到 $PREFIX（请耐心等待）..."
cd "$SRC_DIR"
./configure \
  --prefix="$PREFIX" \
  --with-ensurepip=install \
  --with-openssl=/usr \
  --enable-loadable-sqlite-extensions
make -j"$(nproc 2>/dev/null || echo 2)"
make altinstall

echo "==> 验证 SSL..."
"$PY_BIN" -c "import ssl; print(ssl.OPENSSL_VERSION)"
echo "==> 下一步: cd /www/wwwroot/poster.ms1001.com && bash deploy/install.sh"
