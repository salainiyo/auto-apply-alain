import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Inside docker-compose, the backend is reachable via the service name "backend".
// Locally (bare vite dev), it's localhost:8000.
const target = process.env.VITE_PROXY_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/auth': { target, changeOrigin: true },
      '/users': { target, changeOrigin: true },
      '/resumes': { target, changeOrigin: true },
      '/roles': { target, changeOrigin: true },
      '/jobs': { target, changeOrigin: true },
      '/dashboard': { target, changeOrigin: true },
      '/ws': { target, ws: true, changeOrigin: true },
    },
  },
})
