import { useEffect, useMemo, useRef, useState } from 'react'
import { Paperclip, ShieldCheck } from 'lucide-react'
import { useStore } from '../lib/store'
import { clock } from '../lib/format'
import type { FeedItem } from '../lib/types'
import { Chip, Coach, Who, cx } from './ui'

const ROOM_LABEL: Record<string, string> = { order: 'Order', deccan: 'Deccan', ganesh: 'Ganesh', apex: 'Apex', '': 'Other' }
const ROOM_TONE: Record<string, 'teal' | 'indigo' | 'vermilion' | 'mute'> = { order: 'teal', deccan: 'indigo', ganesh: 'indigo', apex: 'indigo', '': 'mute' }

/** Tiny, safe markdown: **bold**, `code`, ```blocks```, > quotes, tables, line breaks. No HTML injection. */
export function ChatBody({ text }: { text: string }) {
  const blocks = useMemo(() => {
    const out: React.ReactNode[] = []
    const parts = text.split(/```/)
    parts.forEach((part, i) => {
      if (i % 2 === 1) { out.push(<pre key={i}>{part.replace(/^\n/, '')}</pre>); return }
      const lines = part.split('\n')
      let table: string[][] = []
      const flush = (k: string) => {
        if (!table.length) return
        out.push(
          <table key={k}><tbody>{table.filter((r) => !r.every((c) => /^-+$/.test(c.trim()))).map((r, ri) => (
            <tr key={ri}>{r.map((c, ci) => <td key={ci}>{inline(c.trim())}</td>)}</tr>
          ))}</tbody></table>,
        )
        table = []
      }
      lines.forEach((ln, li) => {
        if (/^\s*\|.*\|\s*$/.test(ln)) { table.push(ln.trim().slice(1, -1).split('|')); return }
        flush(`${i}-${li}-t`)
        if (ln.startsWith('> ')) out.push(<blockquote key={`${i}-${li}`}>{inline(ln.slice(2))}</blockquote>)
        else if (ln.trim()) out.push(<div key={`${i}-${li}`}>{inline(ln)}</div>)
      })
      flush(`${i}-end`)
    })
    return out
  }, [text])
  return <div className="chat-body space-y-0.5 break-words">{blocks}</div>
}

function inline(s: string): React.ReactNode[] {
  const out: React.ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_|@[a-z0-9][a-z0-9._-]*)/g
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index))
    const t = m[0]
    if (t.startsWith('**')) out.push(<strong key={k++} className="font-semibold text-text">{t.slice(2, -2)}</strong>)
    else if (t.startsWith('`')) out.push(<code key={k++}>{t.slice(1, -1)}</code>)
    else if (t.startsWith('_')) out.push(<em key={k++} className="text-sub">{t.slice(1, -1)}</em>)
    else out.push(<span key={k++} className="font-medium text-marigold">{t}</span>)
    last = m.index + t.length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}

export function isApproval(f: FeedItem) {
  return /allow once|allow for this session|permission|approval needed/i.test(f.body)
}

export function FeedRow({ f, compact }: { f: FeedItem; compact?: boolean }) {
  const approval = isApproval(f)
  return (
    <div className={cx('rounded-md px-2.5 py-2', approval ? 'border border-indigo/40 bg-indigo/[0.07]' : 'hover:bg-raise/60')}>
      <div className="mb-0.5 flex items-center gap-2 text-[11.5px]">
        {!compact && <Chip tone={ROOM_TONE[f.room_key] ?? 'mute'} className="!px-1.5 !py-0 !text-[10.5px]">{ROOM_LABEL[f.room_key] ?? f.room_key}</Chip>}
        <Who name={f.sender_name} kind={f.sender_kind} />
        {approval && <span className="flex items-center gap-1 text-indigo"><ShieldCheck size={11} /> approval</span>}
        {f.data?.simulated && <span className="text-amber">simulated</span>}
        <span className="num ml-auto text-mute">{clock(f.at)}</span>
      </div>
      {f.event === 'message' ? (
        <div className="text-[12.5px] leading-[1.45] text-sub">
          <ChatBody text={f.body} />
          {(f.data?.attachments ?? []).map((a) => (
            <div key={a.filename} className="mt-1 inline-flex items-center gap-1 rounded border border-hair bg-ink/50 px-1.5 py-0.5 text-[11.5px] text-text"><Paperclip size={11} />{a.filename}</div>
          ))}
        </div>
      ) : (
        <div className="text-[12px] italic text-mute">{f.body}</div>
      )}
    </div>
  )
}

export function Feed() {
  const feed = useStore((s) => s.feed)
  const [room, setRoom] = useState<string>('all')
  const ref = useRef<HTMLDivElement>(null)
  const items = room === 'all' ? feed : feed.filter((f) => f.room_key === room)
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' }) }, [items.length])
  return (
    <section className="relative flex min-h-0 flex-col bg-pane">
      <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-hair px-4">
        <h2 className="text-[13px] font-semibold">Live Switch feed</h2>
        <div className="flex gap-1" role="tablist" aria-label="Filter by room">
          {['all', 'order', 'deccan', 'ganesh', 'apex'].map((r) => (
            <button key={r} role="tab" aria-selected={room === r} onClick={() => setRoom(r)}
              className={cx('rounded px-1.5 py-0.5 text-[11.5px]', room === r ? 'bg-raise text-text' : 'text-mute hover:text-sub')}>
              {r === 'all' ? 'All' : ROOM_LABEL[r]}
            </button>
          ))}
        </div>
      </header>
      <div ref={ref} className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        {items.length === 0 ? (
          <p className="p-6 text-center text-[12.5px] leading-relaxed text-mute">
            Messages from the Switch rooms appear here as they happen. Mandi's auditor agent listens to every room it belongs to and streams the traffic in.
          </p>
        ) : items.slice(-160).map((f) => <FeedRow key={f.id} f={f} />)}
      </div>
      <Coach n={5} text="This is the real chat traffic from the Switch rooms (Mattermost), captured by Mandi's auditor agent. Approval requests from Switch are outlined in indigo." />
    </section>
  )
}
