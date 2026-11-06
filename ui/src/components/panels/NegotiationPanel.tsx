import { BadgeCheck, Ban, Eye, EyeOff, Handshake, Lock, ShieldX } from 'lucide-react'
import { motion } from 'motion/react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { loadGodView } from '../../lib/api'
import { unit } from '../../lib/format'
import { useStore } from '../../lib/store'
import type { OrderView } from '../../lib/types'
import { FeedRow } from '../Feed'
import { Chip, Coach, Empty, cx } from '../ui'

type Pt = { i: number; vendor?: number; buyer?: number; label: string }

function series(view: OrderView, vid: string) {
  const quote = view.quotes.find((q) => q.vendor_id === vid)
  const offers = view.offers.filter((o) => o.vendor_id === vid)
  const pts: Pt[] = []
  let v: number | undefined = quote?.comparable ? quote.landed_unit_paise ?? undefined : undefined
  let b: number | undefined
  if (v) pts.push({ i: 0, vendor: v / 100, label: 'Quote' })
  for (const o of offers) {
    if (o.verification === 'BLOCKED' || !o.unit_price_paise) continue
    if (o.side === 'VENDOR') v = o.unit_price_paise
    else if (o.conditions === 'ask') b = o.unit_price_paise
    else continue
    pts.push({ i: pts.length, vendor: v ? v / 100 : undefined, buyer: b ? b / 100 : undefined, label: o.side === 'VENDOR' ? 'Offer' : 'Ask' })
  }
  return { pts, offers, quote }
}

function VendorColumn({ vid }: { vid: string }) {
  const { view, feed, godView, god, comparison } = useStore()
  if (!view) return null
  const v = view.vendors.find((x) => x.vendor_id === vid)!
  const { pts, offers } = series(view, vid)
  const vendorPrices = offers.filter((o) => o.side === 'VENDOR' && o.unit_price_paise).map((o) => o.unit_price_paise!)
  const quote = view.quotes.find((q) => q.vendor_id === vid)
  const tape = [...(quote?.comparable && quote.landed_unit_paise ? [quote.landed_unit_paise] : []), ...vendorPrices]
  const accepted = offers.find((o) => o.side === 'VENDOR' && o.status === 'ACCEPTED')
  const awarded = view.order.awarded_vendor_id === vid
  const lev = offers.flatMap((o) => (o.verification === 'APPROVED' ? o.claims.filter((c) => c.verified) : []))
  const blocked = offers.filter((o) => o.verification === 'BLOCKED')
  const vapprovals = view.approvals.filter((a) => a.kind === 'VENDOR_BELOW_LINE' && a.vendor_id === vid)
  const owner = { deccan: 'Asha', ganesh: 'Sanjay', apex: 'Karan' }[vid] ?? 'owner'
  const g = god?.[vid]
  const competing = lev.length ? lev[lev.length - 1].unit_price_paise / 100 : undefined
  const msgs = feed.filter((f) => f.room_key === vid && f.event === 'message').slice(-4)
  const status = awarded ? <Chip tone="mint"><Handshake size={11} /> Awarded · {unit(accepted?.unit_price_paise)}</Chip>
    : accepted ? <Chip tone="teal"><Handshake size={11} /> Agreed in principle · {unit(accepted.unit_price_paise)}</Chip>
      : v.status === 'CLOSED' ? <Chip tone="mute">Walked away</Chip>
        : offers.some((o) => o.side === 'VENDOR' && o.status === 'REJECTED') || !['NEGOTIATING', 'COMPARED'].includes(view.order.state)
          ? <Chip tone="mute">Not awarded{vendorPrices.length ? ` · final ${unit(vendorPrices[vendorPrices.length - 1])}` : ''}</Chip>
          : <Chip tone="marigold">Negotiating · round {Math.max(1, offers.filter((o) => o.side === 'BUYER' && o.verification === 'APPROVED').length)}</Chip>
  const ys = pts.flatMap((p) => [p.vendor, p.buyer]).filter((x): x is number => !!x)
  const lo = Math.floor(Math.min(...ys, competing ?? 99, godView && g ? g.floor_paise / 100 : 99) - 0.6)
  const hi = Math.ceil(Math.max(...ys, 36) + 0.4)
  return (
    <div className={cx('flex min-h-0 flex-col rounded-lg border bg-raise', awarded ? 'border-mint/40' : 'border-indigo/30')}>
      <div className="flex items-center justify-between gap-2 border-b border-hair px-4 py-2.5">
        <div className="flex items-center gap-2 text-[14px] font-semibold"><Lock size={14} className="text-indigo" />{v.legal_name}</div>
        {status}
      </div>
      <div className="flex items-baseline gap-2 overflow-hidden px-4 pt-3">
        {tape.length === 0 && <span className="text-[13px] text-mute">{vid === 'ganesh' ? 'Asked for a 20,000-piece price…' : 'Waiting for the first move…'}</span>}
        {tape.map((p, i) => (
          <motion.span key={i} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
            className={cx('num whitespace-nowrap', i === tape.length - 1 ? 'text-[26px] font-semibold text-marigold' : 'text-[15px] text-mute line-through decoration-hair-2')}>
            {unit(p)}{i < tape.length - 1 && <span className="mx-1.5 text-mute no-underline">›</span>}
          </motion.span>
        ))}
      </div>
      <div className="h-[190px] px-1 pt-1">
        {pts.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={pts} margin={{ top: 10, right: 64, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--color-hair)" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: 'var(--color-mute)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis domain={[lo, hi]} tick={{ fill: 'var(--color-mute)', fontSize: 11, fontFamily: 'Geist Mono' }} axisLine={false} tickLine={false} width={44} tickFormatter={(x) => `₹${x}`} />
              <Tooltip contentStyle={{ background: 'var(--color-ink)', border: '1px solid var(--color-hair-2)', borderRadius: 8, fontSize: 12 }}
                formatter={(val, name) => [`₹${Number(val).toFixed(2)}`, name === 'vendor' ? `${v.legal_name} offer` : 'Mandi ask']} />
              {competing && <ReferenceLine y={competing} stroke="var(--color-indigo)" strokeDasharray="4 4" label={{ value: `verified rival ₹${competing.toFixed(2)}`, position: 'right', fill: 'var(--color-indigo)', fontSize: 10.5 }} />}
              {godView && g && <ReferenceLine y={g.approval_line_paise / 100} stroke="var(--color-vermilion)" strokeDasharray="2 3" label={{ value: `secret line ₹${(g.approval_line_paise / 100).toFixed(2)}`, position: 'right', fill: 'var(--color-vermilion)', fontSize: 10.5 }} />}
              <Line type="stepAfter" dataKey="vendor" stroke="var(--color-marigold)" strokeWidth={2.4} dot={{ r: 3.5, fill: 'var(--color-marigold)' }} connectNulls isAnimationActive />
              <Line type="stepAfter" dataKey="buyer" stroke="var(--color-teal)" strokeWidth={2.4} dot={{ r: 3.5, fill: 'var(--color-teal)' }} connectNulls isAnimationActive />
            </LineChart>
          </ResponsiveContainer>
        ) : <div className="flex h-full items-center justify-center text-[12.5px] text-mute">The price ladder fills in as offers arrive.</div>}
      </div>
      <div className="flex flex-wrap gap-1.5 px-4 pb-2">
        {lev.slice(-1).map((c, i) => <Chip key={i} tone="indigo"><BadgeCheck size={11} /> Leverage verified: rival {unit(c.unit_price_paise)} (cited anonymously)</Chip>)}
        {vapprovals.map((a) => (
          <Chip key={a.id} tone={a.decision === 'DECLINED' ? 'vermilion' : 'mint'}><Lock size={11} /> Asked {owner} for {unit(a.unit_price_paise)} — {a.decision === 'DECLINED' ? 'declined' : 'approved'}</Chip>
        ))}
        {blocked.map((b) => <Chip key={b.id} tone="vermilion"><Ban size={11} /> Blocked before reaching the room{b.redteam ? ' (red-team)' : ''}: claimed {unit(b.unit_price_paise)}</Chip>)}
      </div>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto border-t border-hair p-1.5">
        {msgs.map((f) => <FeedRow key={f.id} f={f} compact />)}
        {!msgs.length && <p className="p-3 text-[12px] text-mute">Room messages appear here.</p>}
      </div>
      {comparison && null}
    </div>
  )
}

export function NegotiationPanel() {
  const { view, godView, set, god } = useStore()
  if (!view) return null
  const apex = view.vendors.find((v) => v.vendor_id === 'apex')
  if (!['NEGOTIATING', 'NEGOTIATION_CLOSED', 'AWARDED', 'ENDORSED_PURCHASE_HEAD', 'ENDORSED_FINANCE', 'PO_ISSUED', 'COMPARED'].includes(view.order.state)) {
    return <Empty title="Negotiation starts after the comparison" />
  }
  return (
    <div className="flex h-full min-h-0 flex-col p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[13px] text-sub">
          Two sealed rooms, negotiating in parallel. <span className="text-marigold">Supplier offers</span> fall, <span className="text-teal">Mandi's asks</span> rise. Every number is decided by code and checked before it reaches Switch.
        </p>
        <button onClick={() => { if (!god) loadGodView(); set({ godView: !godView }) }}
          className={cx('flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px]', godView ? 'border-vermilion/50 text-vermilion' : 'border-hair text-sub hover:text-text')}
          title="Shows each supplier's secret approval line — visible here only for the demo. No buyer agent ever sees it.">
          {godView ? <EyeOff size={13} /> : <Eye size={13} />} God view{godView ? ' (demo only)' : ''}
        </button>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-3">
        <VendorColumn vid="deccan" />
        <VendorColumn vid="ganesh" />
      </div>
      {apex?.status === 'DISQUALIFIED' && (
        <div className="mt-3 flex items-center gap-2 rounded-md border border-vermilion/30 bg-vermilion/[0.05] px-3 py-2 text-[12.5px] text-sub">
          <ShieldX size={14} className="text-vermilion" /> Apex Precision's room is closed — disqualified for a prompt injection before negotiation began.
        </div>
      )}
      <Coach n={6} text="Negotiators may cite a rival's price only if Mandi verified it — and never say who. When Deccan's agent is asked to go below its limit, it must ask its own human, Asha, in its sealed room." className="!top-14" />
    </div>
  )
}
