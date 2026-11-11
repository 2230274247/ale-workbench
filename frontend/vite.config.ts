import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({ plugins: [vue()], server: { host: '0.0.0.0', port: 5173, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true } } }, build: { outDir: 'dist', rollupOptions: { output: { manualChunks: { 'element-plus': ['element-plus'], 'vue-core': ['vue', 'vue-router', 'pinia'] } } } } })
