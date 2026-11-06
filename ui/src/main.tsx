import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { connectEvents, refreshAll } from './lib/api'
import { useStore } from './lib/store'

async function boot() {
  for (;;) {
    try {
      const r = await fetch('/ui/config')
      if (r.ok) {
        useStore.getState().set({ cfg: await r.json() })
        break
      }
    } catch {
      /* Core not up yet */
    }
    await new Promise((res) => setTimeout(res, 1500))
  }
  await refreshAll()
  connectEvents()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
boot()
