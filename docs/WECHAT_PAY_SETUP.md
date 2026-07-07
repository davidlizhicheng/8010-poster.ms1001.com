# 微信支付 API v3 接入指南（替代收款码 + 人工审核）

## 现状

当前为 **`qr_screenshot` 模式**：

1. 展示静态收款码（`payment_qr` 图片）
2. 用户转账后上传截图
3. 服务端 `submit_payment_claim` 入库
4. 默认 `PAYMENT_AUTO_APPROVE=1` 自动开通（**不校验是否真的付过款**），或管理员后台人工审核

`config.json` 里 `wechat_pay.enabled` 仅为预留，**尚未接微信官方 API**。

---

## 目标

接入 **微信支付 API v3** 后：

| 现在 | 接入后 |
|------|--------|
| 静态个人/商户收款码 | 官方动态订单，金额与套餐绑定 |
| 上传截图 | 无需截图 |
| 人工审核 / 假自动开通 | 微信 **支付结果通知** 回调，自动调用 `_fulfill_payment_claim` 到账 |
| 对账困难 | 商户平台可对账，`out_trade_no` 关联 `payment_claims.id` |

---

## 选 JSAPI 还是 Native？

你粘贴的是 **JSAPI** 流程。对本站（浏览器打开的 `generate.html`）建议 **两阶段**：

### 阶段 1：Native 扫码（优先，改动最小）

- 用户在 **PC 浏览器** 打开支付弹窗
- 后端调用 [`Native 下单`](https://pay.weixin.qq.com/doc/v3/merchant/4012791870.md) 拿到 `code_url`
- 前端展示动态二维码，用户微信扫一扫付款
- **直接替换** 现有静态收款码，无需公众号 OAuth

### 阶段 2：JSAPI（微信内打开时）

- 用户从 **服务号菜单 / 图文链接** 进入（必须在微信内置浏览器）
- 需完成你文档中的步骤 1–8：服务号、商户号、APPID 绑定、**支付授权目录**
- 后端 [`JSAPI 下单`](https://pay.weixin.qq.com/doc/v3/merchant/4012791870.md) 需用户 `openid`（OAuth 获取）
- 前端调 `WeixinJSBridge.invoke('getBrandWCPayRequest', …)` 拉起支付

**结论**：PC 主流量先做 Native；公众号导流多再做 JSAPI。两者共用同一套 **支付通知回调** 与到账逻辑。

---

## 商户侧准备（对应微信官方流程）

1. **服务号**（JSAPI 必需）+ 完成认证  
2. **商户号** + 开通 JSAPI / Native 产品权限  
3. **商户号与 APPID 绑定**（公众平台确认授权）  
4. **配置 JSAPI 支付授权目录**（如 `https://你的域名/`）  
5. 下载 **商户 API 证书**，记录 **证书序列号**  
6. 在商户平台设置 **APIv3 密钥**（32 位）  
7. 配置 **支付通知 URL**（必须 HTTPS 公网），例如：  
   `https://你的域名/api/payment/wechat/notify`

开发时请将应答头里的 **Request-ID** 写入日志，便于微信侧排查。

---

## 本系统配置项（接入后填写 `data/config.json`）

```json
{
  "wechat_pay": {
    "enabled": true,
    "mch_id": "1234567890",
    "app_id": "wxXXXXXXXXXXXXXXXX",
    "api_v3_key": "32位APIv3密钥",
    "serial_no": "商户API证书序列号",
    "private_key_path": "data/apiclient_key.pem",
    "notify_url": "https://你的域名/api/payment/wechat/notify",
    "trade_type": "native"
  }
}
```

| 字段 | 说明 |
|------|------|
| `mch_id` | 商户号 |
| `app_id` | 公众号 / 小程序 APPID（Native 下单也需要） |
| `api_v3_key` | 解密回调资源、部分验签 |
| `serial_no` | 商户私钥证书序列号 |
| `private_key_path` | `apiclient_key.pem` 路径（勿提交 git） |
| `notify_url` | 支付成功异步通知 |
| `trade_type` | `native`（PC 扫码）或 `jsapi`（微信内） |

---

## 代码改造点（已在架构上预留）

| 模块 | 作用 |
|------|------|
| `poster_platform._fulfill_payment_claim` | 到账发额度（复用，不改业务规则） |
| `payment_claims` 表 | 增加 `wechat_out_trade_no`、`wechat_transaction_id` 字段 |
| `POST /api/payment/wechat/create` | 创建待支付订单 + 调微信下单 |
| `POST /api/payment/wechat/notify` | 验签 + 解密 + 自动 `_fulfill_payment_claim` |
| `GET /api/payment/wechat/status/{id}` | 前端轮询支付结果 |
| `web/auth.js` | `wechat_pay_ready` 时隐藏截图上传，展示动态码并轮询 |

关闭截图模式：设置 `wechat_pay.enabled: true`，并将 `PAYMENT_AUTO_APPROVE=0`（避免截图通道误开通）。

---

## 部署注意

- 通知 URL 必须是 **443 HTTPS**，宝塔/nginx 需把 `/api/payment/wechat/notify` 反代到 `server.py`
- 私钥与 APIv3 密钥 **只放服务器**，不要进前端
- 生产环境建议关闭截图自动开通，仅保留微信回调到账

---

## 下一步

商户号与证书就绪后，在仓库中实现 `wechat_pay_v3.py` 并切换 `payment_mode` 为 `wechat_native` / `wechat_jsapi`。开发可先用微信支付 **沙箱**（若可用）或 0.01 元测试单验证回调。
