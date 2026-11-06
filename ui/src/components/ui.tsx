import type { ReactNode } from 'react'
import { useStore } from '../lib/store'

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ')
}

export type Tone = 'mint' | 'amber' | 'vermilion' | 'indigo' | 'teal' | 'marigold' | 'mute'

const toneText: Record<Tone, string> = {
  mint: 'text-mint', amber: 'text-amber', vermilion: 'text-vermilion', indigo: 'text-indigo', teal: 'text-teal',
  marigold: 'text-marigold', mute: 'text-sub',
}
const toneBg: Record<Tone, string> = {
  mint: 'bg-mint/10 border-mint/30', amber: 'bg-amber/10 border-amber/30', vermilion: 'bg-vermilion/10 border-vermilion/35',
  indigo: 'bg-indigo/10 border-indigo/30', teal: 'bg-teal/10 border-teal/30', marigold: 'bg-marigold/10 border-marigold/35',
  mute: 'bg-raise border-hair',
}

export function Chip({ tone = 'mute', children, title, className }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px] leading-4 whitespace-nowrap', toneBg[tone], toneText[tone], className)}>
      {children}
    </span>
  )
}

export function Pane({ title, aside, children, className, bodyClass, explain }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; explain?: { n: number; text: string }
}) {
  return (
    <section className={cx('relative flex min-h-0 flex-col bg-pane', className)}>
      {(title || aside) && (
        <header className="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-hair px-4">
          <h2 className="truncate text-[13px] font-semibold text-text">{title}</h2>
          <div className="flex items-center gap-2 text-sub">{aside}</div>
        </header>
      )}
      <div className={cx('min-h-0 flex-1', bodyClass)}>{children}</div>
      {explain && <Coach n={explain.n} text={explain.text} />}
    </section>
  )
}

/** Explain-mode coach mark. Renders only when Explain mode is on. */
export function Coach({ n, text, className }: { n: number; text: string; className?: string }) {
  const on = useStore((s) => s.explain)
  if (!on) return null
  return (
    <div className={cx('pointer-events-none absolute right-3 top-12 z-30 max-w-[300px]', className)}>
      <div className="flex gap-2 rounded-lg border border-marigold/50 bg-ink/95 p-3 text-[12.5px] leading-snug text-text shadow-2xl shadow-black/40">
        <span className="num flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-marigold text-[11px] font-semibold text-ink">{n}</span>
        <span>{text}</span>
      </div>
    </div>
  )
}

export function Money({ paise, className, decimals }: { paise: number | null | undefined; className?: string; decimals?: boolean }) {
  if (paise === null || paise === undefined) return <span className={cx('num text-mute', className)}>—</span>
  const p = Math.abs(paise)
  const rupees = Math.floor(p / 100)
  const showDec = decimals ?? p % 100 !== 0
  const s = rupees.toString()
  let head = s.length > 3 ? s.slice(0, -3) : ''
  const tail = s.length > 3 ? s.slice(-3) : s
  const parts: string[] = []
  while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2) }
  if (head) parts.unshift(head)
  const grouped = parts.length ? parts.join(',') + ',' + tail : tail
  return (
    <span className={cx('num', className)}>
      ₹{grouped}{showDec && <span className="opacity-80">.{String(p % 100).padStart(2, '0')}</span>}
    </span>
  )
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      {icon && <div className="text-mute">{icon}</div>}
      <p className="text-[15px] font-medium text-text">{title}</p>
      {children && <div className="max-w-md text-[13px] leading-relaxed text-sub">{children}</div>}
    </div>
  )
}

export function Who({ name, kind }: { name: string; kind: 'human' | 'agent' | 'switch' | 'unknown' }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cx('h-1.5 w-1.5 rounded-full', kind === 'agent' ? 'bg-teal' : kind === 'human' ? 'bg-marigold' : 'bg-indigo')} />
      <span className={cx('font-medium', kind === 'human' ? 'text-marigold' : kind === 'agent' ? 'text-teal' : 'text-indigo')}>{name}</span>
    </span>
  )
}
