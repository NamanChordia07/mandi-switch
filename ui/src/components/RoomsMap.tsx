import { Bot, Lock, MessagesSquare, ShieldX, User } from 'lucide-react'
import { motion } from 'motion/react'
import { AGENTS, ROOMS } from '../lib/cast'
import { useStore } from '../lib/store'
import { Chip, Coach, cx } from './ui'

export function RoomsMap() {
  const { feed, view } = useStore()
  const counts: Record<string, number> = {}
  for (const f of feed) if (f.event === 'message') counts[f.room_key] = (counts[f.room_key] ?? 0) + 1
  const vstatus = Object.fromEntries((view?.vendors ?? []).map((v) => [v.vendor_id, v.status]))
  const rfq = !!view?.order?.rooms && Object.keys(view.order.rooms).length > 0
  return (
    <section className="relative flex min-h-0 flex-col bg-pane">
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-hair px-4">
        <h2 className="text-[13px] font-semibold">Switch rooms</h2>
        <span className="text-[11.5px] text-mute">1 order room · 3 sealed</span>
      </header>
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3">
        {ROOMS.map((r, i) => {
          const closed = vstatus[r.key] === 'DISQUALIFIED'
          const active = r.key === 'order' || rfq
          return (
            <motion.div key={r.key} layout
              className={cx('relative rounded-lg border p-3 transition-colors',
                closed ? 'border-vermilion/50 bg-vermilion/[0.06]' : r.sealed ? 'border-indigo/30 bg-raise' : 'border-teal/35 bg-raise',
                !active && 'opacity-60')}>
              {r.sealed && i > 0 && <span className="absolute -top-2.5 left-6 h-2.5 w-px bg-hair-2" aria-hidden />}
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-[13px] font-semibold">
                    {r.sealed ? <Lock size={13} className={closed ? 'text-vermilion' : 'text-indigo'} /> : <MessagesSquare size={13} className="text-teal" />}
                    <span className="truncate">{r.title}</span>
                  </div>
                  <div className="num mt-0.5 text-[11px] text-mute">{r.channel}</div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  {closed ? <Chip tone="vermilion"><ShieldX size={11} /> Closed: injection</Chip>
                    : r.sealed ? <Chip tone="indigo">Sealed</Chip> : <Chip tone="teal">Buyer only</Chip>}
                  <span className="num text-[11px] text-sub">{counts[r.key] ?? 0} msgs</span>
                </div>
              </div>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {r.people.map((p) => (
                  <span key={p} className="inline-flex items-center gap-1 rounded-md bg-ink/60 px-1.5 py-0.5 text-[11.5px] text-marigold"><User size={11} />{p}</span>
                ))}
              </div>
              <ul className="mt-2 space-y-1">
                {r.agents.map((a) => {
                  const ag = AGENTS[a]
                  return (
                    <li key={a} className="flex items-center justify-between gap-2 text-[11.5px]" title={`Who can talk to it: ${ag.talk}`}>
                      <span className="flex min-w-0 items-center gap-1.5 text-teal">
                        <Bot size={11} className="shrink-0" />
                        <span className="num truncate">{a}</span>
                        {ag.kind === 'claude-code' && <span className="rounded bg-indigo/15 px-1 text-[10px] text-indigo">Claude Code</span>}
                      </span>
                      <span className="shrink-0 text-mute">{ag.owner}</span>
                    </li>
                  )
                })}
              </ul>
            </motion.div>
          )
        })}
      </div>
      <Coach n={1} text="Each supplier negotiates in its own sealed Switch room. Its sales agent belongs to the supplier, and can't see the other rooms. Hover an agent to see who may talk to it." />
    </section>
  )
}
