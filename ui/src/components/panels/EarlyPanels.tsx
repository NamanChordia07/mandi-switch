import { CheckCircle2, FileText, Inbox, Lock, Mail, MessageSquareText, Send, Sparkles } from 'lucide-react'
import { motion } from 'motion/react'
import { director } from '../../lib/api'
import { group, shortDate } from '../../lib/format'
import { useStore } from '../../lib/store'
import { Chip, Coach, cx } from '../ui'

export function RequestPanel() {
  const cfg = useStore((s) => s.cfg)
  const raw = cfg?.scenario.raw_request_message ?? ''
  return (
    <div className="flex h-full items-center justify-center p-10">
      <div className="max-w-xl">
        <div className="mb-5 flex items-center gap-2 text-sub"><Inbox size={18} /> Waiting for a purchase request</div>
        <h1 className="text-[34px] font-semibold leading-[1.15] tracking-tight text-text">
          An engineer asks for bolts in chat.<br />Mandi takes it from there.
        </h1>
        <p className="mt-4 text-[15px] leading-relaxed text-sub">
          Rohan posts his request in the order room in Mattermost, addressed to <span className="num text-teal">@mandi-intake</span>.
          From that message to a signed purchase order, every step happens in Switch rooms — and every rupee waits for a person's approval.
        </p>
        <div className="mt-6 rounded-lg border border-hair bg-raise p-4">
          <div className="mb-2 flex items-center gap-2 text-[12px] text-mute"><MessageSquareText size={13} /> Today's request (scenario)</div>
          <p className="num text-[13px] leading-relaxed text-sub">@mandi-intake {raw}</p>
        </div>
        <button onClick={() => director('start')}
          className="mt-5 rounded-md border border-marigold/50 bg-marigold/10 px-3.5 py-2 text-[13px] font-medium text-marigold hover:bg-marigold/20">
          Run it as a rehearsal (Director)
        </button>
      </div>
    </div>
  )
}

export function SpecPanel() {
  const view = useStore((s) => s.view)
  if (!view) return null
  const o = view.order
  const sp = o.spec
  const fields: [string, React.ReactNode, boolean?][] = [
    ['Part', sp.part_name],
    ['Specification', sp.part_spec],
    ['Drawing', <>{sp.drawing_ref} <span className="text-amber">· assumed from last purchase</span></>, true],
    ['Quantity', <span className="num">{group(sp.quantity ?? 0)} {sp.uom}</span>],
    ['Needed by', <>{shortDate(sp.needed_by)} · {sp.delivery_terms}</>],
    ['Prices', 'INR, excluding GST'],
  ]
  return (
    <div className="grid h-full grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-0">
      <div className="border-r border-hair p-6">
        <div className="mb-3 flex items-center gap-2 text-[12.5px] text-mute"><MessageSquareText size={14} /> What Rohan typed in the order room</div>
        <p className="num whitespace-pre-wrap text-[14px] leading-[1.7] text-sub/80">{o.raw_request}</p>
        <div className="mt-6 text-[12.5px] leading-relaxed text-mute">
          Messy on purpose: “20k”, “mid next month”, “like last time”. The intake agent reads it, checks it against the item master, and asks one question instead of ten.
        </div>
      </div>
      <div className="relative p-6">
        <div className="mb-3 flex items-center gap-2 text-[12.5px] text-mute"><Sparkles size={14} className="text-marigold" /> Structured spec drafted by mandi-intake</div>
        <dl className="divide-y divide-hair rounded-lg border border-hair">
          {fields.map(([k, v, warn], i) => (
            <motion.div key={k} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.08 * i }}
              className={cx('grid grid-cols-[130px_1fr] gap-3 px-4 py-2.5 text-[13.5px]', warn && 'bg-amber/[0.04]')}>
              <dt className="text-mute">{k}</dt>
              <dd className="text-text">{v}</dd>
            </motion.div>
          ))}
        </dl>
        <div className="mt-5">
          {o.spec_confirmed ? (
            <motion.div initial={{ scale: 1.15, opacity: 0, rotate: -4 }} animate={{ scale: 1, opacity: 1, rotate: -2 }}
              className="inline-flex items-center gap-2 rounded-md border-2 border-mint/60 px-3 py-1.5 text-[14px] font-semibold text-mint">
              <CheckCircle2 size={16} /> Confirmed by Rohan in Switch
            </motion.div>
          ) : (
            <Chip tone="amber">Waiting for Rohan to reply “yes” in the order room</Chip>
          )}
        </div>
        <Coach n={2} text="The intake agent turns a chat message into a precise spec, states its assumption, and waits for the requester to confirm in the room." />
      </div>
    </div>
  )
}

export function RoomsPanel() {
  const { view, feed } = useStore()
  if (!view) return null
  const vend = view.vendors
  const quoteOf = (v: string) => view.quotes.find((q) => q.vendor_id === v)
  const rfqSent = (k: string) => feed.some((f) => f.room_key === k && /request for quotation/i.test(f.body))
  return (
    <div className="flex h-full flex-col p-6">
      <p className="mb-5 max-w-2xl text-[14px] leading-relaxed text-sub">
        One request, four suppliers. Three get a <span className="text-indigo">sealed Switch room</span> with their own sales agent; the fourth quote was found in the purchase mailbox.
        No supplier can see another's room, price or documents.
      </p>
      <div className="grid flex-1 grid-cols-4 gap-3">
        {['deccan', 'ganesh', 'apex', 'konkan'].map((k, i) => {
          const v = vend.find((x) => x.vendor_id === k)
          const q = quoteOf(k)
          const room = k !== 'konkan'
          const steps = room
            ? [['Room sealed', true], ['RFQ sent', rfqSent(k)], ['Quote received via Switch', !!q], ['Quote analysed', !!q?.parsed]]
            : [['No agent, no room', true], ['Found in mailbox', !!q], ['Quote analysed', !!q?.parsed]]
          return (
            <motion.div key={k} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.12 }}
              className={cx('flex flex-col rounded-lg border p-4', room ? 'border-indigo/35 bg-raise' : 'border-hair bg-raise/60')}>
              <div className="flex items-center gap-2 text-[14px] font-semibold">
                {room ? <Lock size={15} className="text-indigo" /> : <Mail size={15} className="text-sub" />}
                {v?.legal_name}
              </div>
              <div className="num mt-1 text-[11.5px] text-mute">{room ? `${k}-sales ↔ mandi-negotiator-${k}` : 'quote PDF, “found in email”'}</div>
              <ol className="mt-4 space-y-2.5">
                {steps.map(([label, ok]) => (
                  <li key={label as string} className={cx('flex items-center gap-2 text-[13px]', ok ? 'text-text' : 'text-mute')}>
                    {ok ? <CheckCircle2 size={14} className="text-mint" /> : <span className="h-3.5 w-3.5 rounded-full border border-hair-2" />}
                    {label as string}
                  </li>
                ))}
              </ol>
              {q && (
                <div className="mt-auto flex items-center gap-1.5 pt-4 text-[12px] text-sub">
                  {room ? <Send size={12} /> : <FileText size={12} />} {q.received_via === 'switch_attachment' ? 'PDF attached in the Switch room' : 'imported from mailbox'}
                </div>
              )}
            </motion.div>
          )
        })}
      </div>
      <Coach n={3} text="Sealed rooms are ordinary Switch rooms with private channels. Membership is the wall: a supplier's agent only receives events for its own room." className="!top-3" />
    </div>
  )
}
