import type { CapacitorConfig } from '@capacitor/cli'

// 改成你的公网域名（Cloudflare Tunnel 分配，如 https://ale.example.com）。
// 局域网调试可临时写 http://192.168.x.x:8001（需后端临时监听局域网）。
// 末尾不要带路径，App 会自动落到 /m 入口。
const SERVER_URL = 'https://ale.example.com'

const config: CapacitorConfig = {
  appId: 'com.ale.workbench',   // 反向域名，需唯一；发布到应用商店前请改为你自己的
  appName: 'ALE 实验快录',
  webDir: '../frontend/dist',   // live-URL 模式下仅作占位/回退，实际内容走 SERVER_URL
  server: {
    url: SERVER_URL,                                  // App 直接加载线上 /m 页面，登录态与数据同步完全复用
    cleartext: SERVER_URL.startsWith('http://'),      // 仅局域网 http 调试时允许明文
    androidScheme: 'https',
  },
}

export default config
