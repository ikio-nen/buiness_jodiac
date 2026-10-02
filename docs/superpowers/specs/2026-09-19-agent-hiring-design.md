# Design — Runtime Agent Hiring ("ADD AGENT") for the Agent Office

Status: approved direction · 2026-09-19 · Owner: Zyphr

## Problem

The office roster is a fixed dict of five specialists hardcoded in
`agent_team.py AGENTS`, mirrored by three hardcoded frontend maps
(`BOT_HOME`, `BOT_LOOK`, `ROSTER_META` in `app.js`). Hiring a new
specialist — the thing MDifflin makes a 4-click flow — is impossible
without a code change. The user's search goals change every session,
so the team should be able to grow the specialist each goal needs.

## Scope

In: hire/deactivate specialists at runtime from the office UI; each hire
gets a floor desk, persistent memory, skills, and is reachable via chat.
Out (explicit non-goals): pipeline dispatch changes (the five built-in
legs stay hardcoded to workflows), autonomy/budget guardrails, per-hire
engine choice (all hires use the existing `ai_engine` + heuristic
fallbacks), proactive.py huddle changes, memory-browse UI, and
shareable hire manifests (munder-difflin's import/deep-link format —
a natural follow-up once hiring exists).

## Decisions (confirmed by user)

1. **Depth**: briefable specialist — desk, memory, skills, direct chat;
   pipeline legs untouched.
2. **Engine**: same Gemini engine and fallbacks as built-ins.
3. **Floor**: fixed candidate slots (8), first free wins, position
   persisted so a hire's desk never moves.

## Reference implementation (munder-difflin source, verified)

The user supplied the actual repo (`munder-difflin-main`). Three
patterns are adopted, not approximated:

- **SeatPool** (`src/renderer/src/scene/office/SeatPool.ts`): a
  reservation pool over a fixed ordered seat list — `reserveNext()`
  returns the first unoccupied seat or null, `release()` is idempotent,
  `isReserved()` for checks. Our slot allocator copies this shape
  server-side in `hiring.py` (seats = the 8 slot ids; hire = reserve,
  deactivate = release; the persisted `slot` on each record is the
  claim, rebuilt into the pool on load).
- **AddAgentModal** (`components/AddAgentModal.tsx`): a left sidebar
  section index over one form (NOT a stepped wizard); validation errors
  name and jump to the offending section; id = `slug(name)` +
  base36 timestamp suffix (uniqueness without a collision round-trip);
  characters are a named cast grid — each preset has name, shirt color,
  one-line blurb (`OFFICE_CAST` pattern); a "generate one with AI"
  helper drafts the briefing from name + role. Nothing spawns until the
  human clicks spawn.
- **DESIGN.md token law** for the wizard and every control it adds:
  SNES three-layer panel borders via nested `box-shadow` inset (no
  border-radius, no nested DOM); hard 4px offset shadow only, no blur;
  4px spacing grid; buttons 3D-pressable (top edge bright, bottom dark,
  pressed = translate(0, 2px)); lowercase status labels; never bold,
  no letter-spacing; ≤ 8 colors per screen; on spawn the sprite appears
  at the door and walks to its desk.

## Data model — `agents/hiring.py`

One module owns the hired roster (the contact-seam lesson: one owner for
one actively-changing rule). Persistence:
`agent_output/hired_agents.json`:

```json
{"agents": [{
  "id": "jim", "name": "Jim", "role": "lab-liaison specialist",
  "persona": "…briefing…", "color": "#4e8f7d", "hair": "#2b2b33",
  "skin": "#f0c9a0", "slot": 3, "created_at": "…", "active": true
}]}
```

- `id`: `slug(name)` + base36 timestamp suffix (the AddAgentModal
  `uniqueId` pattern — uniqueness without a collision round-trip),
  still checked against built-in keys. `name` ≤ 30 chars, `role` ≤ 60,
  `persona` 10–2000 chars, colors must be hex.
- Cap: 8 active hires (13 sprites max on the floor with 5 built-ins).
- Deactivate = soft delete (`active: false`); memory files are never
  deleted, matching brain behavior.
- Corrupt file → log, treat as empty, never crash the floor.

## Registry resolution — `agent_team.py`

New functions `get_agent(key)` and `all_agent_keys()` resolve
built-ins + active hires. **Every existing consumer switches to these**:
ask-agent routing in `action_dispatch.py`, the `ask_specialist` tool
schema in `chatbot.py` (agent enum built dynamically at parse time so
Gemini can route to hires), and `/api/agents` in `web/server.py`.
Anything still reading the `AGENTS` dict directly bypasses the roster —
that is the bug class this design removes.

Per-agent memory: `_brain_path`/`_load_brain` already key on the agent
key, so hires get memory for free (`agent_brains/<id>.json`).

## Floor integration

- Server: `/api/agents` gains `home_station` per agent. Built-ins keep
  their fixed stations; hires get `station-hired-<slot>`.
- Slots are allocated by the SeatPool-shaped allocator in `hiring.py`
  (see Reference implementation): reserve on hire, release on
  deactivate, claim rebuilt from the persisted `slot` field on load.
- CSS: 8 predefined slot positions (`station-hired-0…7`) in open floor
  areas, collision-checked against stations/feed. Hired desks reuse the
  existing `.fur-desk` furniture so the room stays one world.
- `app.js`: `BOT_HOME`/`BOT_LOOK`/`ROSTER_META` become derived maps
  built from the `/api/agents` response; init spawns sprites from the
  API roster instead of the hardcoded list, so hires render on reload
  and in `agent_events_replay`. A newly spawned sprite enters at the
  door and walks to its desk (the `spawnTile: entrance` pattern).

## API surface (web/server.py)

- `GET /api/agents` — extended as above (no breaking shape change:
  existing fields untouched).
- `POST /api/agents/hire` — body: name, role, persona, color, hair,
  skin. Returns the hire record + assigned slot; error responses carry
  `{"ok": false, "error": "…", "field": "name"?}` — 409 on id/name
  collision, 400 on validation failure, 400 with `code:
  "floor_full"` at the 8-hire cap.
- `POST /api/agents/{id}/deactivate` — soft delete.
- All three emit event-bus `bot` events ("Jim joins the floor" /
  "Jim departs") so the feed and floor animate the change.

## Wizard UI (vanilla, zero-build)

"＋ agent" button beside "＋ skill" on the roster strip opens the ADD
AGENT modal — an SNES `panel/dialog` (three-layer inset border, hard
4px shadow, corner cuts) with a **left sidebar section index over one
form** (the AddAgentModal pattern, not a stepped wizard):

1. **Identity** — name, role, and the accent color swatch row
   (8 preset hexes + custom hex input).
2. **Character** — a named cast grid (the OFFICE_CAST pattern):
   12+ preset pixel-person looks, each with a shirt color and a one-line
   blurb; picking one sets hair/skin/shirt for the sprite, floor,
   roster, and agent pane.
3. **Briefing** — persona textarea ("what they own / how they work /
   what they never do") plus a **"generate one with AI"** helper that
   drafts the briefing from name + role via the existing Gemini seam
   (heuristic template fallback when no key).

Sidebar entries highlight the section with a validation error and the
form scrolls to it; the spawn button stays enabled until the request
starts. Spawn → POST → sprite walks in from the door to its desk, feed
line fires, roster card appears. Deactivate lives on the agent card in
the agents tab ("part the ways"); sprite walks out the door, desk
frees, memory retained.

All wizard controls follow the DESIGN.md token law: 3D-pressable
buttons (pressed = translate(0, 2px)), no border-radius, no blur
shadows, no bold, no letter-spacing, 4px spacing grid.

## Error handling

- No Gemini key: hires degrade exactly like built-ins (existing
  heuristic path) — no special-casing.
- Validation failures return field-level errors the wizard renders
  inline; nothing spawns on a failed POST.
- Sprite/floor code must tolerate a hire whose station div is missing
  (fall back to brain station, same as today's unknown-agent path).

## Testing

- Unit (`hiring.py`): slug/collision rules, persona cap, corrupt file →
  empty, 8-hire cap, deactivate retains record.
- API (TestClient): hire → appears in `/api/agents` with slot;
  deactivate → gone from roster, memory file intact; collision → error
  shape; cap → refusal.
- Live: hire in the office → sprite walks in; "ask jim …" round-trip;
  reload → sprite still at desk; deactivate → walks out.
- Regression: `node --check app.js`, audit suite 20/20.
