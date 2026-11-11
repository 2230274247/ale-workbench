# 移动端网页版（/m）与 App / 小程序升级路径

2026-11-11 新增。电脑版（`/quick` 等）完全不变；移动版是并列入口，共用同一后端 API、同一登录态、同一数据库。

## 1. 现在有什么

| 路由 | 内容 |
|---|---|
| `/m/quick` | 实验快录：单列卡片表单，A/B/C 三源各一张卡，ΔP 支持单值或 `70–100` 区间，实时推算净减薄/EPC，存草稿/保存记录 |
| `/m/history` | 实验历史：卡片列表 + 关键字筛选 + 加载更多，点卡片直接进入编辑 |
| `/m/dataset` | 导出 XLSX/JSON、批量导入（下载模板/上传原表/预览/确认入库）、数据体检摘要 |
| `/m/me` | 账户信息、数据范围、退出登录、切换电脑版 |
| `/m/login` | 登录页（复用电脑版登录组件，移动端自动单列） |

技术要点：

- 独立代码位于 `frontend/src/mobile/`（`MobileShell.vue` + 4 个视图 + `mobile.css`），样式类全部 `m-` 前缀，不污染桌面版样式。
- 手机端编辑只改动 A/B/C 三步；记录里若存在更多组/步骤（电脑端录入的复杂结构），保存时**原样带回**，不会覆盖。
- 已加 PWA 基础：`manifest.webmanifest`（start_url=`/m/quick`）、图标、`apple-touch-icon`、`viewport-fit=cover`。手机浏览器「添加到主屏幕」后全屏运行，看起来就是 App。
- 未引入 Service Worker：避免缓存旧版本导致「改了代码手机上不生效」。

## 2. 手机怎么访问（当前限制）

后端只监听 `127.0.0.1:8001`，**手机现在还连不上**，需要选一种方式：

| 方式 | 做法 | 适用 |
|---|---|---|
| 局域网访问（推荐日常用） | 启动脚本增加绑定 `0.0.0.0` 的选项，手机连同一 WiFi 访问 `http://<电脑IP>:8001/m` | 实验室内网；需注意局域网内任何人都能打开登录页，靠账户密码保护 |
| USB 调试转发 | `adb reverse tcp:8001 tcp:8001`，手机访问 `http://127.0.0.1:8001` | 安卓 + 数据线，零暴露 |
| 公网部署 | 服务器 + HTTPS 域名（可云服务器或内网穿透） | 升级 App/小程序前必经 |

如需局域网/公网访问，说一声，我改启动脚本加 `-Bind 0.0.0.0` 开关（默认仍只监听本机，不降低现有安全性）。

## 3. 升级为 App

网页版已经是响应式 + PWA，有三档做法：

1. **直接「添加到主屏幕」（0 成本）**：Android Chrome / iOS Safari 均支持，图标、全屏、独立窗口都有。
2. **WebView 套壳 App（1–2 天）**：用 Capacitor（推荐）或 Tauri Mobile 包一层，加载现有 `/m` 页面；可上架侧载或应用商店，能调用摄像头（拍实验记录）、推送等原生能力。后端零改动。
3. **原生/跨端重写（数周）**：uni-app / Flutter / React Native 重写 UI，复用全部 `/api/v1` 接口。只有在需要深度原生功能时才值得。

## 4. 升级为微信小程序

小程序**不能直接复用这套 Vue 代码**（运行时不支持 DOM/BOM），必须重写 UI 层，但后端可以原样复用。前提与工作量：

| 事项 | 说明 |
|---|---|
| 公网 HTTPS 域名 | 微信要求合法域名 + ICP 备案；`127.0.0.1` 或纯 IP 内网不可用 |
| 登录态改造 | 现在靠 Cookie（`credentials:'same-origin'`）；小程序需改为 `Authorization: Bearer` 头（后端已支持 Bearer token，前端请求层要换掉 Cookie 依赖） |
| 微信登录（可选） | `wx.login` 换 openid，与现有账户绑定；也可继续用用户名密码登录 |
| UI 重写 | 推荐 uni-app（Vue 3 语法，与现有代码风格接近，一套代码可同时出 H5 + 小程序 + App）；`/m` 的页面结构与 API 调用逻辑可直接照搬 |
| 估算 | 熟手 1–2 周可上线 MVP（登录 + 快录 + 历史 + 导入导出） |

**建议节奏**：先把局域网访问打开，日常用 PWA（添加到主屏幕）；确实需要在微信里传播或用微信登录时，再做小程序。

## 5. 涉及文件

- `frontend/src/mobile/`：MobileShell.vue、MobileQuickView.vue、MobileHistoryView.vue、MobileDatasetView.vue、MobileMeView.vue、mobile.css
- `frontend/src/router.ts`：`/m` 路由与守卫（未登录跳 `/m/login`）
- `frontend/src/views/LoginView.vue`：登录后按来源跳 `/m/quick` 或 `/`
- `frontend/src/components/AppShell.vue`：页脚「手机版入口」链接（桌面唯一改动）
- `frontend/index.html`：viewport-fit、manifest、apple 图标 meta
- `frontend/public/`：manifest.webmanifest、icons/（SVG + 192/512/180 PNG）
