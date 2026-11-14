import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // En desarrollo, Vite reenvía /api y el WebSocket a la FastAPI de Jesus.
  const target = env.API_PROXY_TARGET || 'http://localhost:8000'
  const wsPath = env.VITE_WS_PATH || '/ws'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      proxy: {
        '/api': { target, changeOrigin: true },
        [wsPath]: { target, ws: true, changeOrigin: true },
      },
    },
  }
})
