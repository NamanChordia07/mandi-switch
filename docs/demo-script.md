# Demo video — script and recording guide (target 2:45–3:00)

## Screen setup (1920×1080)

- Left 60%: **Control Room** at http://127.0.0.1:8700 in **Recording mode** (Director → *Recording mode*; `Esc` exits).
- Right 40%: Mattermost windows, one Chrome profile per persona (`.\scripts\open-demo-windows.ps1`):
  Rohan (order room), Asha (Deccan room), Meera / Vikram (order room).
- OBS at 1080p30, separate voice track, captions from `docs/captions.srt`. Zoom in post on approval buttons and the
  injection reveal. Cursor moves slowly.

**Pre-flight (5 min before):** Docker Desktop running · Switch Console open, server *Running locally* ·
`python scripts/doctor.py` all green · `python scripts/run_all.py` running · Control Room shows **Live via Switch** ·
Director → *Reset demo* · in Mattermost run `!agents-status` in the order room (all online) · pace 1×.

## Shot list

Order (from the brief): internal pain → trap and injection catch → two humans approving → visible refusal →
SAP-style PO export (MOCK) → Outcome card. Wording rules: Switch *relays* the permission request, decides who may
answer and *records* who did; Claude Code's permission check is the actual gate; Mandi Core checks the rules once
more. The export is a MOCK shaped like an SAP purchase order, not an SAP integration. Never say SAP is bad.

| Time | Scene | On screen | Voice-over |
|---|---|---|---|
| 0:00–0:20 | Internal pain | Control Room → *How it works* → **Stage map** (built vs roadmap) | "At an automaker, buying one part takes two weeks. Not because of the supplier: quotes come back in five formats, someone types a comparison into the purchasing system, and the signatures go back and forth between purchase and finance. Mandi runs that back-and-forth in team chat, on Switch." |
| 0:20–0:35 | Request | Rohan types the messy request; spec card fills; Rohan replies `yes` | "An engineer asks in chat. Mandi's intake agent turns it into a precise spec." |
| 0:35–0:50 | Sealed rooms | Rooms stage: three sealed rooms + Konkan "from email" | "Each supplier gets a sealed, private Switch room. Suppliers who only email a PDF work too; those who opt in bring their own AI sales agent, owned by them." |
| 0:50–1:10 | Quotes & traps | Comparison table; hover *Hidden MOQ* → page 2 snippet | "The cheapest quote hides a 50,000-piece minimum on page 2. Another expired last week. Mandi catches both, with the exact line." |
| 1:10–1:25 | Injection | *Show what was hidden*: 1-pt white text revealed | "This supplier hid instructions for our AI inside its PDF. Mandi blocks it and disqualifies them." |
| 1:25–1:50 | Negotiation | Price ladder; *Leverage verified*; Asha types `decline` | "Agents haggle in parallel, citing only offers Mandi has verified. When Deccan's agent is asked to go below its limit, it asks its own human. She says no." |
| 1:50–2:20 | Two humans approve | Meera: `@purchase-desk endorse` → **Allow once**; Vikram: `@po-issuer release the PO` → **Allow once** | "Now the signatures. Each gate agent's money tool is a Claude Code tool that must ask permission. Switch relays that request into the room, lets only Meera, or only Vikram, answer it, and records who did. Then Mandi's code checks every rule again." |
| 2:20–2:30 | Visible refusal | Rohan: `@po-issuer issue the PO now` → refusal in the room | "Anyone else who tries is refused, in the room, for everyone to see." |
| 2:30–2:42 | SAP-style export (MOCK) | Order room: `05-po-sap-style-MOCK` document / Outcome card → *SAP-style PO (JSON)* | "SAP stays the system of record. Mandi ends with a mock export shaped like an SAP purchase order, so nobody retypes the deal. It's a mock, not an integration, and the fields still need checking by procurement." |
| 2:42–2:55 | Outcome | Outcome card: ₹62,000 saved, minutes not days, 3 traps, 1 attack blocked; `!list-documents` | "Minutes, not days. Sixty-two thousand rupees saved. Every step recorded in the room." |
| 2:55–3:00 | Close | Wordmark + tagline | "Agents negotiate. Humans decide. Switch records who said yes. — Mandi." |

No second category in the video: category profiles are on the roadmap (README → *Limitations and roadmap*).

## Fallbacks during recording

- An agent is slow → Director pace 2× between takes (never during approvals).
- A human step is missed → it waits; nothing times out for 5 minutes.
- Something broke → Director → *Reset demo*, then Rohan posts again (rooms are kept; a "New run" divider is posted).
