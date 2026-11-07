import { ArrowLeft, Bot, Lock, User } from 'lucide-react'

const CAST = [
  { who: 'Rohan Kulkarni', what: 'Seat engineer at Sahyadri Motors. Asks for the parts.', kind: 'human' },
  { who: 'Meera Joshi', what: 'Purchase head. Endorses the deal — only she can.', kind: 'human' },
  { who: 'Vikram Shah', what: 'Finance controller. Releases the purchase order — only he can.', kind: 'human' },
  { who: 'Asha · Sanjay · Karan', what: 'People at three supplier companies. Each owns their company\'s sales agent.', kind: 'human' },
  { who: 'mandi-intake, mandi-quotes', what: 'Read the request, open the RFQ, read every quote and catch traps.', kind: 'agent' },
  { who: 'mandi-negotiator-×3', what: 'One per sealed supplier room. Haggle using only verified offers.', kind: 'agent' },
  { who: 'deccan-sales, ganesh-sales, apex-sales', what: 'The suppliers\' own AI sales agents, with limits only their owners can lift.', kind: 'agent' },
  { who: 'purchase-desk, po-issuer', what: 'Claude Code agents for Meera and Vikram. Their one money tool always asks first.', kind: 'agent' },
  { who: 'mandi-auditor', what: 'Neutral record-keeper. Listens everywhere, writes the audit log.', kind: 'agent' },
]

// Keep in sync with the README's stage map.
const STAGES: { name: string; built: boolean; what: string }[] = [
  { name: 'Requisition approval', built: false, what: 'Today the requester confirms the spec in chat. A manager approving the requisition itself is roadmap.' },
  { name: 'RFQ and quotes', built: true, what: 'Sealed room per supplier; PDF quotes read with evidence; traps and prompt injection caught. Works with PDF-only suppliers too.' },
  { name: 'Comparative statement', built: true, what: 'Landed-cost comparison with a code-written recommendation, saved to the room; MOCK CSV export.' },
  { name: 'Negotiation', built: true, what: 'Parallel, in sealed rooms, citing only verified offers. Supplier agents are an opt-in "supplier desk".' },
  { name: 'Sign-off chain', built: true, what: 'Value tiers; purchase head then finance allow a Claude Code permission request that Switch relays and records. Reminder and escalation chaser: roadmap.' },
  { name: 'Purchase order', built: true, what: 'PO PDF after the rules check again; MOCK SAP-style PO export (not an SAP integration) for the system of record.' },
  { name: 'Delivery receipt', built: false, what: 'Goods receipt at the plant and closing the order: roadmap.' },
]

const FLOW = [
  'Rohan types a messy request in the order room.',
  'The intake agent turns it into a precise spec; Rohan replies “yes”.',
  'Three suppliers each get a sealed Switch room with their own sales agent.',
  'Quotes arrive as PDFs. The analyst catches a hidden minimum order, an expired quote, and a hidden prompt injection.',
  'Negotiators haggle in parallel, citing only offers Mandi has verified — anonymously.',
  'When a supplier\'s agent wants to go below its limit, it asks its own human. She says no.',
  'Meera and Vikram each tap Allow on a permission request that Switch relays from an agent only they can instruct.',
  'Mandi\'s rules check everything again and issue the PO. Everything is saved in the room.',
]

export function How() {
  return (
    <div className="h-full overflow-y-auto bg-ink">
      <div className="mx-auto max-w-[1080px] px-10 py-10">
        <a href="#/" className="inline-flex items-center gap-1.5 text-[13px] text-sub hover:text-text"><ArrowLeft size={14} /> Back to the Control Room</a>
        <h1 className="mt-6 text-[40px] font-semibold leading-tight tracking-tight">How Mandi works</h1>
        <p className="mt-3 max-w-2xl text-[16px] leading-relaxed text-sub">
          Buying one part can take a factory two weeks: quotes in five formats, a comparison built by hand, then signatures going back and forth
          between purchase and finance. Mandi runs that back-and-forth in team chat with AI agents, and every rupee still needs a person's tap to move.
        </p>

        <h2 className="mt-12 text-[20px] font-semibold">What Switch is</h2>
        <p className="mt-2 max-w-3xl text-[15px] leading-relaxed text-sub">
          Switch puts people and AI agents in the same chat rooms (here, Mattermost). Each agent has an owner, and its owner decides who may give it instructions.
          When a Claude Code agent's provider pauses a risky tool call, Switch relays that permission request into the room — only the people that agent listens to can answer — and records who did.
          Rooms also keep shared instructions, roles and documents, so the whole deal lives in one place.
        </p>

        <h2 className="mt-12 text-[20px] font-semibold">The cast</h2>
        <div className="mt-4 grid grid-cols-3 gap-3">
          {CAST.map((c) => (
            <div key={c.who} className="rounded-lg border border-hair bg-pane p-4">
              <div className={`flex items-center gap-2 text-[14px] font-semibold ${c.kind === 'human' ? 'text-marigold' : 'text-teal'}`}>
                {c.kind === 'human' ? <User size={14} /> : <Bot size={14} />}{c.who}
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-sub">{c.what}</p>
            </div>
          ))}
        </div>

        <h2 className="mt-12 text-[20px] font-semibold">Three locks on the money</h2>
        <div className="mt-4 grid grid-cols-3 gap-3">
          {[
            ['1. Switch identity', 'Who may even talk to an agent. The PO issuer only listens to Vikram; a supplier\'s agent only to its owner and Mandi\'s negotiator.', 'text-teal border-teal/40'],
            ['2. Permission request', 'The money tools always ask first: Claude Code\'s permission check is the actual gate. Switch relays the request into the room, decides who may answer (the agent\'s one permitted person) and records who did.', 'text-indigo border-indigo/40'],
            ['3. Mandi rules', 'Even after both taps, code refuses a PO that doesn\'t match the deal, the approval tier, or a valid supplier. Prompts aren\'t security; code is.', 'text-marigold border-marigold/40'],
          ].map(([t, d, cls]) => (
            <div key={t} className={`rounded-lg border bg-pane p-5 ${cls}`}>
              <div className="flex items-center gap-2 text-[15px] font-semibold"><Lock size={15} />{t}</div>
              <p className="mt-2 text-[13.5px] leading-relaxed text-sub">{d}</p>
            </div>
          ))}
        </div>

        <h2 className="mt-12 text-[20px] font-semibold">Stage map: where Mandi sits in a purchase</h2>
        <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-sub">
          Most of the pain is inside the buyer: quotes, the comparison, and signatures going back and forth between purchase, finance and other teams.
          Mandi handles that back-and-forth in chat <em>before</em> the record exists, and ends with a PO ready for the ERP, which stays the system of record.
        </p>
        <ol className="mt-4 grid grid-cols-7 gap-2">
          {STAGES.map((st, i) => (
            <li key={st.name} className={`rounded-lg border p-3 ${st.built ? 'border-mint/40 bg-pane' : 'border-dashed border-hair bg-ink'}`}>
              <div className="num text-[11px] text-mute">{i + 1}</div>
              <div className="mt-0.5 text-[13.5px] font-semibold leading-snug text-text">{st.name}</div>
              <div className={`mt-1.5 inline-block rounded px-1.5 py-px text-[10.5px] uppercase tracking-wide ${st.built ? 'bg-mint/15 text-mint' : 'border border-hair text-mute'}`}>{st.built ? 'Built' : 'Roadmap'}</div>
              <p className="mt-2 text-[12px] leading-relaxed text-sub">{st.what}</p>
            </li>
          ))}
        </ol>

        <h2 className="mt-12 text-[20px] font-semibold">The flow, in eight steps</h2>
        <ol className="mt-4 space-y-2.5">
          {FLOW.map((f, i) => (
            <li key={i} className="flex gap-4 text-[15px] leading-relaxed text-sub">
              <span className="num flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-hair text-[12px] text-text">{i + 1}</span>{f}
            </li>
          ))}
        </ol>
        <p className="mt-12 text-[22px] font-medium tracking-tight">Agents negotiate. Humans decide. <span className="text-marigold">Switch records who said yes.</span></p>
        <p className="mt-2 text-[12.5px] text-mute">Sahyadri Motors and all suppliers are fictional. Inspired by what Divya saw on the procurement floor at an automaker.</p>
      </div>
    </div>
  )
}
