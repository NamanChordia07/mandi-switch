# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `doctor`: Switch server ✗ | Switch Console not running, or wrong `SWITCH_BASE_URL` | Open Switch Console; copy the server address from its Home page into `.env`; `curl <url>/health` must return 200 |
| Console says it can't reach Docker | Docker Desktop not started | Start Docker Desktop, wait for *Engine running*, start the server again (only the bundled Mattermost needs Docker) |
| Agent replies "can't act on it" (visible refusal) | Its addressing policy doesn't admit the sender | Expected for wrong senders (that's Lock 1). For the right sender: rerun `scripts/bootstrap_switch.py` (policies) and check the persona appears in `secrets/switch-ids.local.json → people` |
| Meera taps Allow and nothing happens | Mattermost can't reach Switch's callback port, or Meera isn't admitted by `purchase-desk`'s policy | Reply `yes` to the request instead (works without buttons); check the policy; see Switch troubleshooting "Your answer to a request did nothing" |
| No permission request appears for `endorse_order` | Claude Code ran the tool without asking (auto mode) | Ensure `agents/gates/*/.claude/settings.json` exists (`scripts/setup_gates.py`) with the tool on the **ask** list; or turn **Auto mode OFF** on the agent; Stop the session in Console and address the agent again |
| Gate agent says it has no Mandi tools | Project MCP server not loaded | Run `scripts/setup_gates.py`; Directory of the agent must be `agents/gates/<name>`; Stop the session and retry |
| Custom agent exits "No API key for agent …" | Not registered | `python scripts/register_agents.py` |
| Agent log shows `evicted: taken_over` and stops | Another process opened the same agent connection | Only one `run_all.py` at a time; delete `.state/<agent>.json` if you copied state between machines |
| Quote never parsed | Quotes agent not running or Core down | `logs/mandi-quotes.log`; `python scripts/doctor.py` |
| Negotiation stalls | Vendor agent not running, or its reply had no `Offer:` line | `logs/<vendor>-sales.log`; restart `run_all.py` (state is in Core) |
| LLM errors / budget | Key missing, rate limit, or call cap reached | Agents fall back to deterministic templates automatically; see `logs/llm-usage.jsonl`; raise `MANDI_LLM_MAX_CALLS` or set `MANDI_OFFLINE_LLM=1` |
| `UnicodeEncodeError` on Windows console | cp1252 console | Use `scripts/run_all.ps1` (sets `PYTHONUTF8=1`) |
| Control Room "Switch not connected" | Auditor not connected | `logs/mandi-auditor.log`; the dot turns green when the auditor's `scope=all` connection is live |
| Start a fresh run | — | Control Room → Director → *Reset demo* (keeps Switch rooms; fresh Core database) |
