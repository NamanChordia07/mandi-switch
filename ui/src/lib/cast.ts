/** The cast: who owns which agent, who may talk to it. Mirrors config/agents.yaml + bootstrap policies. */
export type CastAgent = { name: string; label: string; owner: string; company: string; talk: string; kind: 'custom' | 'claude-code' }

export const AGENTS: Record<string, CastAgent> = {
  'mandi-intake': { name: 'mandi-intake', label: 'Intake', owner: 'Mandi Exchange', company: 'Sahyadri Motors', talk: 'Rohan, Meera, Vikram, Mandi agents', kind: 'custom' },
  'mandi-quotes': { name: 'mandi-quotes', label: 'Quote Analyst', owner: 'Mandi Exchange', company: 'Sahyadri Motors', talk: 'buyer team, Mandi agents', kind: 'custom' },
  'mandi-auditor': { name: 'mandi-auditor', label: 'Auditor', owner: 'Mandi Exchange', company: 'Neutral record-keeper', talk: 'owner only — never speaks unprompted', kind: 'custom' },
  'purchase-desk': { name: 'purchase-desk', label: 'Purchase Desk', owner: 'Meera (gate)', company: 'Sahyadri Motors', talk: 'Meera only — so only Meera can approve', kind: 'claude-code' },
  'po-issuer': { name: 'po-issuer', label: 'PO Issuer', owner: 'Vikram (gate)', company: 'Sahyadri Motors', talk: 'Vikram only — exclusive role po-issuer', kind: 'claude-code' },
  'mandi-negotiator-deccan': { name: 'mandi-negotiator-deccan', label: 'Negotiator', owner: 'Mandi Exchange', company: 'Sahyadri Motors', talk: 'deccan-sales, Asha', kind: 'custom' },
  'mandi-negotiator-ganesh': { name: 'mandi-negotiator-ganesh', label: 'Negotiator', owner: 'Mandi Exchange', company: 'Sahyadri Motors', talk: 'ganesh-sales, Sanjay', kind: 'custom' },
  'mandi-negotiator-apex': { name: 'mandi-negotiator-apex', label: 'Negotiator', owner: 'Mandi Exchange', company: 'Sahyadri Motors', talk: 'apex-sales, Karan', kind: 'custom' },
  'deccan-sales': { name: 'deccan-sales', label: 'Deccan Sales', owner: 'Asha Rao', company: 'Deccan Bolt Works', talk: 'Asha, Mandi negotiator', kind: 'custom' },
  'ganesh-sales': { name: 'ganesh-sales', label: 'Ganesh Sales', owner: 'Sanjay Patil', company: 'Shree Ganesh Fasteners', talk: 'Sanjay, Mandi negotiator', kind: 'custom' },
  'apex-sales': { name: 'apex-sales', label: 'Apex Sales', owner: 'Karan Mehta', company: 'Apex Precision', talk: 'Karan, Mandi negotiator', kind: 'custom' },
}

export const ROOMS: { key: string; title: string; channel: string; sealed: boolean; people: string[]; agents: string[] }[] = [
  { key: 'order', title: 'Order room', channel: 'sm-pr-0147 · order', sealed: false, people: ['Rohan', 'Meera', 'Vikram'], agents: ['mandi-intake', 'mandi-quotes', 'purchase-desk', 'po-issuer', 'mandi-auditor'] },
  { key: 'deccan', title: 'Deccan Bolt Works', channel: 'sealed · private', sealed: true, people: ['Asha'], agents: ['mandi-negotiator-deccan', 'deccan-sales', 'mandi-auditor'] },
  { key: 'ganesh', title: 'Shree Ganesh Fasteners', channel: 'sealed · private', sealed: true, people: ['Sanjay'], agents: ['mandi-negotiator-ganesh', 'ganesh-sales', 'mandi-auditor'] },
  { key: 'apex', title: 'Apex Precision', channel: 'sealed · private', sealed: true, people: ['Karan'], agents: ['mandi-negotiator-apex', 'apex-sales', 'mandi-auditor'] },
]

export const VENDOR_SHORT: Record<string, string> = { deccan: 'Deccan', ganesh: 'Shree Ganesh', apex: 'Apex', konkan: 'Konkan' }
