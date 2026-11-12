# 公网访问与手机 App（数据同步方案）

> 2026-11-12 新增。目标：手机在外网也能填写实验，数据与电脑实时一致，并打包成可安装的原生 App。
> 核心结论：**本工作台没有「另一份数据」需要同步**——手机端和电脑端走同一个后端、同一个 MySQL 库。所以「同步」不是另写一套同步机制，而是让手机能安全地连到这台后端。

## 1. 为什么数据天然是同步的

```
手机 App / 手机浏览器 ──HTTPS──▶ 公网入口(Cloudflare Tunnel) ──▶ 本机 FastAPI(127.0.0.1:8001) ──▶ MySQL(127.0.0.1:3307)
电脑浏览器 ─────────────────────────────────────────────────────────▶ 同一个 FastAPI ──▶ 同一个库
```

- 手机填完「保存记录」，数据立刻写入 `ale_workbench`；电脑刷新即见，反之亦然。
- 不存在「手机上存一份、电脑上存一份、再合并」的离线副本。当前架构**实时在线、单一数据源**。
- 如果你要的是「没网也能填、联网后自动合并」，那是另一条路（离线优先），需要本地暂存 + 冲突/版本/不重写历史，工作量远大于本方案；暂不在本次范围。

## 2. 三步落地

### 第 1 步 · 后端公网配置（改 `backend/.env`，两个必改项）

公网走 HTTPS，登录态 Cookie 与刷新 Origin 校验都要跟着改：

| 变量 | 值 | 为什么 |
|---|---|---|
| `ALE_COOKIE_SECURE` | `true` | `ale_refresh` Cookie 加 `Secure`，只走 HTTPS |
| `ALE_ALLOWED_ORIGINS` | `https://你的域名`（逗号分隔可多个） | 登录态刷新/登出时后端按 `Origin` 校验来源；**不填公网域名会被 403 拒绝，导致登录 1 小时后会话无法刷新** |

改完重启后端（`.\启动工作台.cmd`）。其余（数据库、JWT 密钥）**不动**。

> 说明：后端仍只监听 `127.0.0.1`，不做 0.0.0.0 绑定，也不改启动脚本的监听地址校验。公网入口由下面的隧道负责，这是最省事也最安全的方式。

### 第 2 步 · Cloudflare Tunnel 出公网（自动 HTTPS）

Tunnel 在本机装一个 `cloudflared`，主动连到 Cloudflare，把 `https://你的域名` 转发到 `http://127.0.0.1:8001`。无需公网 IP、无需开路由器端口、无需改后端绑定。

**2a. 装 cloudflared**（任选其一）：

```powershell
winget install --id Cloudflare.cloudflared
# 或去 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ 下载 Windows 版
```

**2b. 临时试用（零配置，先跑通再谈域名）**——会得到一个 `trycloudflare.com` 临时网址：

```powershell
cloudflared tunnel --url http://127.0.0.1:8001
```

打开终端打印出的 `https://xxxx.trycloudflare.com/m`，手机即可访问。临时网址每次重启会变，仅供验证。

**2c. 正式域名（给 App 用，网址固定）**：

1. 在 Cloudflare 控制台添加并接管你的域名（免费计划即可），记下域名如 `ale.example.com`。
2. 建隧道并记录隧道 UUID：`cloudflared tunnel login`，然后 `cloudflared tunnel create ale-workbench`。
3. 把域名指向隧道：`cloudflared tunnel route dns ale-workbench ale.example.com`。
4. 用模板 `deploy/cloudflared/config.yml.example` 生成 `deploy/cloudflared/config.yml`，填隧道 UUID、域名、credentials-file 路径。
5. 前台运行：`cloudflared tunnel --config deploy\cloudflared\config.yml run`；验证后可用 `--no-autoupdate` 或注册成 Windows 服务开机自启。

> 隧道不触碰数据库端口 3307，只转发 8001 的 HTTP；数据库仍只在 127.0.0.1 上。

### 第 3 步 · 打包原生 App（Capacitor，后端零改动）

App 壳工程在 `mobile-app/`，本质是「给现有 `/m` 网页套一层可安装的原生壳」，WebView 直接加载你的公网域名。这样登录态 Cookie、`/api/v1` 调用、数据同步全部原样复用，**不改任何后端与前端业务代码**。

在装好 Android Studio（含 Android SDK）的机器上：

```powershell
cd mobile-app
npm install                 # 装 @capacitor/core|cli|android
# 先改 capacitor.config.ts 里的 SERVER_URL 为你的域名
npx cap add android         # 生成 android/ 工程
npx cap sync android        # 同步配置
npx cap open android        # 用 Android Studio 打开，直接 Run 出 APK
# 或命令行出调试包：
cd android && .\gradlew.bat assembleDebug
# 产物在 mobile-app\android\app\build\outputs\apk\debug\app-debug.apk
```

APK 拷到手机侧载安装即可；后续按需加 `@capacitor/camera`（拍实验记录）、`@capacitor/push-notifications` 等原生能力。

> 本机当前无 Android SDK，故 `android/` 与 APK 未在本机生成；详见 `mobile-app/README.md` 的完整步骤与图标说明。

## 3. 安全清单

- [ ] `.env` 中 `ALE_COOKIE_SECURE=true`、`ALE_ALLOWED_ORIGINS=https://域名`（缺一登录刷新会失效）。
- [ ] 后端仍只监听 `127.0.0.1`，未改为 0.0.0.0；数据库端口未暴露。
- [ ] 隧道域名走 HTTPS；不用「明文 IP:端口」直接对公网。
- [ ] 管理员与写权限账户使用强密码（后端 Argon2 哈希 + 登录限流已启用）。
- [ ] 可选：Cloudflare Access 给域名再加一层登录/邮箱白名单，作为第二道门。
- [ ] 提交前 `git status` 确认 `.env` / `.appcreds` / `.setup-code` / `config.yml`（含 credentials 路径，不入库）。

## 4. 已知限制

- **登录限流按 `client.host` 计数**（`security.py` 的 `RateLimiter` 注释明确「不取转发头」）。隧道之后所有请求的 `client.host` 都是 `127.0.0.1`，即多人共用同一个「10 次/分钟」登录桶：一个人连续输错 10 次，会短暂挡住所有人登录 1 分钟。小团队可接受；若要按真实 IP 限流，需另做「信任 X-Forwarded-For」的改造，属安全敏感改动，未在本方案内。
- 本方案**实时在线**，无离线填写能力；断网时手机 App 无法保存（会直接报「无法连接服务」）。
- 手机端 App 与网页共用同一套 Cookie 登录态，退出登录在任一端都会吊销对应会话。

## 5. 涉及文件

- `docs/公网访问与手机App.md`（本文）
- `deploy/cloudflared/config.yml.example`（隧道模板）
- `mobile-app/`（Capacitor 壳工程：`package.json`、`capacitor.config.ts`、`README.md`、`.gitignore`）
- `backend/.env.example`（`ALE_COOKIE_SECURE` / `ALE_ALLOWED_ORIGINS` 说明更新）
- 相关背景：`docs/ale_v2_2/05_mobile_web.md`（移动网页版与升级路径）、`docs/配置与部署.md`
