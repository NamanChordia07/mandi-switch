import { Ban, CheckCircle2, FileText, Fingerprint, Gavel, KeyRound, Link2, Lock, ShieldAlert, Users } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { clock } from '../lib/format'
import { useStore } from '../lib/store'
import { Coach, cx } from './ui'

const ICON: Record<string, React.ReactNode> = {
  INJECTION_BLOCKED: <ShieldAlert size={13} className="text-vermilion" />, VENDOR_DISQUALIFIED: <Ban size={13} className="text-vermilion" />,
  LEVERAGE_BLOCKED: <Ban size={13} className="text-vermilion" />, PO_REFUSED_BY_RULE: <Gavel size={13} className="text-vermilion" />,
  LEVERAGE_VERIFIED: <CheckCircle2 size={13} className="text-indigo" />, ENDORSED: <KeyRound size={13} className="text-mint" />,
  PO_ISSUED: <FileText size={13} className="text-mint" />, VENDOR_APPROVAL_DECIDED: <Lock size={13} className="text-indigo" />,
  TRAP_FOUND: <ShieldAlert size={13} className="text-amber" />, ROOMS_OPENED: <Users size={13} className="text-teal" />,
}

export function AuditTicker() {
  const audit = useStore((s) => s.audit)
  const events = (audit?.events ?? []).filter((e) => e.kind !== 'STATE_CHANGED').slice(-14).reverse()
  return (
    <section className="relative flex min-h-0 flex-col bg-pane">
      <header className="flex h-9 shrink-0 items-center justify-between border-b border-hair px-4">
        <h2 className="text-[13px] font-semibold">Audit trail</h2>
        <span className={cx('flex items-center gap-1.5 text-[11.5px]', audit?.verified.ok ? 'text-mint' : 'text-mute')}>
          <Link2 size={12} /> {audit ? (audit.verified.ok ? `Hash chain verified · ${audit.verified.checked} events` : 'Chain broken!') : 'No events yet'}
        </span>
      </header>
      <div className="flex min-h-0 flex-1 gap-2 overflow-x-auto overflow-y-hidden p-2">
        <AnimatePresence initial={false}>
          {events.map((e) => (
            <motion.div key={e.seq} layout initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }}
              className="flex w-[300px] shrink-0 flex-col rounded-md border border-hair bg-raise px-3 py-2">
              <div className="flex items-center gap-1.5 text-[11px] text-mute">
                {ICON[e.kind] ?? <Fingerprint size={13} className="text-sub" />}
                <span className="num">#{e.seq}</span><span>{clock(e.at)}</span>
                <span className="ml-auto truncate">{e.actor.replace('agent:', '')}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-[12px] leading-snug text-sub">{e.summary}</p>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      <Coach n={9} text="Every step is written to an append-only log where each entry carries the hash of the one before. Change any past entry and verification breaks." className="!top-10" />
    </section>
  )
}

export function ThreeLocks() {
  const { audit, view, feed } = useStore()
  const ev = audit?.events ?? []
  const has = (k: string) => ev.some((e) => e.kind === k)
  const refusal = feed.some((f) => /can'?t act on|not permitted|isn'?t permitted|only answers|refus/i.test(f.body) && f.sender_kind !== 'human')
  const locks = [
    { n: 1, name: 'Switch identity', tone: 'teal', on: refusal || has('ROOMS_OPENED'), note: refusal ? 'Refused a sender it does not answer' : 'Sealed rooms + who-can-talk rules' },
    { n: 2, name: 'Permission request', tone: 'indigo', on: has('ENDORSED') || has('VENDOR_APPROVAL_DECIDED'), note: has('ENDORSED') ? 'Humans allowed it; Switch recorded who' : 'Claude Code asks; Switch relays' },
    { n: 3, name: 'Mandi rules', tone: 'marigold', on: has('LEVERAGE_BLOCKED') || has('PO_REFUSED_BY_RULE') || has('INJECTION_BLOCKED'), note: has('PO_REFUSED_BY_RULE') ? 'Refused a PO by rule' : has('LEVERAGE_BLOCKED') ? 'Blocked an unverified claim' : has('INJECTION_BLOCKED') ? 'Blocked an injection' : 'Code checks every rupee' },
  ] as const
  const toneCls: Record<string, string> = { teal: 'border-teal/50 text-teal bg-teal/10', indigo: 'border-indigo/50 text-indigo bg-indigo/10', marigold: 'border-marigold/50 text-marigold bg-marigold/10' }
  return (
    <section className="relative flex min-h-0 flex-col bg-pane">
      <header className="flex h-9 shrink-0 items-center border-b border-hair px-4"><h2 className="text-[13px] font-semibold">Three locks on the money</h2></header>
      <div className="flex flex-1 flex-col justify-center gap-1 px-4 py-1.5">
        {locks.map((l) => (
          <div key={l.n} className="flex items-center gap-3">
            <motion.span animate={{ scale: l.on ? [1.25, 1] : 1 }} className={cx('flex h-6 w-6 shrink-0 items-center justify-center rounded-full border', l.on ? toneCls[l.tone] : 'border-hair text-mute')}>
              <Lock size={13} />
            </motion.span>
            <div className="min-w-0">
              <div className={cx('truncate text-[12.5px] leading-4', l.on ? 'text-text' : 'text-mute')}><span className="font-medium">{l.n}. {l.name}</span> <span className="text-mute">· {l.note}</span></div>
            </div>
          </div>
        ))}
      </div>
      {view && null}
    </section>
  )
}
