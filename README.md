# Mandi <sub>मंडी</sub> — Slack Connect, but for agents

**AI agents from different companies negotiate a purchase in sealed Switch rooms. Every rupee still needs a human's tap to move.**

*Agents negotiate. Humans decide. Switch records who said yes.*

Built for the **Flip the Switch** hackathon (WeMakeDevs × DevTools Academy, powered by [Switch](https://docs.switchagents.ai) by SandboxAQ) · Track 01: Best Business Workflow

![Mandi Control Room — parallel negotiations in sealed rooms, live from Switch](docs/images/live-6-negotiate.png)

> 🎬 **Demo video:** TODO: add link · 📖 **How it works (plain English):** open the Control Room → *How it works*

---

## The 20-second version

At an automaker, buying one part can take **two weeks** of emails: quotes in five formats, a "cheapest" quote that hides a 50,000-unit minimum, another that expired last week, and approvals chased by phone.

**Mandi** turns that into **minutes** of work in team chat (≈2 minutes from request to award in our live run; the rest is how fast the two humans tap Allow). A requester asks in a Mattermost room. Mandi's agents write the spec, open one **sealed Switch room per supplier** — each with the supplier's **own** AI sales agent — catch the traps, block a **prompt-injection attack** hidden in a PDF, and haggle in parallel using only **verified** competing offers. The purchase order can only be issued after the **purchase head and finance each tap Allow** on a Switch approval request, on an agent only they can instruct — and Mandi's code checks everything once more.

| ₹62,000 saved (7.85%) | 3 traps caught | 1 prompt injection blocked | 2 human approvals in Switch | 1 supplier-side "no" |
|---|---|---|---|---|

## Screens

| A supplier's sealed room in Mattermost (Asha sees only this room; she declines going below her line) | The order room: PO PDF, Outcome card, and a **visible refusal** when Rohan tries to instruct `@po-issuer` |
|---|---|
| ![sealed room](docs/images/mm-deccan-sealed.png) | ![order room](docs/images/mm-order-room.png) |

| Quotes normalised, traps caught | Prompt injection revealed | Two humans, approved in Switch |
|---|---|---|
| ![quotes](docs/images/live-4-quotes.png) | ![injection](docs/images/live-injection.png) | ![approvals](docs/images/live-7-approve.png) |

**What Switch actually posted in the live run** (Mattermost, 6 Nov 2026):

> **PO Issuer (Vikram)** · `@vikram` **Permission needed** · request `A2` · mandi wants to run `issue_po` `{"order_id":"SM-PR-2026-0147"}` → **[1. Allow once] [2. Allow for this session] [3. Decline]**
> **PO Issuer (Vikram)** · **Allow once** · request `A2` · mandi wants to run issue_po · *Chosen by @vikram from Mattermost.*
> **PO Issuer (Vikram)** → `@rohan` *You're not permitted to direct messages to me in this room — my operator has restricted who can address me here.*
> **Switch** · `!roles` → **po-issuer** *(exclusive)* — 🟢 held by PO Issuer (Vikram)

---

## The story

Divya works at an automobile manufacturer and has watched this play out on the procurement floor: an engineer needs 20,000 seat-mounting bolts by mid-December; procurement emails four suppliers; quotes come back as PDFs with different layouts and fine print; someone builds a spreadsheet by hand, misses a minimum-order clause on page 2, negotiates over the phone, then walks the file around for signatures. Nobody can later explain *why* a vendor won.

Her original idea: **one chat room per order**, with agents for intake, quotes, comparison, negotiation and approvals, and humans approving by value. Mandi builds that — and pushes it further with things only a shared, identity-aware agent workspace makes possible:

- **Cross-company agents.** Each supplier is represented by an AI sales agent **owned by that supplier's people**, with secret limits only they can lift.
- **Sealed rooms.** One Switch room per supplier. A supplier's agent only ever receives events for its own room.
- **Injection defence.** Supplier documents are untrusted data. Hidden instructions are found, shown to humans, and the supplier is disqualified.
- **Verified leverage.** A negotiator may cite a rival's price only if Mandi holds that offer — and never says who.
- **Approvals Switch enforces.** Money moves only after the right human allows an agent's action in Switch, and Mandi's code agrees.

*(All companies and people in the product are fictional: Sahyadri Motors, Deccan Bolt Works, Shree Ganesh Fasteners, Apex Precision Components, Konkan Fasteners.)*

---

## How Switch is used

> **Remove Switch and Mandi has no sealed rooms, no cross-company agent identity, no human approval gate and no shared record — it stops working.**

| Mandi capability | Switch feature | Where in the code |
|---|---|---|
| One workspace per order + one **sealed room per supplier** | **Rooms** bound to Mattermost channels (private channels for suppliers); membership decides which events an agent receives | `scripts/bootstrap_switch.py` (`create_room` as `mandi-intake`) |
| Agents from **different companies** in one negotiation | **Agent ownership** via per-owner registration keys; several agents with different owners in one room | `scripts/register_agents.py`, `config/agents.yaml` |
| Suppliers can't instruct buyer agents and vice versa | **Who can talk to your agent** (scoped addressing policies) + **visible refusals** | `bootstrap_switch.py → policy_plan()` |
| Purchase head and finance approvals | **Permission requests** (Allow once / for this session / Decline) on Claude Code gate agents — **only the people an agent takes messages from can answer** — Mattermost **buttons**; Switch records who answered | `agents/gates/*`, `mcp_server/mandi_mcp.py` |
| Only one agent can ever issue a PO | **Exclusive role** `po-issuer` | bootstrap (`define_role … exclusive=True`) |
| Spec, comparison, negotiation logs, PO, audit log live with the work | **Room documents** + media attachments | `upsert_doc()` in `agents/switchclient/client.py` |
| Every agent knows each room's rules | **Room instructions** | `config/room-instructions/*.md` |
| Quotes travel through the sealed room | Agent **media upload/download** (`/agents/{id}/rooms/{room}/media`) | vendor agents, negotiator |
| Handoffs between agents | **Mentions / targeted messages** | all agents |
| Live dashboard fed by real chat | **Agent protocol** WebSocket, `scope=all, filter=all` | `agents/auditor/agent.py` → Control Room |
| Operators can inspect | **Room commands**: `!list-agents`, `!roles`, `!list-documents`, `!agents-status` | demo |

### The key insight: in Switch, *who an agent listens to* is *who can approve its actions*

Switch's docs: *"Anyone the agent takes messages from can answer its requests."* So Mandi's two gate agents take messages from **exactly one human each** — `purchase-desk` from Meera, `po-issuer` from Vikram — **and no agents, not even Mandi's own, and not their operator**. A compromised Mandi agent therefore can't approve anything. Meera types `@purchase-desk endorse`, the agent prepares a 4-line summary, calls its gated tool, and Switch asks *Meera* to allow it.

## Three locks on the money

```mermaid
flowchart LR
  A[Agent wants to move money] --> L1{Lock 1 · Switch identity<br/>does this agent take<br/>instructions from the sender?}
  L1 -- no --> R1[Visible refusal in the room]
  L1 -- yes --> L2{Lock 2 · Switch approval<br/>Allow on the permission request<br/>by the one permitted human}
  L2 -- decline --> R2[Nothing happens; decline recorded]
  L2 -- allow --> L3{Lock 3 · Mandi rules in code<br/>award · tier · endorsements · ledger<br/>vendor valid · not disqualified}
  L3 -- fail --> R3[409 + reasons; PO_REFUSED_BY_RULE audited]
  L3 -- pass --> PO[PO issued · PDF + hash-chained audit]
```

Prompts aren't security; code is. Even if an agent were fooled by the injected PDF (try **Director → "Fooled agent calls issue_po for Apex"**), Mandi Core refuses with five reasons.

## Architecture

```mermaid
flowchart TB
  subgraph Chat["Mattermost (team chat)"]
    OR["#order room"]; D["#deccan · sealed"]; G["#ganesh · sealed"]; AX["#apex · sealed"]
  end
  subgraph SW["Switch (server + Console)"]
    RM[rooms · instructions · documents · roles]; AD[ownership · who-can-talk]; PR[permission requests]; PROTO[agent protocol: WebSocket + HTTP ops]
  end
  Chat <--> SW
  subgraph Custom["Mandi custom agents (Python)"]
    I[mandi-intake]; Q[mandi-quotes]; N[3× mandi-negotiator]; AU[mandi-auditor]
  end
  subgraph Vendors["Supplier agents (Python, owned by suppliers)"]
    DS[deccan-sales]; GS[ganesh-sales]; AS[apex-sales]
  end
  subgraph Gates["Claude Code gate agents (run by Switch Console)"]
    PD[purchase-desk · Meera]; PI[po-issuer · Vikram]
  end
  PROTO <--> Custom & Vendors
  SW <--> Gates
  Custom -- REST --> CORE
  Gates -- MCP tools --> MCP[mandi_mcp.py] -- REST --> CORE
  CORE[(Mandi Core · FastAPI · SQLite<br/>rules · PO gate · audit chain · PDF)] -- SSE --> UI[Control Room · React]
  AU -- real Switch events --> CORE
```

Full walkthrough with sequence diagrams: **[docs/architecture.md](docs/architecture.md)**.

## The cast

| Agent | Kind | Owner | Room(s) | Who can talk to it | Can it move money? |
|---|---|---|---|---|---|
| `mandi-intake` | custom (Python) | Mandi Exchange | order | Rohan, Meera, Vikram, Mandi agents | no |
| `mandi-quotes` | custom | Mandi Exchange | order | buyer team, Mandi agents | no |
| `mandi-negotiator-{deccan,ganesh,apex}` | custom | Mandi Exchange | one sealed room each | that supplier's agent + person | no — every message checked by Core |
| `mandi-auditor` | custom, listen-only | Mandi Exchange | all | owner only | no |
| `deccan-sales` / `ganesh-sales` / `apex-sales` | custom | **Asha / Sanjay / Karan** | own sealed room only | own person + Mandi's negotiator | below its line only with its owner's OK |
| `purchase-desk` | **Claude Code**, managed agent run by Switch | operator account; **acts for Meera** | order | **Meera only** (no agents, not even its owner) | `endorse_order` → Switch asks Meera |
| `po-issuer` | **Claude Code**, managed agent run by Switch, exclusive role `po-issuer` | operator account; **acts for Vikram** | order | **Vikram only** | `issue_po` → Switch asks Vikram, then Core checks |

Ownership is real: `deccan-sales`, `ganesh-sales` and `apex-sales` were registered with registration keys created **by Asha's, Sanjay's and Karan's own Switch accounts**, so Switch lists those people as the owners. The two gate agents run on the operator's machine, so the operator owns them, but their addressing policy excludes the owner: only the one approver can instruct them, and therefore only that approver can answer their permission requests.

## How Mandi goes beyond Switch's own examples

| Switch example | What it shows | What Mandi adds |
|---|---|---|
| *Review a vendor purchase across teams* | Security/legal/finance agents review a SaaS purchase in one chat; sign-off happens outside the thread | Quote parsing with evidence, landed-cost comparison, **negotiation**, **cross-company agents in sealed rooms**, **injection defence**, sign-off **inside Switch** gating a real tool, PO issuance |
| *Build a payments room* | Roles, an exclusive release role, permission lists | Exclusive `po-issuer` role **plus** single-human addressing so only one person can approve, **plus** a code gate |
| *Incident response* | Agent asks sign-off before a rollback | Two-person, value-tiered approvals; supplier-side approvals by the supplier's own human |

---

## Quickstart

**Prerequisites:** Windows 11 / macOS / Linux · Python 3.11+ · Node 20+ · **Docker Desktop** (Switch's bundled Mattermost runs in Docker) · **Switch Console 0.40+** · Claude Code installed and signed in (it powers the two gate agents) · an **OpenAI API key** (custom agents; a full run costs about one US cent with `gpt-4o-mini`).

```powershell
# Windows PowerShell (macOS/Linux: same commands with .venv/bin/python, see scripts/*.sh)
git clone <this repo> mandi; cd mandi
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
python scripts/init_env.py            # creates .env with random Mandi Core tokens; paste OPENAI_API_KEY
python seed/make_quotes.py            # the four supplier quote PDFs
python scripts/setup_gates.py         # MCP config for the Claude Code gate agents
cd ui; npm install; npm run build; cd ..
```

Then set up Switch once. Three clicks in Switch Console; everything else is scripted ([docs/manual-setup.md](docs/manual-setup.md) has the details):

1. **Switch Console** → *Get started* → *On this computer* → *Start*. Console 0.40 runs the server natively (Python + bundled PostgreSQL).
2. **Power switch-buddy with Claude Code** (switch-buddy chat → *Connect an AI provider* → Claude Code). This enrols your computer as the machine that runs Claude Code agents.
3. **Admin → Status → Mattermost → on**, then **Restart**. Mattermost now runs in Docker beside the server and is connected.
4. Put the server address in `.env` as `SWITCH_BASE_URL` (Console picks the ports; see `%APPDATA%\switchdash\local-switch-server\ports.json`), along with the Gateway admin login (`SWITCH_ADMIN_EMAIL` / `SWITCH_ADMIN_PASSWORD`), `MATTERMOST_URL`, `MATTERMOST_TEAM=switch` and `MATTERMOST_CONTAINER`.

```powershell
python scripts/setup_switch_accounts.py   # Switch accounts for Asha/Sanjay/Karan + a registration key per owner
python scripts/create_personas.py         # Rohan, Meera, Vikram, Asha, Sanjay, Karan in Mattermost (mmctl --local)
python scripts/register_agents.py         # 9 custom agents, each registered with its OWNER's key
python scripts/create_gate_agents.py      # purchase-desk + po-issuer as managed Claude Code agents (asks first)
python scripts/bootstrap_switch.py        # 4 rooms + channels, instructions, exclusive role, 11 addressing policies
python scripts/doctor.py                  # every check green
```

Run:

```powershell
python scripts/run_all.py             # Mandi Core + 9 agents; Control Room at http://127.0.0.1:8700
```

No Switch at hand? `python scripts/simulate.py` replays the whole scenario through Mandi Core so you can explore the Control Room (clearly marked **Replay mode**; nothing in it pretends to be Switch).

## Run the demo yourself

Open four browser windows (`scripts/open-demo-windows.ps1` does it with separate profiles): Mandi Control Room, Mattermost as **Rohan**, as **Asha**, and as **Meera/Vikram**.

1. **Rohan** posts in the order room: `@mandi-intake hey team, need seat bolts for the new rear bench line…` → replies `yes` to the spec.
2. Watch the sealed rooms open, quotes arrive as PDFs, traps and the injection appear in the Control Room.
3. **Asha** gets `🔒 Approval needed` in the Deccan room → replies `decline`.
4. **Meera**: `@purchase-desk endorse SM-PR-2026-0147` → taps **Allow once** on Switch's request.
5. **Vikram**: `@po-issuer release the PO` → taps **Allow once** → PO PDF lands in the room, Outcome card posts, `!list-documents` shows the record.

Red-team (Director drawer, `D`): *fake leverage* (blocked before it reaches the supplier) and *fooled agent issues a PO for Apex* (refused by rule). Script and timing: **[docs/demo-script.md](docs/demo-script.md)**.

## Tests

```powershell
.venv\Scripts\python -m pytest            # 58 tests, offline: no Switch, no LLM calls
python scripts/live_rehearsal.py          # LIVE: plays Rohan/Asha in Mattermost; waits for a HUMAN to tap Allow
python scripts/simulate.py --fast         # end-to-end through Mandi Core's HTTP API
python tests/run_fake_e2e.py              # the REAL 9 agents end-to-end against a protocol stub (no Docker)
```

Covered: Indian money formatting, every trap, ranking and tie-breaks, tier boundaries (₹49,999 / ₹50,000 / ₹5,00,000 / ₹5,00,001), illegal state transitions, leverage verification (verified, fabricated, expired, disqualified, competitor named, number smuggled in text), every PO-gate check, audit-chain tampering and deletion, vendor token scoping, the full scenario, the decline path, the Switch client's ping/pong, resume and `taken_over` handling.

## Security notes

- **Prompt injection:** supplier PDFs are scanned for hidden text (tiny fonts, white-on-white, off-page, metadata, annotations), English + Hinglish patterns, and an LLM classifier that reads the text *as data*. LLM extractions must quote evidence that Core finds in the document, or the value is rejected.
- **Verified leverage & sealed bids:** every outbound negotiator message is checked by Core *before* it reaches Switch: claimed rival prices must match a valid, non-disqualified, comparable offer (±₹0.01); competitor names and unbacked rupee amounts are blocked.
- **PO gate:** caller identity, state, tier endorsements, accepted award, vendor status, quote validity, ledger arithmetic, no duplicate PO.
- **Audit trail:** append-only, SHA-256 hash-chained; the PO PDF carries the final hash.
- **Secrets:** `.env`, `secrets/*.local.json` are git-ignored; vendor agents load only their own rules file and get a vendor-scoped Core token.
- **Agents' powers:** "Can manage agents" and "Bypass permissions" stay off; gate agents deny shell/file/web tools.

**Real vs simulated.** Real: Switch rooms, agents, ownership, addressing policies, permission requests, room documents, Mattermost. Simulated: the companies, people, quotes and prices (all fictional). The supplier-side approval uses a Switch room message whose **sender identity Switch provides** (we check it), not a Switch permission request — see *Limitations*.

## Limitations and what's next

- Supplier-side approval is a message-based fallback (sender verified via Switch); the next step is a Claude Code "desk" agent per supplier so it becomes a real Switch permission request too.
- Switch Console on Windows is early access; we document what we hit (Virtual Machine Platform, Docker's first boot, protocol quirks) in [docs/switch-notes.md](docs/switch-notes.md).
- The two gate agents are owned by the operator account (Console can only run agents on the signed-in owner's machine); the addressing policy, not ownership, is what restricts them to Meera and Vikram.
- Single plant, single currency, GST excluded, invented approval thresholds.
- Roadmap: ERP/PO export, real supplier onboarding with their own Switch servers, reverse auctions, Switch Trust guardrails on all LLM calls, multi-currency.

## Built during the hackathon · Team

Built 4–7 Nov 2026 for Flip the Switch. **Naman Chordia** (automation engineer) and **Divya** (procurement insight from the automotive floor; plays Meera and the supplier owners in the demo).

Credits: [Switch](https://github.com/sandbox-quantum/switch) by SandboxAQ · WeMakeDevs · DevTools Academy · Noto Sans (SIL OFL) · Geist. Mandi's own code is MIT-licensed (see `LICENSE`); Switch has its own license.
