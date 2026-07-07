# 支付统一到 ai.ms1001.com — 架构说明

## 你的两个问题

### 1. 域名是不是 poster.ms1001.com？

**分用途看：**

| 用途 | 推荐域名 |
|------|----------|
| Poster 产品访问 | `https://poster.ms1001.com` |
| 微信 Native 回调（**当前已接好**） | `https://poster.ms1001.com/api/payment/wechat/notify` |
| 统一登录 / 会员中心 | `https://ai.ms1001.com` |

Poster 部署在 `poster.ms1001.com`（见 `deploy/nginx-poster.ms1001.com.conf`）。  
微信支付 **notify_url 必须与实际上线域名一致**，且在微信商户平台可访问（HTTPS）。

当前 Poster 侧已配置：

- `app_id`: `wx75b3754841c31043`
- `notify_url`: `https://poster.ms1001.com/api/payment/wechat/notify`

上线前请在 **微信商户平台 → 产品中心 → 开发配置** 中确认 Native 支付已开通，且 APPID 已与商户号 `1747467120` 绑定。

---

### 2. 能否把所有支付统一到 ai.ms1001.com？

**可以，而且与 unified-auth 的设计方向一致。**

`unified-auth` 已是 MS1001 矩阵的：

- 统一登录（`/login`）
- JWT 校验（`/api/auth/verify`）
- 平台注册与会员（`platformMemberships` + `/.well-known/ms1001-plans.json`）

`INTEGRATION.md` 已写明：支付成功后应 **webhook 回写统一认证会员** — 这部分尚未实现，Native 支付放在 `ai.ms1001.com` 是自然延伸。

---

## 推荐两阶段路线

### 阶段 A（现在）：Poster 独立收款 — 已就绪

```
用户 @ poster.ms1001.com 购买
    → Poster 后端 Native 下单
    → 微信 notify → poster.ms1001.com/.../notify
    → Poster 本地 credit_buckets 到账
```

**优点**：改动最小，可先验证商户号、证书、APPID。  
**缺点**：每个子平台各接一套支付，对账分散。

### 阶段 B（目标）：统一支付中心 @ ai.ms1001.com

```
任意子平台（poster / humanvoice / agent …）
    → 跳转或 iframe：ai.ms1001.com/billing?platform=poster.ms1001.com&plan=single_50
    → 统一 Native 下单（notify 只配一条 URL）
    → ai.ms1001.com/api/payment/wechat/notify
    → 更新 unified-auth 用户 platformMemberships
    → 回调各子平台 webhook 发本地额度
         POST poster.ms1001.com/api/internal/grant-credits（内网 + 签名）
```

**优点**：

- 微信商户后台 **只需一个 notify_url**
- 用户 **一个 MS1001 账号、一处付费**，`account.html` 看全部套餐
- 与 `platforms.json` 里各平台 `billingUrl` 可逐步改为指向 `ai.ms1001.com`

**需要在 unified-auth 新增**（约 1–2 周工作量）：

| 模块 | 说明 |
|------|------|
| `payment_service.js` | 复用 Poster 的 `wechat_pay_v3` 逻辑（或 Node 版） |
| `POST /api/payment/wechat/native/create` | 带 `platformKey` + `planId` |
| `POST /api/payment/wechat/notify` | 验签 + 写订单 + 更新会员 |
| `POST /api/internal/platform/grant` | 通知子平台发额度（HMAC 密钥） |
| `web/billing.html` | 统一收银台（可被各站 `billingUrl` 引用） |

Poster 侧改造：

- `auth.js` 在 `wechat_pay_ready` 时改为打开 `https://ai.ms1001.com/billing?...`（或保留本地直至阶段 B 上线）
- 提供 `POST /api/internal/grant-credits` 接收中心 webhook
- 可选：逐步废弃 Poster 独立注册，只保留 `AUTH_BASE_URL=ai.ms1001.com` 校验 JWT（长期与 INTEGRATION.md 对齐）

---

## 与「要不要公众号」的关系

- Native 支付 **必须有 APPID**（你已有 `wx75b3754841c31043`）
- **不必**用户关注公众号才能付款；PC 扫一扫即可
- 若 APPID 来自 **小程序**，同样可绑定商户号做 Native
- `ai.ms1001.com` 上的 **微信登录 OAuth** 与 **微信 Native 支付** 是两套配置，可共用同一 AppID，也可分开

---

## 微信平台还需做什么

无论阶段 A 还是 B，商户侧都要：

1. ✅ 商户号 `1747467120`
2. ✅ APIv3 密钥、商户证书
3. ☐ APPID `wx75b3754841c31043` 与商户号 **授权绑定**（公众平台/开放平台确认）
4. ☐ Native 支付产品 **已开通**
5. ☐ 支付通知 URL 填 **实际 notify 域名**（阶段 A 填 poster；阶段 B 改 ai）
6. ☐ 上线 HTTPS（宝塔证书）

---

## 子平台 billingUrl 迁移示例

`unified-auth/data/platforms.json` 中 Poster 当前：

```json
"billingUrl": "https://poster.ms1001.com/"
```

阶段 B 可改为：

```json
"billingUrl": "https://ai.ms1001.com/billing?platform=poster.ms1001.com"
```

各站前端「购买」按钮统一跳转该地址即可，**无需每个站各自维护微信支付证书**（证书只放 ai 服务器）。

---

## 建议你现在怎么做

1. **先走阶段 A**：在 `poster.ms1001.com` 跑通一笔真实支付（notify + 轮询），确认额度到账。  
2. **并行规划阶段 B**：在 unified-auth 立项「统一收银台」，把 `wechat_pay_v3` 与订单表迁到 `ai.ms1001.com`。  
3. **不要**在多个子域各配一条微信 notify_url，除非短期来不及做中心。

---

## 相关文档

- Poster Native 操作：[WECHAT_PAY_OPERATIONS.md](./WECHAT_PAY_OPERATIONS.md)
- 统一认证接入：[../unified-auth/INTEGRATION.md](../unified-auth/INTEGRATION.md)
- 平台会员体系：[../unified-auth/PLATFORM_MEMBERSHIP.md](../unified-auth/PLATFORM_MEMBERSHIP.md)
