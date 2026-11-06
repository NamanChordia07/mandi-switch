/** Indian money formatting. Money arrives from Core as integer paise. */
export function group(n: number): string {
  const neg = n < 0
  const s = Math.abs(Math.trunc(n)).toString()
  if (s.length <= 3) return (neg ? '-' : '') + s
  let head = s.slice(0, -3)
  const tail = s.slice(-3)
  const parts: string[] = []
  while (head.length > 2) {
    parts.unshift(head.slice(-2))
    head = head.slice(0, -2)
  }
  if (head) parts.unshift(head)
  return (neg ? '-' : '') + parts.join(',') + ',' + tail
}

export function inr(paise: number | null | undefined, opts: { decimals?: boolean } = {}): string {
  if (paise === null || paise === undefined) return '—'
  const decimals = opts.decimals ?? paise % 100 !== 0
  const p = Math.abs(paise)
  const sign = paise < 0 ? '-' : ''
  if (decimals) return `${sign}₹${group(Math.floor(p / 100))}.${String(p % 100).padStart(2, '0')}`
  return `${sign}₹${group(Math.round(p / 100))}`
}

export const unit = (paise: number | null | undefined) => inr(paise, { decimals: true })

export function shortDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso)
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

export function clock(iso?: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export function elapsed(fromIso?: string | null, toIso?: string | null): string {
  if (!fromIso) return ''
  const a = new Date(fromIso).getTime()
  const b = toIso ? new Date(toIso).getTime() : Date.now()
  const s = Math.max(0, Math.round((b - a) / 1000))
  const m = Math.floor(s / 60)
  return m ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${s}s`
}

export const titleCase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
