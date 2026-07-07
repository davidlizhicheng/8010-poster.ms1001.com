"""WeChat Pay API v3 — Native 下单、查单、回调验签与解密。"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from shutil import which
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography import x509

logger = logging.getLogger("wechat_pay")

WECHAT_API_BASE = "https://api.mch.weixin.qq.com"
_PLATFORM_CERTS: dict[str, bytes] = {}


class WeChatPayError(Exception):
    pass


def build_wechat_config(config: dict[str, Any]) -> dict[str, Any]:
    wechat = dict(config.get("wechat_pay") or {})
    root = Path(__file__).resolve().parent
    key_path = Path(str(wechat.get("private_key_path") or "data/apiclient_key.pem"))
    if not key_path.is_absolute():
        key_path = root / key_path
    return {
        "mch_id": str(wechat.get("mch_id") or "").strip(),
        "app_id": str(wechat.get("app_id") or "").strip(),
        "api_v3_key": str(wechat.get("api_v3_key") or "").strip(),
        "serial_no": str(wechat.get("serial_no") or "").strip(),
        "notify_url": str(wechat.get("notify_url") or "").strip(),
        "private_key_path": str(key_path),
    }


def validate_wechat_config(cfg: dict[str, Any]) -> None:
    missing = [key for key in ("mch_id", "app_id", "api_v3_key", "serial_no", "notify_url") if not cfg.get(key)]
    if missing:
        raise WeChatPayError(f"微信支付配置不完整，缺少：{', '.join(missing)}")
    if not Path(cfg["private_key_path"]).is_file():
        raise WeChatPayError(f"未找到商户私钥文件：{cfg['private_key_path']}")


def _load_private_key(path: str):
    return serialization.load_pem_private_key(Path(path).read_bytes(), password=None, backend=default_backend())


def _sign(private_key, message: str) -> str:
    signature = private_key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def _build_authorization(cfg: dict[str, Any], method: str, url_path: str, body: str) -> tuple[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
    signature = _sign(_load_private_key(cfg["private_key_path"]), message)
    auth = (
        f'WECHATPAY2-SHA256-RSA2048 mchid="{cfg["mch_id"]}",'
        f'nonce_str="{nonce}",signature="{signature}",timestamp="{timestamp}",serial_no="{cfg["serial_no"]}"'
    )
    return auth, nonce


def _decrypt_aes_gcm(api_v3_key: str, associated_data: str, nonce: str, ciphertext_b64: str) -> bytes:
    aesgcm = AESGCM(api_v3_key.encode("utf-8"))
    return aesgcm.decrypt(
        nonce.encode("utf-8"),
        base64.b64decode(ciphertext_b64),
        associated_data.encode("utf-8"),
    )


def _ssl_available() -> bool:
    try:
        import _ssl  # noqa: F401
        return True
    except ImportError:
        return False


def _https_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 30,
) -> tuple[int, bytes, dict[str, str]]:
    headers = headers or {}
    use_curl = url.lower().startswith("https://") and not _ssl_available()
    if not use_curl:
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_headers = {k: v for k, v in resp.headers.items()}
                return int(resp.status or 200), resp.read(), resp_headers
        except urllib.error.HTTPError as exc:
            resp_headers = {k: v for k, v in exc.headers.items()}
            return int(exc.code), exc.read(), resp_headers
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            if "unknown url type" not in reason.lower() and "ssl" not in reason.lower():
                raise WeChatPayError(f"无法连接微信支付: {reason}") from exc
            use_curl = True

    if use_curl:
        curl_bin = which("curl")
        if not curl_bin:
            raise WeChatPayError(
                "当前 Python 无 SSL 模块且系统无 curl，无法调用微信支付。"
                "请执行: yum install -y curl openssl-devel && bash deploy/rebuild-python-ssl.sh"
            )
        cmd = [curl_bin, "-sS", "-X", method, url, "--max-time", str(timeout), "-w", "%{http_code}"]
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        if body is not None:
            cmd.extend(["--data-binary", "@-"])
        proc = subprocess.run(
            cmd,
            input=body,
            capture_output=True,
            timeout=timeout + 30,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip() or "curl 请求失败"
            raise WeChatPayError(f"无法连接微信支付: {err}")
        out = proc.stdout
        if len(out) < 3:
            raise WeChatPayError("微信支付返回为空")
        code = int(out[-3:].decode("ascii", errors="replace") or "0")
        return code, out[:-3], {}

    raise WeChatPayError("无法连接微信支付")


def _request(cfg: dict[str, Any], method: str, url_path: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    body = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    auth, _ = _build_authorization(cfg, method, url_path, body)
    headers = {
        "Authorization": auth,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "poster-generator/1.0",
    }
    url = WECHAT_API_BASE + url_path
    status, raw_bytes, resp_headers = _https_request(
        url,
        method=method,
        headers=headers,
        body=body.encode("utf-8") if body else None,
    )
    raw = raw_bytes.decode("utf-8", errors="replace")
    request_id = resp_headers.get("Request-ID") or resp_headers.get("Request-Id") or ""
    logger.info("WeChat Pay %s %s status=%s Request-ID=%s", method, url_path, status, request_id)
    if status >= 400:
        logger.error("WeChat Pay error %s Request-ID=%s body=%s", status, request_id, raw[:500])
        raise WeChatPayError(f"微信返回 {status}（Request-ID: {request_id}）：{raw[:500]}")
    return (json.loads(raw) if raw else {}), request_id


def refresh_platform_certificates(cfg: dict[str, Any]) -> None:
    data, _ = _request(cfg, "GET", "/v3/certificates", None)
    for item in data.get("data") or []:
        enc = item.get("encrypt_certificate") or {}
        pem = _decrypt_aes_gcm(
            cfg["api_v3_key"],
            str(enc.get("associated_data") or ""),
            str(enc.get("nonce") or ""),
            str(enc.get("ciphertext") or ""),
        )
        _PLATFORM_CERTS[str(item.get("serial_no") or "")] = pem


def _platform_public_key(cfg: dict[str, Any], serial_no: str):
    if serial_no not in _PLATFORM_CERTS:
        refresh_platform_certificates(cfg)
    pem = _PLATFORM_CERTS.get(serial_no)
    if not pem:
        raise WeChatPayError(f"无法获取微信平台证书 serial={serial_no}")
    cert = x509.load_pem_x509_certificate(pem, default_backend())
    return cert.public_key()


def verify_notify_signature(cfg: dict[str, Any], headers: dict[str, str], body: str) -> None:
    timestamp = headers.get("Wechatpay-Timestamp") or headers.get("wechatpay-timestamp") or ""
    nonce = headers.get("Wechatpay-Nonce") or headers.get("wechatpay-nonce") or ""
    signature_b64 = headers.get("Wechatpay-Signature") or headers.get("wechatpay-signature") or ""
    serial = headers.get("Wechatpay-Serial") or headers.get("wechatpay-serial") or ""
    if not all([timestamp, nonce, signature_b64, serial]):
        raise WeChatPayError("回调缺少 Wechatpay 签名头")
    message = f"{timestamp}\n{nonce}\n{body}\n"
    public_key = _platform_public_key(cfg, serial)
    public_key.verify(
        base64.b64decode(signature_b64),
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def decrypt_notify_resource(cfg: dict[str, Any], resource: dict[str, Any]) -> dict[str, Any]:
    plaintext = _decrypt_aes_gcm(
        cfg["api_v3_key"],
        str(resource.get("associated_data") or ""),
        str(resource.get("nonce") or ""),
        str(resource.get("ciphertext") or ""),
    )
    return json.loads(plaintext.decode("utf-8"))


def create_native_order(
    cfg: dict[str, Any],
    *,
    description: str,
    out_trade_no: str,
    amount_fen: int,
) -> tuple[str, str]:
    validate_wechat_config(cfg)
    path = "/v3/pay/transactions/native"
    payload = {
        "appid": cfg["app_id"],
        "mchid": cfg["mch_id"],
        "description": description[:127],
        "out_trade_no": out_trade_no,
        "notify_url": cfg["notify_url"],
        "amount": {"total": amount_fen, "currency": "CNY"},
    }
    data, request_id = _request(cfg, "POST", path, payload)
    code_url = data.get("code_url")
    if not code_url:
        raise WeChatPayError(f"微信未返回 code_url（Request-ID: {request_id}）")
    return str(code_url), request_id


def query_order_by_out_trade_no(cfg: dict[str, Any], out_trade_no: str) -> tuple[dict[str, Any], str]:
    validate_wechat_config(cfg)
    path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={cfg['mch_id']}"
    return _request(cfg, "GET", path, None)


def qr_image_url(code_url: str, size: int = 240) -> str:
    from urllib.parse import quote

    return f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={quote(code_url, safe='')}"
