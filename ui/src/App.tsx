import { useEffect, useState } from 'react'
import { AuditTicker, ThreeLocks } from './components/Bottom'
import { SimBanner, Stepper, TopBar } from './components/Chrome'
import { DirectorDrawer } from './components/Director'
import { Feed } from './components/Feed'
import { RequestPanel, RoomsPanel, SpecPanel } from './components/panels/EarlyPanels'
import { ApprovalPanel, OutcomePanel } from './components/panels/LatePanels'
import { NegotiationPanel } from './components/panels/NegotiationPanel'
import { InjectionModal, QuotesPanel } from './components/panels/QuotesPanel'
import { RoomsMap } from './components/RoomsMap'
import { director, loadGodView } from './lib/api'
import { STAGES, liveStage, useStore, type StageKey } from './lib/store'
import { How } from './pages/How'

const TITLES: Record<StageKey, string> = {
  request: 'Request', spec: 'Spec — from chat message to precise requirement', rooms: 'Sealed rooms — one per supplier',
  quotes: 'Quotes — read, normalised, checked', compare: 'Comparison — landed cost for our quantity',
  negotiate: 'Negotiation — parallel, sealed, verified', approve: 'Approvals — two humans, in Switch', po: 'Purchase order',
}

function Hero({ stage }: { stage: StageKey }) {
  switch (stage) {
    case 'request': return <RequestPanel />
    case 'spec': return <SpecPanel />
    case 'rooms': return <RoomsPanel />
    case 'quotes':
    case 'compare': return <QuotesPanel />
    case 'negotiate': return <NegotiationPanel />
    case 'approve': return <ApprovalPanel />
    case 'po': return <OutcomePanel />
  }
}

export default function App() {
  const { view, pinned, theme, recording, set, cfg } = useStore()
  const [route, setRoute] = useState(location.hash)
  useEffect(() => {
    const f = () => setRoute(location.hash)
    window.addEventListener('hashchange', f)
    return () => window.removeEventListener('hashchange', f)
  }, [])
  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])
  useEffect(() => { document.documentElement.dataset.recording = String(recording) }, [recording])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.metaKey || e.ctrlKey || e.altKey) return
      const s = useStore.getState()
      const k = e.key.toLowerCase()
      if (k === 'e') s.set({ explain: !s.explain })
      else if (k === 'g') { if (!s.god) loadGodView(); s.set({ godView: !s.godView }) }
      else if (k === 'd') s.set({ director: !s.director })
      else if (k === 's') director('start')
      else if (k === 'r') { if (confirm('Reset Mandi Core for a new run? Switch rooms are kept.')) director('reset') }
      else if (k === 'f') { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen() }
      else if (k === 'escape') s.set({ pinned: null, recording: false, injectionOpen: null, explain: false })
      else if (/^[1-8]$/.test(k)) s.set({ pinned: STAGES[Number(k) - 1].key })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!cfg) return <div className="flex h-full items-center justify-center text-sub">Connecting to Mandi Core…</div>
  if (route.startsWith('#/how')) return <How />
  const live = liveStage(view)
  const stage = pinned ?? live
  return (
    <div className="flex h-full min-w-[1280px] flex-col">
      <TopBar />
      <SimBanner />
      <Stepper />
      <main className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)_400px] gap-px bg-hair">
        <RoomsMap />
        <section className="relative flex min-h-0 flex-col bg-pane">
          <header className="flex h-10 shrink-0 items-center justify-between border-b border-hair px-5">
            <h2 className="text-[13px] font-semibold">{TITLES[stage]}</h2>
            {pinned && pinned !== live && (
              <button onClick={() => set({ pinned: null })} className="text-[12px] text-marigold hover:underline">Back to live stage</button>
            )}
          </header>
          <div className="min-h-0 flex-1 overflow-hidden"><Hero stage={stage} /></div>
        </section>
        <Feed />
      </main>
      <footer className="grid h-[150px] shrink-0 grid-cols-[minmax(0,1fr)_320px] gap-px border-t border-hair bg-hair">
        <AuditTicker />
        <ThreeLocks />
      </footer>
      <DirectorDrawer />
      <InjectionModal />
    </div>
  )
}
