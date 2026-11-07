import { AlertTriangle, Eye, FileWarning, ShieldAlert, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { quotePageUrl } from '../../lib/api'
import { group, inr, shortDate, unit } from '../../lib/format'
import { useStore } from '../../lib/store'
import type { Quote, Trap } from '../../lib/types'
import { Chip, Coach, Empty, Money, cx } from '../ui'

const TRAP_LABEL: Record<string, string> = {
  HIDDEN_MOQ: 'Hidden MOQ', EXPIRED: 'Expired', LATE_DELIVERY: 'Late', FREIGHT_EXCLUDED: 'Freight extra',
  MISSING_FIELD: 'Missing field', INJECTION: 'Prompt injection',
}

function TrapBadge({ t }: { t: Trap }) {
  const [open, setOpen] = useState(false)
  const tone = t.code === 'INJECTION' || t.severity === 'BLOCKER' ? 'vermilion' : 'amber'
  return (
    <span className="relative" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} tabIndex={0}>
      <Chip tone={tone} className="pulse-once cursor-help">{t.code === 'INJECTION' ? <ShieldAlert size={11} /> : <AlertTriangle size={11} />}{TRAP_LABEL[t.code]}</Chip>
      {open && (
        <span className="absolute right-0 top-6 z-40 w-[320px] rounded-lg border border-hair-2 bg-ink p-3 text-left text-[12.5px] leading-snug text-text shadow-2xl">
          {t.message}
          {t.evidence?.snippet && (
            <span className="mt-2 block rounded border border-hair bg-raise p-2 text-[11.5px] text-sub">
              {t.evidence.page ? <span className="text-mute">Page {t.evidence.page}: </span> : null}“{t.evidence.snippet}”
            </span>
          )}
        </span>
      )}
    </span>
  )
}

export function QuotesPanel() {
  const { comparison: cmp, view, set } = useStore()
  if (!view) return null
  const quotes = view.quotes
  if (!cmp || !cmp.rows.length) {
    return <Empty icon={<FileWarning size={28} />} title="Quotes are on their way">
      Supplier agents attach their quotation PDFs in their sealed rooms. Mandi's Quote Analyst reads each one — including fine print and hidden text.
    </Empty>
  }
  const injected = quotes.find((q) => q.injection_verdict === 'INJECTION')
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto p-5">
        <table className="w-full border-separate border-spacing-0 text-[13px]">
          <thead>
            <tr className="text-left text-[11.5px] text-mute">
              {['Rank', 'Supplier', 'Quoted', 'Basis', 'Landed /pc', 'MOQ', 'Lead', 'Valid until', 'Payment', 'Landed total', 'Findings'].map((h) => (
                <th key={h} className={cx('border-b border-hair px-2.5 pb-2 font-medium', ['Quoted', 'Landed /pc', 'MOQ', 'Landed total'].includes(h) && 'text-right')}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cmp.rows.map((r, i) => {
              const bad = r.injection_verdict === 'INJECTION'
              const moq = r.traps.find((t) => t.code === 'HIDDEN_MOQ')
              return [
                <motion.tr key={r.quote_id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.1 }}
                  className={cx(bad && 'bg-vermilion/[0.06]', r.rank === 1 && 'bg-mint/[0.05]')}>
                  <td className="border-b border-hair px-2.5 py-3">
                    {r.rank ? <span className={cx('num flex h-6 w-6 items-center justify-center rounded-full text-[12px]', r.rank === 1 ? 'bg-mint/20 text-mint' : 'bg-raise text-sub')}>{r.rank}</span> : <span className="text-mute">–</span>}
                  </td>
                  <td className="border-b border-hair px-2.5 py-3 font-medium text-text">{r.vendor}</td>
                  <td className="num border-b border-hair px-2.5 py-3 text-right text-sub">{bad ? '—' : unit(r.unit_paise)}</td>
                  <td className="border-b border-hair px-2.5 py-3 text-sub">{r.basis === 'EX_WORKS' ? 'Ex-works' : r.basis ? 'Delivered' : '—'}</td>
                  <td className="num border-b border-hair px-2.5 py-3 text-right text-text">{bad ? '—' : <>{unit(r.landed_unit_paise)}{!r.comparable && <span className="text-amber">*</span>}</>}</td>
                  <td className={cx('num border-b border-hair px-2.5 py-3 text-right', moq ? 'text-amber' : 'text-sub')}>{r.moq ? group(r.moq) : '—'}</td>
                  <td className="num border-b border-hair px-2.5 py-3 text-sub">{r.lead_time_days ? `${r.lead_time_days} d` : '—'}</td>
                  <td className={cx('num border-b border-hair px-2.5 py-3', r.traps.some((t) => t.code === 'EXPIRED') ? 'text-vermilion' : 'text-sub')}>{shortDate(r.valid_until)}</td>
                  <td className="num border-b border-hair px-2.5 py-3 text-sub">{r.payment_terms_days ? `${r.payment_terms_days} d` : '—'}</td>
                  <td className="border-b border-hair px-2.5 py-3 text-right"><Money paise={r.landed_total_paise} className={r.rank === 1 ? 'text-mint' : 'text-text'} /></td>
                  <td className="border-b border-hair px-2.5 py-3">
                    <div className="flex flex-wrap justify-end gap-1">
                      {r.traps.filter((t) => t.code !== 'MISSING_FIELD').map((t) => <TrapBadge key={t.code} t={t} />)}
                      {!r.traps.length && <Chip tone="mint">Clean</Chip>}
                      {bad && <button onClick={() => set({ injectionOpen: r.quote_id })} className="inline-flex items-center gap-1 rounded-full border border-vermilion/50 px-2 py-0.5 text-[11.5px] text-vermilion hover:bg-vermilion/10"><Eye size={11} /> Show what was hidden</button>}
                    </div>
                  </td>
                </motion.tr>,
                moq && (
                  <tr key={r.quote_id + '-why'}>
                    <td />
                    <td colSpan={10} className="border-b border-hair px-2.5 pb-3 pt-0 text-[12.5px] text-amber">
                      Why not the cheapest? {unit(r.unit_paise)} only applies if you buy {group(r.moq ?? 0)}. That's {group((r.moq ?? 0) - cmp.quantity)} extra bolts ({inr((r.unit_paise ?? 0) * ((r.moq ?? 0) - cmp.quantity), { decimals: false })} of stock nobody asked for) — and freight is extra. Mandi asks for a {group(cmp.quantity)}-piece price instead.
                    </td>
                  </tr>
                ),
              ]
            })}
          </tbody>
        </table>
        <p className="mt-2 text-[11.5px] text-mute">* not comparable at our quantity as quoted. Landed = quoted price + freight, for {group(cmp.quantity)} pcs, excluding GST.</p>
        <div className="mt-5 max-w-3xl rounded-lg border border-hair bg-raise p-4 text-[13.5px] leading-relaxed text-sub">
          <span className="font-medium text-text">Recommendation. </span>{cmp.recommendation}
        </div>
      </div>
      {injected && <InjectionStrip q={injected} />}
      <Coach n={4} text="Every quote is normalised to landed cost for our quantity. Traps are flagged with the exact page and words they came from — hover a badge." />
    </div>
  )
}

function InjectionStrip({ q }: { q: Quote }) {
  const set = useStore((s) => s.set)
  return (
    <button onClick={() => set({ injectionOpen: q.id })}
      className="flex shrink-0 items-center gap-3 border-t border-vermilion/40 bg-vermilion/[0.07] px-5 py-3 text-left">
      <ShieldAlert size={20} className="text-vermilion" />
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold text-vermilion">Prompt injection blocked in Apex Precision's quote — supplier disqualified</div>
        <div className="truncate text-[12.5px] text-sub">“{q.injection_spans[0]}”</div>
      </div>
      <span className="text-[12px] text-vermilion">Reveal →</span>
    </button>
  )
}

export function InjectionModal() {
  const { injectionOpen, view, set } = useStore()
  const q = view?.quotes.find((x) => x.id === injectionOpen)
  return (
    <AnimatePresence>
      {q && view && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-8" onClick={() => set({ injectionOpen: null })}>
          <motion.div initial={{ scale: 0.97, y: 10 }} animate={{ scale: 1, y: 0 }} onClick={(e) => e.stopPropagation()}
            className="grid max-h-[90vh] w-[1320px] max-w-full grid-cols-[1.15fr_1fr] overflow-hidden rounded-xl border border-vermilion/50 bg-pane shadow-2xl">
            <div className="min-h-0 space-y-3 overflow-auto bg-ink p-3">
              {[1, 2].map((p) => (
                <img key={p} src={quotePageUrl(view.order.id, q.id, p)} alt={`Apex quote page ${p} with hidden text outlined`} className="w-full rounded border border-hair" />
              ))}
            </div>
            <div className="flex min-h-0 flex-col overflow-auto p-6">
              <div className="flex items-start justify-between gap-3">
                <h3 className="flex items-center gap-2 text-[18px] font-semibold text-vermilion"><ShieldAlert size={20} /> Prompt injection blocked</h3>
                <button onClick={() => set({ injectionOpen: null })} aria-label="Close" className="text-sub hover:text-text"><X size={18} /></button>
              </div>
              <p className="mt-2 text-[13.5px] leading-relaxed text-sub">
                Apex Precision's PDF hid instructions for our AI agents — once as invisible 1-point white text in the footer, and again in a pale “Notes for automated processing” box.
              </p>
              <pre className="num mt-4 whitespace-pre-wrap rounded-lg border border-vermilion/40 bg-vermilion/[0.07] p-3 text-[12.5px] leading-relaxed text-text">{q.injection_spans[0]}</pre>
              <dl className="mt-4 grid grid-cols-[120px_1fr] gap-y-2 text-[13px]">
                <dt className="text-mute">Verdict</dt><dd className="font-medium text-vermilion">INJECTION · {(q.injection_confidence * 100).toFixed(0)}% confidence</dd>
                <dt className="text-mute">How found</dt><dd className="text-sub">Hidden-text scan ({q.injection_detail.hidden?.[0]?.reason ?? 'hidden text'}), pattern rules, and an LLM classifier reading it as data</dd>
                <dt className="text-mute">What it wanted</dt><dd className="text-sub">Skip the comparison, get the PO issuer to release a PO, and keep humans in the dark</dd>
                <dt className="text-mute">What happened</dt><dd className="text-sub">Apex disqualified, its sealed room closed, Meera alerted in the order room</dd>
              </dl>
              <div className="mt-5 rounded-lg border border-hair bg-raise p-4">
                <div className="mb-2 text-[13px] font-medium text-text">Even if an agent had been fooled, three locks still hold</div>
                <ol className="space-y-1.5 text-[12.5px] text-sub">
                  <li><span className="text-teal">1 · Switch identity</span> — the PO issuer takes instructions from Vikram only.</li>
                  <li><span className="text-indigo">2 · Permission request</span> — issuing a PO pauses in Claude Code; Switch relays the request and only Vikram may answer it.</li>
                  <li><span className="text-marigold">3 · Mandi rules</span> — code refuses a PO for a disqualified vendor, without endorsement, or off-ledger.</li>
                </ol>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
