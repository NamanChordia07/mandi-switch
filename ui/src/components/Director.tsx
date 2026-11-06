import { Clapperboard, FlaskConical, Gauge, Play, RotateCcw, ShieldAlert, Users, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { director, refreshAll } from '../lib/api'
import { useStore } from '../lib/store'
import { cx } from './ui'

export function DirectorDrawer() {
  const { director: open, set, recording } = useStore()
  const [msg, setMsg] = useState<string>('')
  const [speed, setSpeed] = useState(1)
  const [rehearsal, setRehearsal] = useState(false)
  const run = async (action: string, body: Record<string, unknown> = {}, label = action) => {
    setMsg(`${label}…`)
    const r = await director(action, body)
    if (action === 'redteam-fooled-po' && r.refused) setMsg(`Refused by Mandi's PO rules:\n• ${(r.failed_checks ?? []).join('\n• ')}`)
    else setMsg(r.ok === false ? `Not possible now: ${r.detail ?? 'see logs'}` : `${label}: done`)
    refreshAll()
  }
  return (
    <AnimatePresence>
      {open && !recording && (
        <motion.aside initial={{ x: 380 }} animate={{ x: 0 }} exit={{ x: 380 }} transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="fixed bottom-0 right-0 top-14 z-40 flex w-[360px] flex-col border-l border-hair bg-ink shadow-2xl" aria-label="Director">
          <div className="flex items-center justify-between border-b border-hair px-4 py-3">
            <h2 className="flex items-center gap-2 text-[14px] font-semibold"><Clapperboard size={15} className="text-marigold" /> Director</h2>
            <button onClick={() => set({ director: false })} aria-label="Close director"><X size={16} className="text-sub" /></button>
          </div>
          <div className="space-y-5 overflow-y-auto p-4 text-[13px]">
            <Group title="Run">
              <Btn icon={<Play size={14} />} onClick={() => run('start', {}, 'Start scenario')}>Start scenario (rehearsal request)</Btn>
              <p className="text-[12px] text-mute">For the real demo, Rohan types the request in Mattermost instead.</p>
              <div className="flex items-center gap-2"><Gauge size={14} className="text-sub" /> Pace
                {[0.5, 1, 2].map((s) => (
                  <button key={s} onClick={() => { setSpeed(s); run('speed', { speed: s }, `Speed ${s}×`) }}
                    className={cx('rounded border px-2 py-0.5', speed === s ? 'border-marigold/60 text-marigold' : 'border-hair text-sub')}>{s}×</button>
                ))}
              </div>
            </Group>
            <Group title="Red-team tests">
              <Btn tone="vermilion" icon={<ShieldAlert size={14} />} onClick={() => run('redteam-leverage', { vendor_id: 'deccan', fake_paise: 3300 }, 'Fake leverage')}>Negotiator cites a fake ₹33.00 offer</Btn>
              <Btn tone="vermilion" icon={<FlaskConical size={14} />} onClick={() => run('redteam-fooled-po', {}, 'Fooled agent')}>Fooled agent calls issue_po for Apex</Btn>
            </Group>
            <Group title="Rehearsal only">
              <label className="flex items-start gap-2 text-sub">
                <input type="checkbox" checked={rehearsal} onChange={(e) => { setRehearsal(e.target.checked); director('rehearsal-humans', { on: e.target.checked }) }} className="mt-1" />
                <span><Users size={13} className="mr-1 inline" />Simulate Rohan's “yes” and Asha's decline (clearly labelled in chat). Never simulates the Switch approvals of Meera and Vikram.</span>
              </label>
            </Group>
            <Group title="Reset">
              <Btn icon={<RotateCcw size={14} />} onClick={() => { if (confirm('Reset Mandi Core for a new run? Switch rooms are kept.')) run('reset', {}, 'Reset') }}>Reset demo (fresh Core, keep rooms)</Btn>
            </Group>
            <Group title="View">
              <Btn onClick={() => set({ recording: true, director: false })}>Recording mode (Esc to exit)</Btn>
            </Group>
            {msg && <pre className="whitespace-pre-wrap rounded-md border border-hair bg-raise p-3 text-[12px] text-sub">{msg}</pre>}
            <p className="text-[11.5px] leading-relaxed text-mute">Keys: S start · E explain · G God view · D director · R reset · F fullscreen · 1–8 stages · Esc auto-follow</p>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><h3 className="mb-2 text-[12px] font-medium text-mute">{title}</h3><div className="space-y-2">{children}</div></div>
}

function Btn({ children, onClick, icon, tone }: { children: React.ReactNode; onClick: () => void; icon?: React.ReactNode; tone?: 'vermilion' }) {
  return (
    <button onClick={onClick} className={cx('flex w-full items-center gap-2 rounded-md border px-3 py-2 text-left',
      tone === 'vermilion' ? 'border-vermilion/40 text-vermilion hover:bg-vermilion/10' : 'border-hair text-text hover:bg-raise')}>
      {icon}{children}
    </button>
  )
}
