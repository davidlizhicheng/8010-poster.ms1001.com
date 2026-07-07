# Payment Migration Cloud Checklist

Date: 2026-06-26

## Scope

Payment ownership is moving to `ai.ms1001.com` (`unified-auth`) as the central policy source. Poster keeps its current payment fulfillment path for compatibility, but now follows the shared rules:

- Boss account `18665898305` is full-platform VIP and pays `0` automatically.
- Company payment minimum is RMB 200. No company-side RMB 0.01 orders.
- Personal trial can remain RMB 50 via personal QR: 1 generated poster, 5 modifications.
- Same-plan pending orders and repeated screenshot submissions are allowed by policy.
- Poster batch generation allows up to 100 items when balance is enough.

## Cloud Files To Upload

Poster app (`poster.ms1001.com`):

- `poster_platform.py`
- `server.py`
- `web/generate.html`
- `web/generate.js`
- `web/generate.css`
- `data/config.json` or equivalent production config changes for `max_items_per_job=100`, bulk `min_quantity=20`, bulk `min_amount=200`

Unified auth (`ai.ms1001.com`):

- `payment_policy_service.js`
- `server.js`
- `user_service.js`
- `data/users.json` owner account update, or apply the same update through admin tooling
- `package.json` if using the new `check:all` script

## Required Production Environment

Poster:

- `PORT=8010`
- `POSTER_SECURE_COOKIE=1`
- `PAYMENT_AUTO_APPROVE=1` if screenshot payment should continue auto-crediting
- WeChat Pay V3 fields in `data/config.json` or production config: app id, merchant id, serial, API v3 key, private key path, notify URL
- Minimax prompt planning config: `MINIMAX_API_KEY` environment variable or `data/config.json` `minimax_api_key`, plus `minimax_base_url` and `minimax_model`
- Fenno image generation config: `base_url`, `api_key`, and `image_model`
- QR assets for personal RMB 50 and company payments under `web/assets/`

Unified auth:

- `PORT` / `AUTH_PORT` for ai.ms1001.com service
- Strong production `JWT_SECRET` (do not use the default warning value)
- `AUTH_COOKIE_SECURE=true`
- `AUTH_COOKIE_DOMAIN=.ms1001.com` if sharing cookies across subdomains
- `CORS_ALLOWED_ORIGINS` including production subdomains, or keep trusted `*.ms1001.com` behavior enabled

## Deployment Verification

1. `node --check server.js user_service.js payment_policy_service.js` in `unified-auth`.
2. `python -m py_compile poster_platform.py server.py` with `PYTHONDONTWRITEBYTECODE=1` if pycache is restricted.
3. Open `https://ai.ms1001.com/api/payment/policy` and confirm company min is `200`, personal trial is `50`.
4. Login as `18665898305` and confirm `/api/payment/policy` returns `isOwner: true` and the owner free message.
5. Open `https://poster.ms1001.com/api/config` and confirm `max_items_per_job: 100`, bulk `min_quantity: 20`, and no public RMB 0.01 plan.
6. Confirm boss-facing responses include `李总您好！（深圳市了不起品牌管理有限公司）`.
7. Create two same-plan pending orders in a row and confirm the second is not blocked.
8. Use `AI规划清单` on the poster batch page; confirm Minimax returns a multi-poster plan, then submit and confirm Fenno generates each image.
9. Submit a batch job with more than 10 and at most 100 rows using enough balance.

## Local Debug (verified 2026-06-27)

Terminal 1 — unified-auth:

```powershell
cd D:\Coding\Personal\01-core-systems\unified-auth
$env:PORT="10080"
$env:POSTER_PLATFORM_URL="http://127.0.0.1:8010"
node server.js
```

Terminal 2 — poster:

```powershell
cd D:\Coding\Personal\01-core-systems\poster-generator
$env:PORT="8010"
$env:AUTH_BASE_URL="http://127.0.0.1:10080"
python server.py
```

Smoke tests:

```powershell
cd D:\Coding\Personal\01-core-systems\poster-generator
$env:POSTER_BASE_URL="http://127.0.0.1:8010"
$env:AUTH_BASE_URL="http://127.0.0.1:10080"
python test_unified_integration.py
python test_batch_feature.py
```

Local URLs:

- 统一登录: http://127.0.0.1:10080/login
- 统一收银台: http://127.0.0.1:10080/billing?platform=poster.ms1001.com&plan=pack_20
- Poster: http://127.0.0.1:8010/generate.html
- 老板账号: `18665898305` / `test123456`

Integration notes:

- Poster `use_unified_auth: true` — 登录/注册跳转 ai.ms1001.com，API 接受 `Authorization: Bearer` 统一 JWT。
- 公司套餐（非 ¥50 个人体验）跳转 `central_billing_url` 统一收银台。
- 微信 notify 可先打到 `ai.ms1001.com/api/payment/wechat/notify`，由 unified-auth 转发到 Poster（`POSTER_PLATFORM_URL`）。
