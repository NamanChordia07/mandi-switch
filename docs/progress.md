# Build progress (resume point)

If the Claude session restarts, run `claude -c` in this folder and say "continue from docs/progress.md".
Deadline: Sat 7 Nov 2026, 11:59 PM IST (target submit 9 PM).

## Status (6 Nov, 15:37 IST)
- [x] Phase 0 — recon, environment, scaffold
- [x] Phase 1 — Switch live: Console 0.40.1 native server + Mattermost (Docker); WS + ops verified
- [x] Phase 2 — Mandi Core (58 tests green)
- [x] Phase 3 — seed PDFs; Switch accounts (asha/sanjay/karan) + per-owner registration keys; 6 Mattermost personas
- [x] Phase 4 — parsing + injection (evidence-checked LLM extraction, gpt-4o-mini)
- [x] Phase 5 — 9 custom agents registered + 2 Claude Code gate agents (managed) + 4 rooms + role + 11 policies
- [x] Phase 6 — negotiation engine + vendor-side approval
- [x] **Phase 7 — FULL LIVE E2E on real Switch + Mattermost**, human approvals clicked by Naman:
      request → spec (9 s) → 4 quotes (3 as Switch attachments) → Apex injection blocked → parallel negotiation →
      Asha declined → award Deccan ₹36.40 (~2 min) → Meera Allow once → Vikram Allow once → PO-SM-2026-0147 PDF in room
      → Outcome card → 04-audit-log; audit chain verified (63 events); LLM spend $0.0019 for the whole run.
      Also verified: visible refusal (Rohan → @po-issuer), `!roles` exclusive role, `!list-documents`.
- [x] Phase 8 — Control Room UI (live screenshots in docs/images/live-*.png, Mattermost in mm-*.png)
- [~] Phase 9 — doctor/run_all/simulate/live_rehearsal/fake-e2e done; clean-clone test still to do
- [x] Phase 10 — README, architecture, manual-setup (verified path), troubleshooting, demo script, captions, blog, social
- [ ] Phase 11 — stretch (optional)
- [ ] Phase 12 — final judge review + submission (video recording by Naman/Divya)

## Live environment (this machine)
- Switch API http://127.0.0.1:63663 · Mattermost http://localhost:63664 (team `switch`) · Mandi Core/Control Room http://127.0.0.1:8700
- Persona logins: secrets/demo-users.local.json · agent keys: secrets/agent-keys.local.json · ids: secrets/switch-ids.local.json
- Switch Console was relaunched with `--remote-debugging-port=9333` to configure it via its own UI (CDP/Playwright).
- Start everything: `python scripts/run_all.py` (Switch itself runs in Switch Console; keep Docker Desktop running)
- New run: Control Room → Director → Reset (or POST /director/reset), then Rohan posts in the order room.

## Decisions since start
- LLM: OpenAI gpt-4o-mini (no Anthropic API key); cache + per-process cap + usage log.
- Gate agents answer exactly one human each, no agents, owner excluded → only Meera/Vikram can approve.
- Automation never answers a Switch permission request (Claude Code's classifier also refuses it) — humans click.
