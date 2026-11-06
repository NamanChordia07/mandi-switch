export type Trap = {
  code: 'HIDDEN_MOQ' | 'EXPIRED' | 'LATE_DELIVERY' | 'FREIGHT_EXCLUDED' | 'MISSING_FIELD' | 'INJECTION'
  severity: 'BLOCKER' | 'WARNING'
  message: string
  evidence?: { page?: number | null; snippet?: string }
}

export type Vendor = {
  vendor_id: string
  legal_name: string
  status: 'ACTIVE' | 'DISQUALIFIED' | 'NO_ROOM' | 'CLOSED'
  room_id?: string | null
  agent_name?: string | null
  negotiator?: string | null
  status_reason?: string
}

export type Quote = {
  id: string
  vendor_id: string
  received_via: string
  received_at: string
  parsed: boolean
  quote_ref: string
  unit_price_paise: number | null
  basis: string | null
  freight_paise_per_unit: number | null
  moq: number | null
  lead_time_days: number | null
  valid_until: string | null
  payment_terms_days: number | null
  extraction_confidence: number
  extraction_method: string
  evidence: Record<string, { page?: number; snippet?: string }>
  injection_verdict: 'CLEAN' | 'SUSPICIOUS' | 'INJECTION'
  injection_confidence: number
  injection_spans: string[]
  injection_detail: { hidden?: { page: number; kind: string; reason: string; text: string }[]; llm?: unknown; heuristic_top_score?: number }
  traps: Trap[]
  comparable: boolean
  landed_unit_paise: number | null
  landed_total_paise: number | null
}

export type Claim = { unit_price_paise: number; verified: boolean; reason: string }

export type Offer = {
  id: string
  vendor_id: string
  round: number
  side: 'BUYER' | 'VENDOR'
  unit_price_paise: number | null
  basis: string
  quantity: number
  conditions: string
  status: string
  is_final: boolean
  claims: Claim[]
  verification: 'APPROVED' | 'BLOCKED' | 'N/A'
  message_text: string
  created_at: string
  switch_message_id?: string | null
  redteam: boolean
}

export type Approval = {
  id: string
  kind: 'PURCHASE_HEAD_ENDORSEMENT' | 'FINANCE_RELEASE' | 'VENDOR_BELOW_LINE'
  decision: 'APPROVED' | 'DECLINED'
  decided_by_user: string
  mechanism: string
  agent_name: string
  vendor_id?: string | null
  unit_price_paise?: number | null
  at: string
}

export type Order = {
  id: string
  base_id: string
  buyer: string
  plant: string
  requester_user: string
  created_at: string
  raw_request: string
  spec: {
    part_name?: string; part_spec?: string; drawing_ref?: string; quantity?: number; uom?: string
    needed_by?: string; delivery_terms?: string; assumptions?: string[]; confirmed_by?: string | null
  }
  spec_confirmed: boolean
  state: string
  tier: string | null
  awarded_vendor_id: string | null
  awarded_offer_id: string | null
  po_id: string | null
  rooms: Record<string, string>
  stage_times: Record<string, string>
}

export type PO = { id: string; vendor_id: string; unit_price_paise: number; quantity: number; total_paise: number; pdf_path: string; sha256: string; audit_hash: string; issued_at: string }

export type OrderView = {
  order: Order
  vendors: Vendor[]
  quotes: Quote[]
  offers: Offer[]
  approvals: Approval[]
  po: PO | null
  tier: { name: string; label: string; approvers: string[] } | null
}

export type CompareRow = {
  quote_id: string; vendor_id: string; vendor: string; vendor_status: string; rank: number | null
  unit_paise: number | null; basis: string | null; freight_paise: number | null; landed_unit_paise: number | null
  landed_total_paise: number | null; moq: number | null; lead_time_days: number | null; valid_until: string | null
  payment_terms_days: number | null; comparable: boolean; injection_verdict: string; traps: Trap[]; flags: string[]
}

export type Comparison = {
  quantity: number; rows: CompareRow[]; best_vendor_id: string | null; best_landed_unit_paise: number | null
  best_landed_total_paise: number | null; traps_caught: number; injections_blocked: number; recommendation: string
}

export type AuditEvent = { seq: number; at: string; order_id: string; actor: string; kind: string; summary: string; data: Record<string, unknown>; hash: string }

export type Outcome = {
  order_id: string; state: string; po: PO | null; vendor?: string; unit?: string; quantity?: number; total?: string
  total_paise?: number; baseline_total_paise?: number; saved_paise?: number; saved?: string; saved_pct?: string
  lead_time_days?: number; payment_terms_days?: number; traps?: string[]; traps_caught?: number
  injections_blocked?: number; leverage_blocked?: number; approvals?: { name: string; kind: string; mechanism: string }[]
  vendor_decisions?: { name: string; decision: string; unit: string | null }[]; elapsed_seconds?: number | null
  paper_process_days?: string
}

export type FeedItem = {
  id: number; at: string; event: string; room_id: string; room_key: string; sequence?: number; message_id?: string
  thread_id?: string | null; sender: string; sender_name: string; sender_kind: 'human' | 'agent' | 'switch' | 'unknown'
  body: string; addressed: boolean; data: { attachments?: { filename: string; mimetype: string }[]; display_name?: string; simulated?: boolean }
}

export type MandiEvent = { id: number; kind: string; order_id: string | null; at: string; data: Record<string, any> }

export type Health = { ok: boolean; current_order: string | null; scenario_date: string; switch: { switch_live: boolean; switch_live_at: string | null; auditor: any } }

export type UiConfig = {
  ui_token: string
  director_token: string
  scenario_date: string
  scenario: {
    order_id: string; short_id: string; buyer: string; plant: string; requester: string; quantity: number
    part: { name: string; spec: string; drawing_ref: string }
    raw_request_message: string
    vendors: Record<string, { legal_name: string; short: string; contact_persona: string | null; agent: string | null; negotiator: string | null; has_room: boolean }>
    personas: Record<string, { name: string; title: string; company: string; approver_role?: string }>
  }
}

export type GodView = Record<string, { approval_line_paise: number; floor_paise: number; schedule_paise: number[] }>
