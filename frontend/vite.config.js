import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Proxy WebSocket + HTTP for the backend API
      '/ws': {
        target: 'http://localhost:8000',
        ws: true,        // upgrade to WebSocket
        changeOrigin: true,
      },
      '/scenarios': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/predict': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

