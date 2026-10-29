import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` proxies /api to the local read-only API (python Frontend_v2/api/meshheal_api.py).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})
