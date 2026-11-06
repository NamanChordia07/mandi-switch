import { Check, CircleDot, Lightbulb, Lock, Moon, Radio, SlidersHorizontal, Sun, TriangleAlert } from 'lucide-react'
import { STAGES, liveStage, useStore, type StageKey } from '../lib/store'
import { elapsed, group, shortDate } from '../lib/format'
import { Chip, cx } from './ui'

export function TopBar() {
  const { cfg, view, health, explain, director, theme, recording, set, sse } = useStore()
  const o = view?.order
  const sc = cfg?.scenario
  const live = !!health?.switch?.switch_live
  const tierLabel = view?.tier?.label
  return (
    <header className="flex h-14 shrink-0 items-center gap-6 border-b border-hair bg-ink px-5">
      <a href="#/" className="flex items-baseline gap-2" aria-label="Mandi Control Room">
        <span className="text-[22px] font-semibold tracking-tight text-text">Mandi</span>
        <span className="font-deva text-[19px] leading-none text-marigold">मंडी</span>
      </a>
      <div className="h-6 w-px bg-hair" />
      <div className="flex min-w-0 items-center gap-4 text-[13px]">
        <span className="num font-medium text-text">{o?.id ?? sc?.order_id ?? '—'}</span>
        <span className="truncate text-sub">
          {o?.spec?.part_name ?? sc?.part.name} M10 · 10.9 · zinc-flake
        </span>
        <span className="num text-sub">{group(o?.spec?.quantity ?? sc?.quantity ?? 0)} pcs</span>
        {o?.spec?.needed_by && <span className="text-sub">needed by <span className="text-text">{shortDate(o.spec.needed_by)}</span></span>}
        {tierLabel && <Chip tone="indigo"><Lock size={11} /> {tierLabel}</Chip>}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <span
          className={cx('flex items-center gap-2 rounded-full border px-3 py-1 text-[12px]', live ? 'border-mint/40 text-mint' : 'border-hair text-mute')}
          title={live ? 'The auditor agent is connected to Switch; the feed on the right is real room traffic.' : 'The auditor agent is not connected to Switch right now.'}
        >
          <span className={cx('h-2 w-2 rounded-full', live ? 'live-dot bg-mint' : 'bg-mute')} />
          {live ? 'Live via Switch' : 'Switch not connected'}
        </span>
        {sse === 'lost' && <Chip tone="vermilion"><TriangleAlert size={11} /> Core connection lost — retrying</Chip>}
        {!recording && (
          <>
            <IconBtn label="Explain (E)" active={explain} onClick={() => set({ explain: !explain })}><Lightbulb size={16} /></IconBtn>
            <IconBtn label="Theme" onClick={() => set({ theme: theme === 'dark' ? 'light' : 'dark' })}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</IconBtn>
            <a href="#/how" className="rounded-md px-2 py-1 text-[12.5px] text-sub hover:text-text">How it works</a>
            <IconBtn label="Director (D)" active={director} onClick={() => set({ director: !director })}><SlidersHorizontal size={16} /></IconBtn>
          </>
        )}
      </div>
    </header>
  )
}

function IconBtn({ label, active, onClick, children }: { label: string; active?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} title={label} aria-label={label} aria-pressed={active}
      className={cx('flex h-8 w-8 items-center justify-center rounded-md border transition-colors', active ? 'border-marigold/60 bg-marigold/10 text-marigold' : 'border-transparent text-sub hover:border-hair hover:text-text')}>
      {children}
    </button>
  )
}

export function Stepper() {
  const { view, pinned, set } = useStore()
  const current = liveStage(view)
  const ci = STAGES.findIndex((s) => s.key === current)
  const times = view?.order?.stage_times ?? {}
  const startOf = (k: StageKey) => {
    const st = STAGES.find((s) => s.key === k)!
    for (const e of st.enters) if (times[e]) return times[e]
    return undefined
  }
  const blocked = view?.quotes?.some((q) => q.injection_verdict === 'INJECTION')
  const done = view?.order?.state === 'PO_ISSUED'
  return (
    <nav aria-label="Stages" className="flex h-12 shrink-0 items-stretch border-b border-hair bg-ink px-3">
      {STAGES.map((s, i) => {
        const isDone = i < ci || (done && i === ci)
        const isCur = i === ci && !done
        const sel = (pinned ?? current) === s.key
        const next = STAGES[i + 1]
        const t0 = startOf(s.key)
        const t1 = next ? startOf(next.key) : times['PO_ISSUED']
        const warn = s.key === 'quotes' && blocked
        return (
          <button key={s.key} disabled={i > ci} onClick={() => set({ pinned: s.key === current ? null : s.key })}
            className={cx('group relative flex flex-1 items-center gap-2.5 px-3 text-left disabled:cursor-default',
              sel && 'bg-pane')}>
            <span className={cx('num flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px]',
              isDone ? 'border-mint/50 bg-mint/15 text-mint' : isCur ? 'border-marigold bg-marigold/15 text-marigold shadow-[0_0_14px_-2px] shadow-marigold/60' : 'border-hair text-mute')}>
              {isDone ? <Check size={13} /> : i + 1}
            </span>
            <span className="min-w-0">
              <span className={cx('block text-[13px] font-medium', isDone || isCur ? 'text-text' : 'text-mute')}>
                {s.label}{warn && <TriangleAlert size={12} className="ml-1 inline text-vermilion" />}
              </span>
              <span className="num block text-[11px] text-mute">{t0 ? elapsed(t0, isDone ? t1 : undefined) : ''}</span>
            </span>
            {sel && <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-marigold" />}
          </button>
        )
      })}
    </nav>
  )
}

export function SimBanner() {
  const { feed, health } = useStore()
  const sim = !health?.switch?.switch_live && feed.some((f) => f.data?.simulated)
  if (!sim) return null
  return (
    <div className="flex items-center gap-2 border-b border-amber/30 bg-amber/10 px-5 py-1.5 text-[12.5px] text-amber">
      <Radio size={13} /> Replay mode: this run was simulated without Switch (scripts/simulate.py). Messages marked “simulated” did not travel through Switch.
    </div>
  )
}

export function StageHint({ stage }: { stage: StageKey }) {
  return <CircleDot size={12} className={cx(stage ? 'text-marigold' : '')} />
}
