import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` proxies /api/v1 to the fleet API (python -m dashboard.server, port 8780) and the rest of /api to the
// local read-only demo API (python Frontend_v3/api/meshheal_api.py, port 8765).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api/v1': 'http://127.0.0.1:8780', '/api': 'http://127.0.0.1:8765' } },
})
