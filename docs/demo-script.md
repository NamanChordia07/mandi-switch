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

| Time | Scene | On screen | Voice-over |
|---|---|---|---|
| 0:00–0:15 | Hook | Title card over the Control Room's *Request* screen | "At an automaker, buying one bolt can take two weeks of emails. We built Mandi to fix that — on Switch." |
| 0:15–0:30 | Request | Rohan types the messy request; Control Room spec card fills; Rohan replies `yes` | "An engineer asks in chat. Mandi's intake agent turns it into a precise spec and asks one question." |
| 0:30–0:45 | Sealed rooms | Rooms stage: three locked rooms; Rooms map shows owners | "Each supplier gets a sealed Switch room, with its own AI sales agent — owned by the supplier, not by us." |
| 0:45–1:05 | Quotes & traps | Comparison table; badges pulse; hover *Hidden MOQ* → page 2 snippet; "Why not the cheapest?" row | "The cheapest quote hides a 50,000-piece minimum on page 2. Another expired last week. Mandi catches both — with the exact line." |
| 1:05–1:25 | Injection | Click *Show what was hidden*: the PDF with 1-pt white text revealed; Three locks panel | "This supplier hid instructions for our AI inside its PDF. Mandi blocks it, closes their room — and even a fooled agent couldn't issue a PO." |
| 1:25–2:05 | Negotiation | Price ladder converging; *Leverage verified* chip; Asha's window: `🔒 Approval needed` → she types `decline`; chip *Asked Asha — declined*; quick Director red-team *fake ₹33.00* → *Blocked before reaching the room* | "Agents haggle in parallel, citing only offers Mandi has verified — never naming who. When Deccan's agent is asked to go below its limit, it must ask its own human. She says no." |
| 2:05–2:35 | Approvals | Meera: `@purchase-desk endorse` → Switch request with buttons → **Allow once**; Vikram: `@po-issuer release the PO` → **Allow once**; `!roles` | "The money needs two humans. Each approves in Switch, on an agent that listens only to them. Only one agent can ever issue a PO." |
| 2:35–2:50 | Outcome | PO PDF in the room; Outcome card: ₹62,000 saved, minutes not days, 3 traps, 1 attack blocked; `!list-documents` | "Minutes, not days. Sixty-two thousand rupees saved. Every step recorded in the room." |
| 2:50–3:00 | Close | Wordmark + tagline | "Agents negotiate. Humans decide. Switch records who said yes. — Mandi." |

## Fallbacks during recording

- An agent is slow → Director pace 2× between takes (never during approvals).
- A human step is missed → it waits; nothing times out for 5 minutes.
- Something broke → Director → *Reset demo*, then Rohan posts again (rooms are kept; a "New run" divider is posted).
