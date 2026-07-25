import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// FarmVault frontend build config.
// Dev server proxies API and WebSocket traffic to the FastAPI backend
// so the frontend can call relative paths like /api/... and /ws/...
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true
  }
})