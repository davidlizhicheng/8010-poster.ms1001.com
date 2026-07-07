# Poster

批量 AI 海报生成工作台。目标是把 GPT-Image-2 / OpenAI 兼容图片接口单独拆成可收费的“海报工厂”：批量导入主题、选择商业模板、估算成本与售价、生成队列、历史画廊、下载成品。

## 上线说明

- 公开站点：`index.html` — 注册、套餐购买（扫码截图）、海报生成、企业开票
- 管理通知：`/admin.html` — 查看注册/支付/开票事件（需管理员登录）
- 套餐：免费 1 张 · ¥50/张(5次优化) · ¥300/20张 · ¥1000/100张 · 批量 ¥10/张
- 收款码：在 `data/config.json` 的 `payment_qr` 中配置图片路径
- 管理员：环境变量 `ADMIN_PHONE` / `ADMIN_PASSWORD`（默认 13800000000 / admin123456）
- 注册通知：写入 `data/admin_alerts.log`，可设 `ADMIN_NOTIFY_URL`  webhook
- 微信官方支付：见 [docs/WECHAT_PAY_OPERATIONS.md](docs/WECHAT_PAY_OPERATIONS.md)（Native 扫码 + 自动到账）

## 数据保留

生产更新时必须保留整个 `data/` 目录：

- `data/poster.db`：用户、会话、额度、生成任务、支付记录、开票和管理员事件。
- `data/config.json`：本地 API、收款码与运行配置。
- `data/payment-screenshots/`：每一条付款截图，管理员后台可逐条查看。
- `data/reference-images/`：用户上传的参考图，可通过 `/api/reference-images/<job_id>/<filename>` 直接访问。

更新代码前建议备份 `data/`；不要用新包覆盖或删除该目录。

## 宝塔 / Linux 部署

详见 **[deploy/BAOTA.md](deploy/BAOTA.md)**。

快速步骤：

```bash
cd /www/wwwroot/poster
cp data/config.example.json data/config.json   # 填写 api_key
cp deploy/env.example .env                     # 修改管理员密码
bash deploy/install.sh                         # systemd 启动
# 宝塔：添加站点 → SSL → Nginx 反代到 127.0.0.1:8010（见 deploy/baota-nginx.conf）
```

## 运行（本地开发）

```powershell
cd D:\Coding\Poster
python server.py
```

打开：

```text
http://127.0.0.1:8010/
```

## 配置

在网页右侧“接口配置”里填写：

- Base URL：例如 `https://api.fenno.ai`
- API Key：你的中转站密钥
- Image Model：例如 `gpt-image-2`

配置会保存在本机 `data/config.json`，不会提交到代码里。

## 核心功能

- 批量主题输入：一行一个海报主题。
- 商业模板：错题卡、课程招生、社群裂变、节日促销、品牌活动。
- 成本估算：按单张成本、建议售价和毛利率估算。
- 真接口生成：无参考图时按 OpenAI 兼容 `/v1/images/generations` 调用；上传参考图或修改已有海报时按 `/v1/images/edits` 调用，并用 multipart 上传真实图片文件。
- 历史记录：每次生成都会进入历史画廊，支持打开和下载。
- 无 Key 预检：未配置 Key 时可保存任务与提示词，方便先设计批次。
