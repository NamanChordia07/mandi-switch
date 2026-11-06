import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Dev: the Control Room runs on :5173 and proxies Mandi Core (:8700).
// Prod: `npm run build` → ui/dist, served by Mandi Core at http://127.0.0.1:8700/
const core = 'http://127.0.0.1:8700'
const proxied = ['/orders', '/negotiation', '/events', '/director', '/switch', '/ui', '/health']

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(proxied.map((p) => [p, { target: core, changeOrigin: false, ws: p === '/events' }])),
  },
})
