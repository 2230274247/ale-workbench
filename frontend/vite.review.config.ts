import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Standalone review server: deliberately has no /api proxy or production output.
export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5178, strictPort: true },
  build: {
    outDir: '../reports/soft-ui-preview/build',
    emptyOutDir: false,
    rollupOptions: { input: fileURLToPath(new URL('./ui-review.html', import.meta.url)) },
  },
})
