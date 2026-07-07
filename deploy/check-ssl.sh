#!/usr/bin/env bash
# 检查 Python 是否能访问 HTTPS（图片 API 必需）
PY="${POSTER_PYTHON:-/usr/local/python311/bin/python3.11}"

echo "==> Python: $($PY --version 2>&1)"
$PY -c "import ssl; print('SSL:', ssl.OPENSSL_VERSION)" || echo "SSL 模块不可用"

echo "==> 测试 urllib https ..."
$PY -c "
import urllib.request, urllib.error
try:
    urllib.request.urlopen('https://api.fenno.ai/v1', timeout=10)
    print('urllib https: OK')
except urllib.error.HTTPError as e:
    print('urllib https: OK (HTTP', e.code, ')')
except Exception as e:
    print('urllib https: FAIL', e)
"

if command -v curl >/dev/null 2>&1; then
  echo "==> curl https ..."
  curl -sI --max-time 10 https://api.fenno.ai/v1 | head -n 3
else
  echo "curl 未安装"
fi
