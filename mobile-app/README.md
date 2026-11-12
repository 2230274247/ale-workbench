# ALE 实验快录 · 原生 App 壳

基于 [Capacitor](https://capacitorjs.com/) 的 Android App 壳：WebView 加载线上 `/m` 页面（`capacitor.config.ts` 里的 `SERVER_URL`），**后端与前端业务代码零改动**。登录态 Cookie、`/api/v1` 调用、数据同步全部复用现有实现。

## 前置条件

- Node.js 20+
- Android Studio（含 Android SDK；命令行出包另需 JDK 17）
- 已按 `docs/公网访问与手机App.md` 完成公网隧道与 `.env` 配置，且手机能通过浏览器打开 `https://你的域名/m`

## 打包步骤

```powershell
cd mobile-app
npm install

# 1) 编辑 capacitor.config.ts，把 SERVER_URL 改成你的域名

# 2) 生成 Android 工程
npx cap add android

# 3) 同步（webDir=../frontend/dist 需存在；live-URL 模式下内容仅作回退，不影响实际加载）
npm run build:web        # 或手动 mkdir ../frontend/dist
npx cap sync android

# 4) 打开 Android Studio 直接 Run，或命令行出调试包
npx cap open android
# 或：
cd android && .\gradlew.bat assembleDebug
```

产物：`android/app/build/outputs/apk/debug/app-debug.apk`，拷到手机侧载安装。

> 正式发布需自行签名（`assembleRelease` + keystore），并到应用商店按流程上架；侧载调试包即可满足日常使用。

## 图标

先放一张 `assets/icon.png`（1024×1024）与 `assets/splash.png`，再生成全套原生图标：

```powershell
npx @capacitor/assets generate --android
```

也可复用现有 `frontend/public/icons/` 里的 PNG 作为起点。

## 常见问题

- **App 打开一片空白/连不上**：确认 `SERVER_URL` 是公网可访问的 https 域名，且手机与隧道网络可达。
- **登录后过一会儿掉线**：确认后端 `.env` 已设 `ALE_COOKIE_SECURE=true` 且 `ALE_ALLOWED_ORIGINS` 含该域名（否则刷新会话被 403 拒绝）。
- **局域网 http 调试连不上**：后端需临时监听局域网、且 `SERVER_URL` 用 `http://` 时 `cleartext` 已自动开启。
