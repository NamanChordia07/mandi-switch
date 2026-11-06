import { useStore } from './store'
import type { MandiEvent } from './types'

const token = () => useStore.getState().cfg?.ui_token ?? ''
const dtoken = () => useStore.getState().cfg?.director_token ?? ''

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Authorization: `Bearer ${token()}` } })
  if (!r.ok) throw new Error(`${path} → ${r.status}`)
  return r.json()
}

export async function director(action: string, body: Record<string, unknown> = {}) {
  const r = await fetch(`/director/${action}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${dtoken()}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return r.json()
}

export const pdfUrl = (orderId: string) => `/orders/${orderId}/po.pdf?token=${encodeURIComponent(token())}`
export const quotePageUrl = (orderId: string, quoteId: string, page: number) =>
  `/orders/${orderId}/quotes/${quoteId}/page/${page}.png?token=${encodeURIComponent(token())}`

let timer: number | undefined
export function scheduleRefresh(delay = 120) {
  window.clearTimeout(timer)
  timer = window.setTimeout(refreshAll, delay)
}

export async function refreshAll() {
  const st = useStore.getState()
  try {
    const health = await get<any>('/health')
    st.set({ health })
    const view = await get<any>('/orders/current')
    if (!view.order) {
      st.set({ view: null, comparison: null, outcome: null, audit: null })
      const feed = await get<any>('/switch/feed?limit=300')
      st.set({ feed: feed.items })
      return
    }
    const oid = view.order.id
    const [comparison, audit, outcome, feed] = await Promise.all([
      get<any>(`/orders/${oid}/comparison`),
      get<any>(`/orders/${oid}/audit`),
      get<any>(`/orders/${oid}/outcome`),
      get<any>('/switch/feed?limit=400'),
    ])
    st.set({ view, comparison, audit, outcome, feed: feed.items })
  } catch (e) {
    console.warn('[mandi] refresh failed', e)
  }
}

export async function loadGodView() {
  try {
    const r = await director('god-view')
    if (r && !r.detail) useStore.getState().set({ god: r })
  } catch {
    /* director-only */
  }
}

export function connectEvents() {
  const st = useStore.getState()
  let es: EventSource | null = null
  let last = 0
  const open = () => {
    st.set({ sse: 'connecting' })
    es = new EventSource(`/events/stream?token=${encodeURIComponent(token())}&since=${last}`)
    es.addEventListener('open', () => useStore.getState().set({ sse: 'open' }))
    es.addEventListener('mandi', (m) => {
      const evt = JSON.parse((m as MessageEvent).data) as MandiEvent
      last = Math.max(last, evt.id)
      const s = useStore.getState()
      if (evt.kind === 'switch.event') {
        const item = evt.data.item
        if (!s.feed.some((f) => f.id === item.id)) s.set({ feed: [...s.feed.slice(-500), item] })
      }
      if (evt.kind === 'switch.status' && s.health) {
        s.set({ health: { ...s.health, switch: { ...s.health.switch, switch_live: evt.data.live } } })
      }
      if (evt.kind === 'demo.reset') s.set({ feed: [], pinned: null })
      s.set({ events: [...s.events.slice(-200), evt] })
      if (evt.kind !== 'switch.event') scheduleRefresh()
    })
    es.addEventListener('error', () => {
      useStore.getState().set({ sse: 'lost' })
      es?.close()
      window.setTimeout(open, 2000)
    })
  }
  open()
  window.setInterval(() => scheduleRefresh(0), 15000)
}
