# Manual setup — Switch, Mattermost, personas, gate agents

Everything that needs a person clicking in a UI, in order. Each step says what you should see afterwards.
Commands assume Windows PowerShell in the repo folder (macOS/Linux: use `.venv/bin/python`).

## 0. Prerequisites

| Need | Why | Install |
|---|---|---|
| Docker Desktop (WSL2 backend on Windows) | Switch runs its bundled Mattermost in Docker | Admin PowerShell: `wsl --install --no-distribution`, reboot, then `winget install -e --id Docker.DockerDesktop`; start Docker Desktop and wait for **Engine running** |
| Switch Console 0.40+ | runs the Switch server + the Claude Code gate agents | [Download](https://docs.switchagents.ai/switch-rooms/getting-started/install-switch-console.md) (Windows build is early access) |
| Claude Code, signed in | provider for `purchase-desk` and `po-issuer` | `npm i -g @anthropic-ai/claude-code`, then `claude` once to sign in |
| OpenAI API key | wording + evidence-checked extraction in the custom agents | put it in `.env` as `OPENAI_API_KEY` |

## 1. Start the Switch server (Switch Console)

1. Switch Console → **Get started** → **On this computer** → **Start**. On Windows, Console 0.40 runs `switch-core` natively
   (Python venv + bundled PostgreSQL 16) — "This computer · runs without Docker".
2. Ports are chosen per install: `%APPDATA%\switchdash\local-switch-server\ports.json` (`api`, `gateway`, `mattermost`).
   Put `SWITCH_BASE_URL=http://127.0.0.1:<api>` in `.env`. Check: `curl <SWITCH_BASE_URL>/health` → `{"status":"ok"}`.
3. The Gateway admin login Console generated is in `%APPDATA%\switchdash\local-switch-server\native\run\switch-core.env`
   (`GATEWAY_ADMIN_EMAIL`, `GATEWAY_ADMIN_PASSWORD`) → copy to `.env` as `SWITCH_ADMIN_EMAIL` / `SWITCH_ADMIN_PASSWORD`.

## 2. Let Switch run Claude Code agents on this computer

switch-buddy chat (sidebar) → **Connect an AI provider to chat with switch-buddy** → **Claude Code** → **Start with
Claude Code**. This enrols the computer as a *machine* (Console's embedded agent controller). Expected: Console's log
shows "Agent attached to the controller stream"; `list_machines` lists your PC with `claude: ok`.

## 3. Turn on Mattermost

**Admin → SERVER · Status → Mattermost → on**, then **Restart** (not *Reset* — that deletes data). Console pulls
`mattermost/mattermost-team-edition` and runs it in Docker beside the server, creates team `switch`, and connects it with
the callback address set (so permission requests have buttons). In `.env`: `MATTERMOST_URL=http://localhost:<mattermost>`,
`MATTERMOST_TEAM=switch`, `MATTERMOST_CONTAINER=switchdash-local-mattermost-mattermost-1`.

## 4. Accounts, personas and agents (scripted)

```powershell
.venv\Scripts\python scripts\setup_switch_accounts.py   # Switch users asha/sanjay/karan + a registration key per owner
.venv\Scripts\python scripts\create_personas.py         # 6 Mattermost users via `mmctl --local` in the container
.venv\Scripts\python scripts\register_agents.py         # 9 custom agents, each with its owner's key
.venv\Scripts\python scripts\setup_gates.py             # .mcp.json + Claude Code permissions for the gate dirs
.venv\Scripts\python scripts\create_gate_agents.py      # purchase-desk + po-issuer (managed Claude Code agents)
```
`create_gate_agents.py` briefly gives `mandi-intake` the *can manage agents* capability (admin, Gateway API), calls
Switch's `create_agent` twice (provider `claude`, directory `agents/gates/<name>`, instructions = its `CLAUDE.md`, Auto
mode **off**, Bypass **off**) and switches the capability **off** again. By hand instead: Console → Your Agents → + with
the same fields.

## 5. Bootstrap rooms, role and policies

```powershell
.venv\Scripts\python scripts\bootstrap_switch.py
```
Creates the 4 rooms (Switch creates the Mattermost channels; vendor rooms are private), invites the gate agents, defines
the exclusive role `po-issuer`, records participant ids, checks sealed-ness and applies 11 addressing policies through
the Gateway (`PUT /gateway/agents/{id}/addressing-policy`). Expected: every line ✓ and `policy … HTTP 200`.

| Room | Channel | People | Agents |
|---|---|---|---|
| SM-PR-0147 · Seat bolts · Order room | public | rohan, meera, vikram | mandi-intake, mandi-quotes, mandi-auditor, purchase-desk, po-issuer |
| SM-PR-0147 · Deccan Bolt Works · Sealed | private | asha | mandi-negotiator-deccan, deccan-sales, mandi-auditor |
| SM-PR-0147 · Shree Ganesh Fasteners · Sealed | private | sanjay | mandi-negotiator-ganesh, ganesh-sales, mandi-auditor |
| SM-PR-0147 · Apex Precision · Sealed | private | karan | mandi-negotiator-apex, apex-sales, mandi-auditor |

## 6. Check

`.venv\Scripts\python scripts\doctor.py` → everything ✅ except Mandi Core until you start it.

## 7. Assign the role and verify

`po-issuer` assumes the role itself at the start of its first session ("🎭 assumed the `po-issuer` role"); `!roles` then shows **po-issuer** *(exclusive)* — held by PO Issuer (Vikram).

Checks (screenshot these for the README):
- `!list-agents` in the order room and in the Deccan room — different agents, no supplier agent in the order room.
- As **Rohan**: `@po-issuer issue the PO now` → a **visible refusal** (Rohan isn't Vikram).
- As **Asha** in the Deccan room: `!list-agents` shows only that room's agents.

## 8. Run

```powershell
.venv\Scripts\python scripts\doctor.py     # all green
.venv\Scripts\python scripts\run_all.py    # Core + 9 agents, Control Room at http://127.0.0.1:8700
```
Then follow the demo in the README.
