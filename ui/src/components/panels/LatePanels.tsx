import { Check, Clock3, FileCheck2, FileText, Lock, ShieldCheck, X } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { exportUrl, pdfUrl } from '../../lib/api'
import { clock, group, unit } from '../../lib/format'
import { useStore } from '../../lib/store'
import { Coach, Empty, Money, cx } from '../ui'

type NodeState = 'idle' | 'waiting' | 'requested' | 'approved' | 'declined'

export function ApprovalPanel() {
  const { view, audit, feed } = useStore()
  if (!view) return null
  const o = view.order
  const offer = view.offers.find((x) => x.id === o.awarded_offer_id)
  const vendor = view.vendors.find((v) => v.vendor_id === o.awarded_vendor_id)
  const ev = audit?.events ?? []
  const ph = view.approvals.filter((a) => a.kind === 'PURCHASE_HEAD_ENDORSEMENT').at(-1)
  const fin = view.approvals.filter((a) => a.kind === 'FINANCE_RELEASE').at(-1)
  const askedSwitch = (agent: string) => feed.some((f) => f.room_key === 'order' && f.sender_name === agent && /allow|permission|approve/i.test(f.body))
    || ev.some((e) => e.kind === 'SWITCH_APPROVAL_OBSERVED' && (e.data as any)?.agent === agent)
  const phState: NodeState = ph ? (ph.decision === 'APPROVED' ? 'approved' : 'declined') : askedSwitch('purchase-desk') ? 'requested' : o.awarded_vendor_id ? 'waiting' : 'idle'
  const finState: NodeState = fin ? (fin.decision === 'APPROVED' ? 'approved' : 'declined') : phState === 'approved' ? (askedSwitch('po-issuer') ? 'requested' : 'waiting') : 'idle'
  const poState: NodeState = view.po ? 'approved' : ev.some((e) => e.kind === 'PO_REFUSED_BY_RULE' && !(e.data as any)?.caller?.startsWith?.('agents')) ? 'declined' : finState === 'approved' ? 'waiting' : 'idle'
  if (!o.awarded_vendor_id && !ph) {
    return <Empty icon={<Lock size={28} />} title="Approvals start when a deal is struck">
      Above ₹5,00,000 an order needs two people: Meera (purchase head) and Vikram (finance). Each approves in Switch, on an agent only they can instruct.
    </Empty>
  }
  const nodes: { who: string; role: string; agent: string; state: NodeState; at?: string; how: string }[] = [
    { who: 'Meera Joshi', role: 'Purchase Head', agent: 'purchase-desk', state: phState, at: ph?.at, how: 'Allows @purchase-desk to run endorse_order' },
    { who: 'Vikram Shah', role: 'Finance', agent: 'po-issuer', state: finState, at: fin?.at, how: 'Allows @po-issuer to run issue_po' },
    { who: 'Mandi rules', role: 'PO gate (code)', agent: 'mandi core', state: poState, at: view.po?.issued_at, how: 'Re-checks award, endorsements, ledger, vendor, validity' },
  ]
  const progress = nodes.filter((n) => n.state === 'approved').length / nodes.length
  return (
    <div className="flex h-full flex-col p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[13px] text-mute">Provisional award</div>
          <div className="mt-1 text-[24px] font-semibold tracking-tight">{vendor?.legal_name}</div>
          <div className="num mt-1 text-[15px] text-sub">{unit(offer?.unit_price_paise)} × {group(offer?.quantity ?? 0)} = <Money paise={(offer?.unit_price_paise ?? 0) * (offer?.quantity ?? 0)} className="text-marigold" /> <span className="text-mute">excl. GST</span></div>
        </div>
        <div className="rounded-md border border-indigo/40 bg-indigo/[0.07] px-3 py-2 text-[12.5px] text-indigo">
          Tier: <b>{view.tier?.label}</b> — orders above ₹5,00,000 need both approvals
        </div>
      </div>
      <div className="relative mt-10 grid grid-cols-3 gap-6">
        <div className="absolute left-[16%] right-[16%] top-[30px] h-1 rounded-full bg-hair">
          <motion.div className="h-full rounded-full bg-mint" initial={{ width: 0 }} animate={{ width: `${Math.min(1, progress * 1.5) * 100}%` }} transition={{ duration: 0.8 }} />
        </div>
        {nodes.map((n, i) => (
          <div key={n.role} className="relative flex flex-col items-center text-center">
            <motion.div layout className={cx('relative z-10 flex h-[62px] w-[62px] items-center justify-center rounded-full border-2 bg-pane',
              n.state === 'approved' ? 'border-mint text-mint' : n.state === 'declined' ? 'border-vermilion text-vermilion'
                : n.state === 'requested' ? 'border-indigo text-indigo' : n.state === 'waiting' ? 'border-marigold text-marigold' : 'border-hair text-mute')}>
              {n.state === 'approved' ? <Check size={26} /> : n.state === 'declined' ? <X size={26} /> : n.state === 'requested' ? <ShieldCheck size={24} /> : i === 2 ? <FileCheck2 size={22} /> : <Lock size={22} />}
              {n.state === 'requested' && <span className="absolute inset-0 animate-ping rounded-full border-2 border-indigo/60" />}
            </motion.div>
            <div className="mt-3 text-[15px] font-semibold">{n.who}</div>
            <div className="text-[12.5px] text-sub">{n.role}</div>
            <div className="num mt-1 text-[11.5px] text-teal">{n.agent}</div>
            <div className={cx('mt-2 text-[12.5px]', n.state === 'approved' ? 'text-mint' : n.state === 'declined' ? 'text-vermilion' : n.state === 'requested' ? 'text-indigo' : 'text-mute')}>
              {n.state === 'approved' ? `Approved ${clock(n.at)}${i < 2 ? ' · via Switch permission request' : ' · PO issued'}`
                : n.state === 'declined' ? (i < 2 ? 'Declined in Switch' : 'Refused by rule')
                  : n.state === 'requested' ? 'Switch is asking for approval…'
                    : n.state === 'waiting' ? (i < 2 ? `Waiting for ${n.who.split(' ')[0]} to ask the agent` : 'Waiting for finance') : 'Not yet'}
            </div>
            <div className="mt-1 max-w-[220px] text-[11.5px] text-mute">{n.how}</div>
          </div>
        ))}
      </div>
      <div className="mt-auto grid grid-cols-3 gap-3 pt-8 text-[12.5px] leading-relaxed text-sub">
        <p><span className="text-text">Only Meera can approve.</span> purchase-desk takes instructions from Meera alone — not from Mandi's agents, not even from its operator. In Switch, whoever an agent listens to is whoever can approve its actions.</p>
        <p><span className="text-text">One agent can issue POs.</span> po-issuer holds the exclusive Switch role <span className="num text-teal">po-issuer</span>, listens only to Vikram, and its issue_po tool always asks first.</p>
        <p><span className="text-text">Code has the last word.</span> Even after both taps, Mandi Core refuses a PO that doesn't match the ledger, the tier, or a valid, non-disqualified vendor.</p>
      </div>
      <Coach n={7} text="Money needs two humans. Each one approves by tapping Allow on a Switch permission request posted by an agent that only they can instruct." />
    </div>
  )
}

function Counter({ to, prefix = '', decimals = 0 }: { to: number; prefix?: string; decimals?: number }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    const t0 = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / 1100)
      setV(to * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [to])
  return <>{prefix}{decimals ? v.toFixed(decimals) : group(Math.round(v))}</>
}

export function OutcomePanel() {
  const { outcome: o, view } = useStore()
  if (!o?.po || !view) return <Empty icon={<FileText size={28} />} title="No purchase order yet" />
  const mins = Math.floor((o.elapsed_seconds ?? 0) / 60)
  const secs = (o.elapsed_seconds ?? 0) % 60
  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex flex-col p-7">
        <div className="text-[13px] text-mute">{o.order_id} closed</div>
        <h1 className="mt-1 text-[28px] font-semibold tracking-tight">{o.po.id} issued to {o.vendor}</h1>
        <div className="num mt-1 text-[15px] text-sub">{o.unit} × {group(o.quantity ?? 0)} = <span className="text-text">{o.total}</span> excl. GST · lead {o.lead_time_days} days · payment {o.payment_terms_days} days</div>
        <div className="mt-8 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-hair bg-hair">
          <div className="bg-pane p-5">
            <div className="num text-[40px] font-semibold leading-none text-mint"><Counter to={(o.saved_paise ?? 0) / 100} prefix="₹" /></div>
            <div className="mt-2 text-[13px] text-sub">saved ({o.saved_pct}) vs the best valid opening quote</div>
          </div>
          <div className="bg-pane p-5">
            <div className="num text-[40px] font-semibold leading-none text-text">{mins}m {String(secs).padStart(2, '0')}s</div>
            <div className="mt-2 text-[13px] text-sub">request to signed PO · paper process ~{o.paper_process_days} days</div>
          </div>
          <div className="bg-pane p-5">
            <div className="num text-[40px] font-semibold leading-none text-vermilion">{(o.traps_caught ?? 0) + (o.injections_blocked ?? 0)}</div>
            <div className="mt-2 text-[13px] text-sub">{o.traps_caught} traps caught · {o.injections_blocked} attack blocked</div>
          </div>
        </div>
        <ul className="mt-6 space-y-2 text-[13.5px] text-sub">
          <li className="flex gap-2"><Check size={16} className="mt-0.5 text-mint" />Approved by {o.approvals?.map((a) => a.name).join(' and ')} — each in Switch, on an agent only they can instruct</li>
          <li className="flex gap-2"><Check size={16} className="mt-0.5 text-mint" />{o.vendor_decisions?.length ? `Supplier side: ${o.vendor_decisions.map((d) => `${d.name} ${d.decision.toLowerCase()} ${d.unit}`).join(', ')}` : 'Suppliers negotiated within their own limits'}</li>
          <li className="flex gap-2"><Check size={16} className="mt-0.5 text-mint" />Caught: {(o.traps ?? []).map((t) => t.split(': ')[1].replace('_', ' ').toLowerCase()).join(', ')} · prompt injection blocked</li>
          <li className="flex gap-2"><Check size={16} className="mt-0.5 text-mint" />Spec, comparison, negotiation logs, PO and audit log saved as Switch room documents</li>
        </ul>
        <p className="mt-auto text-[18px] font-medium tracking-tight text-text">Agents negotiate. Humans decide. <span className="text-marigold">Switch records who said yes.</span></p>
      </div>
      <div className="flex min-h-0 flex-col border-l border-hair bg-ink p-4">
        <div className="mb-2 flex items-center justify-between text-[12.5px] text-sub">
          <span className="flex items-center gap-1.5"><FileText size={13} /> {o.po.id}.pdf</span>
          <a className="text-marigold hover:underline" href={pdfUrl(o.order_id)} target="_blank" rel="noreferrer">Open PDF</a>
        </div>
        <a href={pdfUrl(o.order_id)} target="_blank" rel="noreferrer" className="min-h-0 flex-1 overflow-hidden rounded border border-hair bg-white">
          <img src={pdfUrl(o.order_id).replace('/po.pdf', '/po.png')} alt={`Purchase order ${o.po.id}, first page`} className="w-full" />
        </a>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-sub" title="MOCK exports: not an SAP or ERP integration. Field names are illustrative and unverified.">
          <span className="rounded border border-hair px-1.5 py-px text-[10px] uppercase tracking-wide text-mute">Mock</span>
          <a className="text-marigold hover:underline" href={exportUrl(o.order_id, 'po-sap-style.json')} target="_blank" rel="noreferrer">SAP-style PO (JSON)</a>
          <a className="text-marigold hover:underline" href={exportUrl(o.order_id, 'po-sap-style.csv')}>CSV</a>
          <a className="text-marigold hover:underline" href={exportUrl(o.order_id, 'comparative-statement.csv')}>Comparative statement (CSV)</a>
        </div>
        <div className="num mt-2 truncate text-[11px] text-mute" title={o.po.sha256}><Clock3 size={11} className="mr-1 inline" />sha256 {o.po.sha256.slice(0, 24)}…</div>
      </div>
      <Coach n={8} text="The PO PDF carries both approvals and the hash of the final audit event. The same record is saved in the Switch order room." />
    </div>
  )
}
