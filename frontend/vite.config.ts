import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  // The optional comparison editor uses top-level await in its font shaping runtime.
  optimizeDeps: {
    entries: ['index.html', 'onlyoffice-integration.html'],
    esbuildOptions: { target: 'esnext' },
    exclude: ['@docx-editor.dev/fonts', '@docx-editor.dev/fonts-cjk/browser'],
  },
  server: {
    port: 9174,
    strictPort: true,
    watch: { ignored: ['**/*.md'] },
    proxy: { '/api': process.env.RIXIN_API_TARGET || 'http://127.0.0.1:8010' },
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    // 开发验证页面只由开发服务器提供，不加入生产构建。
    rollupOptions: {
      input: { main: fileURLToPath(new URL('./index.html', import.meta.url)) },
    },
  },
})
