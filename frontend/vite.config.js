import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Dev-only proxy: the FastAPI backend serves endpoints at the root
      // (no /api prefix). This proxy rewrites /api/* to /* so the frontend
      // can use a consistent /api base URL in development. In production,
      // a reverse proxy (nginx, Cloudflare, etc.) handles this routing.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.js'],
    css: true,
    include: ['src/**/*.{test,spec}.{js,jsx}'],
  },
})