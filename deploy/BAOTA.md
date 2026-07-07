# 宝塔服务器部署指南

将 **AI 平面设计系统** 部署到宝塔（BT Panel）的完整步骤。

## 架构说明

```
用户浏览器 → 宝塔 Nginx（HTTPS）→ 127.0.0.1:8010 → python server.py
```

- 静态页面、`/api/*`、生成图片 `/outputs/*` 均由 `server.py` 统一提供
- 数据与配置在 `data/`，生成图在 `outputs/`

## 一、服务器准备

1. 宝塔安装 **Nginx** 即可
2. **不必**依赖「Python 项目管理器」安装 Python（该插件常因云端解析失败报错）
3. 使用系统自带 `python3`（3.8+ 即可，推荐 3.10+）

SSH 检查：

```bash
python3 --version
which python3
```

若版本 ≥ 3.8，直接用于部署。若没有或版本过低，用系统包管理器安装（见下方「Python 安装失败」）。

## 二、上传代码

任选一种方式：

**方式 A：Git**

```bash
cd /www/wwwroot
git clone <你的仓库地址> poster.ms1001.com
cd poster.ms1001.com
```

**方式 B：本地上传**

将项目打包上传到 `/www/wwwroot/poster.ms1001.com`

## 三、配置

```bash
cd /www/wwwroot/poster.ms1001.com
cp data/config.example.json data/config.json
cp deploy/env.example .env
```

编辑 `data/config.json`：

- `api_key`：图片 API 密钥
- `base_url`：接口地址
- `payment_qr`：收款码路径（图片在 `web/assets/`）

编辑 `.env`：

```bash
HOST=127.0.0.1
PORT=8010
POSTER_SECURE_COOKIE=1
ADMIN_PHONE=你的手机号
ADMIN_PASSWORD=强密码
```

## 四、安装并启动后端

```bash
chmod +x deploy/install.sh
bash deploy/install.sh
```

`install.sh` 会：

1. 选择 Python 3.8+（优先 `/usr/local/python311/bin/python3.11`）
2. **`pip install -r requirements.txt`**（含 `cryptography`，微信支付必需）
3. 创建 `data/`、`outputs/` 目录并安装 systemd / `poster` 命令

验证：

```bash
curl -I http://127.0.0.1:8010/
# 应返回 HTTP/1.0 200
python3 -c "import cryptography; print('cryptography OK')"
poster s
```

### 不用 systemd 时（Supervisor）

宝塔 → **软件商店** → 安装 **Supervisor** → 添加守护进程，配置参考 `deploy/supervisor.conf`（注意改路径）。

## 五、宝塔添加网站（poster.ms1001.com 示例）

与 `translate.ms1001.com`（Node 5177 + 静态分离）不同，本项目 **前后端一体**，全部由 Python `8010` 提供。

1. **网站** → **添加站点**
   - 域名：`poster.ms1001.com`
   - 根目录：`/www/wwwroot/poster.ms1001.com`
   - PHP：不选 / 纯静态

2. **SSL** → 申请证书 → **强制 HTTPS**

3. **设置** → **配置文件**：
   - 使用 `deploy/nginx-poster.ms1001.com.conf`（**仅 HTTP，无 SSL 路径**）
   - **先保存成功**，再在面板 **SSL → 申请证书 → 强制 HTTPS**（宝塔自动写入证书路径）
   - ⚠️ 证书未申请前不要写 `listen 443` 和 `ssl_certificate`，否则会报 `fullchain.pem` 不存在

对照 translate 站点差异：

| 项目 | translate.ms1001.com | poster.ms1001.com |
|------|----------------------|-------------------|
| 前端 | `try_files` 静态 SPA | 反代 `8010` |
| API | `127.0.0.1:5177` | `127.0.0.1:8010` |
| 生成超时 | 120s | **300s**（`/api/`） |

4. 保存后 **重载 Nginx**，`.env` 中设置 `POSTER_SECURE_COOKIE=1`

## 六、访问与管理员

- 前台：`https://你的域名/`
- 管理：`https://你的域名/admin.html`
- 默认管理员：`.env` 中的 `ADMIN_PHONE` / `ADMIN_PASSWORD`（首次无管理员时自动创建）

## 七、目录权限

```bash
chown -R www:www /www/wwwroot/poster/data /www/wwwroot/poster/outputs
chmod -R 755 /www/wwwroot/poster/web
```

## 八、更新部署

```bash
cd /www/wwwroot/poster.ms1001.com
git pull   # 或上传新文件
bash deploy/install.sh   # 会同步 pip 依赖（含 cryptography）
poster r   # 重启并检查
```

## 九、常见问题

| 问题 | 处理 |
|------|------|
| 宝塔安装 Python 3.11 报 ParseError / 未找到版本 | **忽略面板 Python 插件**，用系统 `python3` + `deploy/install.sh`（见下节） |
| 502 Bad Gateway | `poster s` 看是否崩溃；端口 8010 是否监听 |
| 登录后立刻退出 | HTTPS 站点需设 `POSTER_SECURE_COOKIE=1` |
| 生成超时 | Nginx `proxy_read_timeout` 调至 300s 以上 |
| 支付截图失败 | `client_max_body_size` 至少 10m |
| 支付弹窗 `No module named 'cryptography'` | SSH 执行 `bash deploy/install.sh` 或 `pip install -r requirements.txt`，然后 `poster r` |
| 支付弹窗 `unknown url type: https` | Python 未编译 SSL；先 `yum install -y curl`，再 `poster r`（已自动用 curl 调微信）；根治：`bash deploy/rebuild-python-ssl.sh` |
| 页面无样式、纯文字蓝链 | 删除 Nginx 里 `location ~ .*\.(js|css)` 段，css/js 须反代到 8010 |

### CentOS 7 自带 Python 3.6 无法运行

报错 `SyntaxError: future feature annotations is not defined` 时，系统 Python 太旧。

**CentOS 7 不要用最新 Miniconda**（会报 `GLIBC >=2.28`），请用**源码编译**：

```bash
cd /www/wwwroot/poster.ms1001.com
# 若没有 install-python311-centos7.sh，见下方「无脚本时一键命令」
chmod +x deploy/install-python311-centos7.sh deploy/install.sh
bash deploy/install-python311-centos7.sh   # 约 5–15 分钟
bash deploy/install.sh
curl -I http://127.0.0.1:8010/
```

`install.sh` 会优先使用 `/usr/local/python311/bin/python3.11`。

### 一键重启（不用记 systemctl）

```bash
# 推荐：全局命令（install.sh 已安装到 /usr/local/bin/poster）
poster r          # 重启并检查（替代 systemctl restart poster + status）
poster s          # 仅看状态
poster l          # 最近日志
poster t          # 自检

# 或在项目目录：
cd /www/wwwroot/poster.ms1001.com
bash deploy/posterctl.sh r
```

环境变量 `PAYMENT_AUTO_APPROVE=1` 在 `.env` 中配置（`deploy/env.example` 默认已开启自动开通支付）。

**宝塔面板：** 软件商店 → **终端**，直接输入 `poster r` 即可。

也可配置别名：

```bash
echo 'alias pr="poster r"' >> ~/.bashrc
echo 'alias ps="poster s"' >> ~/.bashrc
source ~/.bashrc
```

## 十、安全建议

- 勿将 `data/config.json` 提交到公开仓库
- 修改默认管理员密码
- 仅通过 Nginx 对外暴露，后端监听 `127.0.0.1`
- 定期备份 `data/poster.db` 与 `outputs/`
