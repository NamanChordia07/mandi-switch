import { create } from 'zustand'
import type { AuditEvent, Comparison, FeedItem, GodView, Health, MandiEvent, OrderView, Outcome, UiConfig } from './types'

export type StageKey = 'request' | 'spec' | 'rooms' | 'quotes' | 'compare' | 'negotiate' | 'approve' | 'po'

export const STAGES: { key: StageKey; label: string; enters: string[] }[] = [
  { key: 'request', label: 'Request', enters: ['REQUEST'] },
  { key: 'spec', label: 'Spec', enters: ['REQUEST'] },
  { key: 'rooms', label: 'Rooms', enters: ['SPEC_CONFIRMED'] },
  { key: 'quotes', label: 'Quotes', enters: ['RFQ_OPEN'] },
  { key: 'compare', label: 'Compare', enters: ['QUOTES_RECEIVED'] },
  { key: 'negotiate', label: 'Negotiate', enters: ['COMPARED', 'NEGOTIATING'] },
  { key: 'approve', label: 'Approve', enters: ['NEGOTIATION_CLOSED', 'AWARDED'] },
  { key: 'po', label: 'PO', enters: ['PO_ISSUED'] },
]

const STATE_STAGE: Record<string, StageKey> = {
  DRAFT: 'spec', SPEC_CONFIRMED: 'rooms', RFQ_OPEN: 'quotes', QUOTES_RECEIVED: 'compare', COMPARED: 'negotiate',
  NEGOTIATING: 'negotiate', NEGOTIATION_CLOSED: 'approve', AWARDED: 'approve', ENDORSED_PURCHASE_HEAD: 'approve',
  ENDORSED_FINANCE: 'approve', PO_ISSUED: 'po', CANCELLED: 'request',
}

export function liveStage(view: OrderView | null): StageKey {
  if (!view?.order) return 'request'
  return STATE_STAGE[view.order.state] ?? 'request'
}

type S = {
  cfg: UiConfig | null
  view: OrderView | null
  comparison: Comparison | null
  audit: { verified: { ok: boolean; checked: number; head?: string }; events: AuditEvent[] } | null
  outcome: Outcome | null
  feed: FeedItem[]
  health: Health | null
  god: GodView | null
  events: MandiEvent[]
  sse: 'connecting' | 'open' | 'lost'
  pinned: StageKey | null
  explain: boolean
  godView: boolean
  director: boolean
  recording: boolean
  theme: 'dark' | 'light'
  injectionOpen: string | null
  set: (p: Partial<S>) => void
}

export const useStore = create<S>((set) => ({
  cfg: null, view: null, comparison: null, audit: null, outcome: null, feed: [], health: null, god: null, events: [],
  sse: 'connecting', pinned: null, explain: false, godView: false, director: false, recording: false,
  theme: 'dark', injectionOpen: null,
  set: (p) => set(p),
}))
