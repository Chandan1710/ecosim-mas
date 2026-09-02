# EcoSim-MAS — Production Architecture & Build Specification

**Team Heisenberg · RNSIT Bengaluru · BIS685 · Guide: Dr. Sunitha K**
**Target build environment: Google Antigravity / OpenAI Codex (agentic coding tools)**

This spec is written to be handed directly to an agentic coding tool, module by module. Each section below maps to one buildable subsystem. Where a decision was open in your original prompt, this document makes the call and states why — no vague trade-off tables, no "you could also…".

---

## 0. Where this file lives, and how to start

**Put this file in the repo itself**, at `docs/ARCHITECTURE.md` (or repo root), and commit it before you write any code. Two reasons: an agentic tool reads it as live context whenever it opens the repo, and you get version history on the spec itself — when a decision changes (like the solo-vs-team rework in §13), that's a diffable commit, not a lost Slack message. This repo copy is canonical; don't maintain a second copy elsewhere that can drift out of sync.

**Day one, before any API keys:**
1. `git init`, create the top-level folders (`backend/`, `frontend/`, `docs/`), commit `docs/ARCHITECTURE.md`.
2. Add a `.env.example` with every key name this spec references (`GROQ_API_KEY`, `NEWSAPI_KEY`, etc.) but no real values — this documents what you'll eventually need without blocking you now.
3. Open the repo in Antigravity and start on §12's module 1 — it needs no live keys, just fixture data.
4. Work top to bottom through §12, one module per session, per the workflow in §13.

---

## 1. Why this isn't "a chatbot with a dashboard"

The four things you asked for that separate this from a typical student MAS project:

1. **LLMs generate *understanding*, not *decisions*.** The Groq/Ollama models translate a real-world event into a structured causal chain and an initial numeric feature vector. They never decide what an agent does tick-by-tick — that's too slow, too expensive, and too easy to fake with a good prompt. Decisions come from a **trained reinforcement-learning policy** per agent archetype.
2. **Outputs come from simulation logs, not formulas.** The Failure Frontier, Inequality Index, and Risk Scores are predictions from supervised ML models (gradient-boosted trees + a temporal model) trained on thousands of simulated agent-trajectories and validated against real historical Indian macro events. There is no `if inflation > 6: risk = "high"` anywhere in the codebase.
3. **Agents perceive each other, not just the environment.** This is implemented as a proper multi-agent environment (`PettingZoo` `ParallelEnv`) with a shared event bus, not 10 independent LLM calls run in a loop.
4. **The system asks before it assumes.** A dedicated Scenario Parser stage runs before any simulation, surfaces its understanding as structured bullet points, and blocks on ambiguity instead of silently guessing.

---

## 2. Tech stack — final decisions

| Concern | Choice | Why |
|---|---|---|
| API layer | **FastAPI** (Python 3.12, async) | You already know it; async fits streaming simulation ticks over WebSocket |
| Simulation engine | **PettingZoo `ParallelEnv` + Ray RLlib (PPO)** | This *is* the industry-standard way to build "real agents that learn from reward/punishment and interact" — it's not a metaphor, it's literally what MARL frameworks exist for |
| Task orchestration | **Celery + Redis** for scraping/LLM jobs; **Ray** for simulation/training jobs | Keep I/O-bound jobs (scraping, API calls) separate from compute-bound jobs (RL training/rollout) |
| Relational data | **PostgreSQL** | Personas, scenarios, users, run metadata |
| Time-series data | **TimescaleDB** | Macro variables (repo rate, CPI, fuel price) — you already have this in your stack |
| Agent short-term memory | **Redis** (per-agent hash, TTL'd per simulation run) | Working memory: current budget, last 3 shocks perceived, current action |
| Agent long-term/episodic memory | **Qdrant** (vector DB) | Each agent embeds and stores (event, decision, outcome) tuples; retrieves the k most similar past situations before acting — this is what makes memory *usable*, not just logged |
| Event bus (agent perception) | **Redis Streams** now, **documented Kafka migration path** for scale | Redis Streams is sufficient at 10 agents × N scenarios; note in `/docs/scaling.md` how to swap in Kafka without touching agent code |
| Object storage | **MinIO (S3-compatible)** | Trained model artifacts, generated reports (PPTX/PDF), scenario replay logs |
| Frontend | **React + Vite**, WebSocket client, Recharts for time-series, D3 for the causal chain graph | Matches your existing stack |
| Deployment | **Docker Compose** (dev) → **Kubernetes manifests** (prod path), **GitHub Actions** CI | Gives you a real "scalable industry grade" story without over-building for a student project |

---

## 2.1 Data persistence in local development

This is separate from any AI assistant's memory — it's about your own project's data surviving a restart or browser refresh.

**Persists automatically only if you mount a Docker volume** — without one, data lives in the container's writable layer and is lost the moment the container is removed:
- **PostgreSQL** — personas, scenarios, run metadata
- **TimescaleDB** — macro time-series (repo rate, CPI, fuel price)
- **Qdrant** — agents' long-term episodic memory
- **MinIO** — trained model artifacts, generated reports

**Intentionally ephemeral, by design:** **Redis** holds agent *working* memory (current tick's budget state, last 3 perceived events) scoped to a single simulation run. It should reset between fresh runs — don't persist it unless you have a specific reason to.

**Frontend refresh** is unrelated to any of this — it only clears React's in-memory `useState`/`useReducer` state. As long as the dashboard fetches from FastAPI on load rather than holding data purely client-side, a browser refresh never touches backend data.

Minimum `docker-compose.yml` pattern to get this right from the start:

```yaml
services:
  postgres:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data
  timescaledb:
    image: timescale/timescaledb:latest-pg16
    volumes:
      - timescale_data:/var/lib/postgresql/data
  qdrant:
    image: qdrant/qdrant
    volumes:
      - qdrant_data:/qdrant/storage
  minio:
    image: minio/minio
    volumes:
      - minio_data:/data

volumes:
  postgres_data:
  timescale_data:
  qdrant_data:
  minio_data:
```

With named volumes in place, only an explicit `docker compose down -v` or manual volume deletion wipes data — a normal `down`/`up` cycle, a machine restart, or a frontend refresh will not.

---

## 3. Data ingestion layer

### 3.1 Sources (decided, not proposed)

- **GDELT Project** (free, real-time, already event-coded with actors/themes/tone) — this is your *primary* global-event feed. It solves "all economic events happening across the world" better than any news API because GDELT already structures events, it doesn't just give you article text.
- **NewsAPI.org / Bing News Search API** — supplies full article text for the events GDELT flags, so the causal-chain LLM has real prose to reason over, not just an event code.
- **RBI Handbook of Statistics / DBIE** — repo rate, CPI inflation, fuel price indices. RBI does not expose a clean public REST API; treat this as a **scheduled scraper/CSV-ingestion job** (weekly), not a live API call. Build this as an isolated module (`ingestion/rbi_scraper.py`) so it can be swapped for a paid data vendor later without touching downstream code.
- **Alpha Vantage News & Sentiment (free tier)** — optional third signal for market tone, useful for the Inequality Index model's feature set.

### 3.2 Pipeline

```
Scheduled job (Celery beat, every 15 min for news, daily for RBI)
  → fetch GDELT export + NewsAPI articles
  → dedupe against Postgres event table
  → store raw event + article text in Postgres
  → push event_id onto Redis Streams "new_events" topic
  → Causal Chain Engine subscribes and picks it up
```

---

## 4. Temporal & spatial grounding (the "LLM hallucinates dates" problem)

You are right to worry about this — LLMs are frequently wrong about "today's" date and can silently drift to their training cutoff. Two-layer fix, exactly as you asked:

**Layer 1 — automatic, every single call.** Never rely on conversation memory or a system prompt set once. A `grounding.py` middleware builds a fresh block and prepends it to *every* LLM call (Groq and Ollama), sourced from:
- Server UTC clock (NTP-synced container, not client clock)
- IP-based reverse geocoding for a default location, overridable per request

**Layer 2 — explicit user override, shown in the frontend.** A small "Simulation context" panel on the scenario intake screen with **Date**, **Location** fields, pre-filled from Layer 1 but editable. Whatever the user sets is stored on the scenario record and takes precedence over the auto-detected value for that run. This directly answers your ask: *"if that would still be inaccurate, I want the client himself to enter the day, date and location."*

The exact grounding block text is in §8.1 below — it goes at the top of every prompt, not just the causal chain one.

---

## 5. Scenario Parser — the ambiguity-handling stage

Before any causal chain or simulation runs, the user's scenario prompt goes through a dedicated parser call (§8.2). It returns:
- A structured list of what it understood (macro conditions, region, time horizon, affected sectors)
- A list of ambiguous or missing fields, each phrased as a direct question

**Frontend behaviour:** render the "understood" bullets and any questions as a confirmation card. The **Run Simulation** button stays disabled until every question is answered or explicitly skipped by the user. This is a hard gate, not a courtesy — the parser is instructed never to guess (see prompt).

---

## 6. Causal chain engine

- **Primary: Groq**, model `openai/gpt-oss-120b` (Groq deprecated the `llama-3.3-70b-versatile` line — don't build against it). Use Groq's `json_schema` structured-output mode so you get guaranteed-parseable chains, not regex-scraped text.
- **Fallback: Ollama**, running locally (`qwen2.5:14b` or `llama3.1:8b` depending on your hardware — pick based on your GPU/CPU budget, both handle structured JSON reasonably with a schema reminder in-prompt since Ollama's structured-output support is weaker than Groq's).
- **Fallback trigger:** Groq timeout (>15s), rate-limit response, or malformed JSON after one retry. Log every fallback event — this becomes a reliability metric worth reporting in your review.
- **Chain length:** enforced 10–15 nodes via the schema (`minItems: 10, maxItems: 15`), each node carries `magnitude: major | moderate | minor`, ranked in generation order from majorly-impacting to minor.

Exact prompt in §8.3.

---

## 7. Agent layer — making agents "real"

This is the part most student projects fake with a persona string. Here's the honest way to build what you described:

### 7.1 Environment

- Define `EcoSimEnv(PettingZoo.ParallelEnv)` with 10 agents, one per persona archetype.
- **Observation space** per agent: own budget state, own risk/literacy/bias traits, last N perceived macro shocks, last N peer actions visible on the shared event bus (partial observability — agents don't see everyone's private state, only public actions, which is realistic).
- **Action space**: `{Spend, Save, Default}` × a continuous magnitude (Box space), so it's not just three buttons — it's "save 12% more this cycle."
- **Loop**, exactly matching what you described:
  `Agent observes state → policy selects action → environment applies budget change → macro state updates → other agents perceive the public parts of that change on the next tick → new observations → repeat`. This *is* emergent behaviour: nothing scripts "when income agent X defaults, agent Y panics" — it emerges from Y's policy having learned that peer defaults correlate with tightening credit conditions.

### 7.2 Cognition — hybrid, not "LLM roleplay"

- **Perception/translation (LLM):** when a causal-chain node reaches the agent layer, a lightweight call (Semantic-to-Numerical Mapper, §8.4) converts the qualitative node into an initial numeric delta (e.g. "fuel price shock, major" → `discretionary_spend_delta: -0.15, savings_rate_delta: -0.08`) that seeds the environment's macro state. This runs once per event, not once per agent per tick.
- **Action selection (RL policy):** each of the 10 archetypes has its **own trained PPO policy** (Ray RLlib `MultiAgentPPO`), trained offline against thousands of synthetic + historical macro trajectories before deployment. At inference time (a live scenario run), the trained policy — not an LLM — picks the action every tick. This is fast, reproducible, and genuinely "learned from reward/punishment" rather than prompted.
- **Reward function** (transparent, inspectable — this is fine to hardcode, it's the *behaviour policy* that must be learned, not the reward): a weighted combination of `liquidity buffer maintained`, `essential spending met`, `debt-to-income delta`, tuned per archetype (a "Frugal Senior" is rewarded more for capital preservation, an "Aggressive Student" more for growth-seeking behaviour even under some risk).

### 7.3 Memory

- **Working memory (Redis):** current tick's budget state, last 3 perceived events — fast, ephemeral, scoped to the current simulation run.
- **Episodic memory (Qdrant):** at the end of every simulation run, each agent's (event, action, outcome) tuples are embedded and stored. On a *new* scenario, before the policy acts, the agent retrieves its k-nearest past situations — this is real continuous learning across runs, not just within one simulation.

### 7.4 2D visualization & world model

**This section replaces the earlier 3D approach.** After extensive attempts, the 3D pipeline (Mixamo → Blender/FBX2glTF → React Three Fiber SkinnedMesh instancing) hit a persistent, unresolved rendering bug across multiple debugging sessions and models — the skinned mesh would not render correctly when instanced ten times simultaneously, despite the underlying asset and every individual piece (geometry, skeleton, materials, WebSocket data pipeline) independently checking out as correct. Rather than continue sinking time into a 3D skeletal-animation bug class, the pivot below is the pragmatic, still-buildable version — closer in spirit to *Generative Agents: Interactive Simulacra of Human Behavior* (Park et al., UIST 2023)'s own 2D tile-based renderer than to a 3D scene, and it eliminates the entire bug class rather than working around it.

- **Top-down 2D scene, rendered on HTML5 Canvas** (or a lightweight 2D library if useful later — PixiJS — but plain Canvas 2D is the default: zero new heavy dependencies, no skeletal animation, nothing that can fail the way SkinnedMesh instancing did). Added to the existing React + Vite frontend.
- **Six fixed zone tiles** — Home, Workplace, Mall, Café, Theater, Grocery — simple flat-colored rectangles/rounded-rects on the canvas, each labelled, laid out in roughly the same relative arrangement as the old 3D scene (positions can be reused as 2D x/y coordinates directly).
- **Agents share ONE simple visual representation** — a small flat-colored circle or dot (no mesh, no skeleton, no per-persona visual distinction, same reasoning as before: different looks would wrongly imply something about the *persona's appearance* rather than the policy behind it), labelled with the persona's name. Distinguish an agent's current action via a simple visual state, not animation frames: e.g. a subtle color/border change or icon swap for Spend / Save / Default, rather than a walk-cycle. Movement between zones can be a straightforward tween of the (x, y) position over ~1s — no animation clips, no bone transforms, nothing that can silently fail to render.
- **Needs state decides *which* zone; the RL policy still decides *how much* gets spent there.** Unchanged from before — the needs-state logic (§9.3) is independent of the rendering layer and carries over exactly as designed.
- **Module 10 (agent_base.glb, the Mixamo asset)** is deferred, not deleted — the file and the pipeline that built it remain in the repo as a documented artifact, and could be revisited later (e.g. for a stretch-goal 3D mode) once the 2D version is solid and demoable. It is not part of the critical path anymore.
### 7.5 Peer influence — how agents actually affect each other

You referenced *Generative Agents: Interactive Simulacra of Human Behavior* (Park et al., UIST 2023 — already cited in your literature survey, Cluster 1 item 2). Full parity with that paper — importance-weighted memory retrieval, hierarchical daily-plan reflection, free-form emergent dialogue between agents — is a research system built by a team over months, not a bolt-on, and would be a genuine downgrade for what this project needs: their architecture is built for improvisational social dialogue via an LLM call every tick, not learned, convergent financial decision-making, and it doesn't do economic shock propagation, RL training, or any of what modules 1-9 already provide. What's genuinely buildable, and gets you the thing you actually asked for — an agent's decision measurably nudged by a peer's behaviour, mood-dependent — is the bounded peer-influence layer already designed here, which stays exactly the same regardless of whether the world is rendered in 2D or 3D:

- **Co-location trigger, not constant chatter.** Peer influence only fires when two or more agents are assigned to the *same zone on the same tick* (their zone choice already comes from the needs-state layer, §9.3) — this is naturally rare enough to be meaningful, not a background hum on every tick.
- **Default mechanism: a cheap, rule-based needs-state nudge — not an LLM call.** When agents co-locate, each one's needs-state (`budget_anxiety`, `discretionary_appetite`) is nudged based on what the *other* agent's most recent action was — seeing a peer who just Defaulted nudges `budget_anxiety` up; seeing a peer who just Spent freely at the Mall nudges `discretionary_appetite` up. This is exactly the "poor agent whose friends buy expensive coffee, influenced or not depending on mood" scenario — it's transparent and inspectable (same philosophy as the reward function in §7.2) rather than another opaque model. Tune the nudge magnitude per persona's `financial_literacy` — more literate agents should be less swayed by a single peer's behaviour, which is realistic and also keeps the effect bounded rather than runaway.
- **Optional narrative layer: extend the Agent Narrator (§8.5) to co-located pairs.** When two agents share a zone, one additional LLM call (not per-agent, per *pair*, so it stays rare) can generate a one-line exchange — "Priya mentions her rent's due; Rahul decides to skip his coffee run too." This is flavor text shown as a subtle text cue near the two figures on the 2D map — it does not itself drive behaviour (the rule-based nudge already did that); it just narrates what the nudge looked like. Prompt in §8.6.
- **This already partially flows through episodic memory (§7.3) for free.** A peer's action, once it nudges an agent's needs-state, becomes part of that agent's own event context for the tick — which gets stored via `store_episode()` (module 7) same as any other event. So a past peer interaction is retrievable later as episodic memory without any new infrastructure — the memory system you already built supports this naturally.
- **What this deliberately does NOT do:** agents don't hold multi-turn conversations, don't form or query a "who do I trust" model of other agents, and don't propagate influence transitively beyond the tick it happens on (no simulated rumor-spreading network). Those are the pieces that would make this a research-paper-scale system rather than a semester project — name them as explicit future work in your report rather than attempting them.

---

## 8. Prompts

Use these verbatim as your starting system prompts. All five assume they're called through a thin orchestration layer that injects the grounding block first.

### 8.1 Grounding block (prepended to every LLM call, Groq and Ollama alike)

```
SYSTEM CONTEXT — DO NOT OVERRIDE
Current date: {server_date_or_user_override}  (ISO 8601)
Current location context: {location_or_user_override}
This date and location are authoritative for this entire task. Do not use your
training cutoff, do not infer a different date from context, and do not assume
a different country or region unless explicitly told to. If the scenario asks
about anything that would require knowledge past {server_date_or_user_override},
say so explicitly rather than guessing.
```

### 8.2 Scenario Parser (ambiguity detection)

```
You are the Scenario Parser for EcoSim-MAS, an economic shock simulation system.
Your only job is to read the user's scenario description and extract a structured
understanding of it. You do NOT generate a causal chain and you do NOT run any
simulation.

Return JSON with exactly these fields:
{
  "understood": [ "short bullet describing a concrete thing you understood" ],
  "region": "string or null if not specified",
  "time_horizon_months": "integer or null if not specified",
  "primary_event": "one-sentence description of the triggering event",
  "affected_sectors": [ "sector names you can confidently infer" ],
  "ambiguous_or_missing": [
    { "field": "what is unclear", "question": "a direct question to ask the user" }
  ]
}

Rules:
- Never invent a region, time horizon, or magnitude the user did not state or
  strongly imply. If it is not there, put it in ambiguous_or_missing instead of
  guessing a default.
- "ambiguous_or_missing" should be empty only if the scenario is genuinely
  unambiguous — do not leave it empty just to seem helpful.
- Keep each question in ambiguous_or_missing short and answerable in one line.
- Do not include any text outside the JSON object.
```

### 8.3 Causal Chain Generator

```
You are the Causal Chain Engine for EcoSim-MAS. Given a primary economic event
and current macro context, produce a ranked causal chain of 10 to 15 downstream
consequences, ordered from the most economically significant to the most minor.

Ground every step in real economic mechanisms (supply/demand, cost pass-through,
policy response, behavioural response) — do not invent effects with no plausible
transmission mechanism.

Return JSON matching this schema:
{
  "chain": [
    {
      "node_id": "integer, 1-indexed, in causal order",
      "description": "one clear sentence describing this consequence",
      "magnitude": "major | moderate | minor",
      "category": "prices | employment | credit | policy | consumer_behaviour | trade | other",
      "depends_on": [ "node_id(s) this follows from, or [] if it follows directly from the primary event" ],
      "confidence": "float 0-1, your confidence this consequence actually follows"
    }
  ]
}

Constraints:
- Exactly 10 to 15 nodes.
- node_id 1 must follow directly from the primary event.
- Order nodes from majorly-impacting to minor — do not cluster all "major" nodes
  arbitrarily; order should reflect the actual causal cascade.
- If you are not confident about a downstream effect, include it with a lower
  confidence score rather than omitting it — the simulation layer will weight
  by confidence.
- Do not include any text outside the JSON object.
```

### 8.4 Semantic-to-Numerical Mapper (per causal-chain node → agent-layer seed values)

```
You are the Semantic-to-Numerical Mapper for EcoSim-MAS. You convert one causal
chain node into numeric deltas that seed the multi-agent simulation's macro
state. You do not decide what any individual agent does — you only translate
a qualitative event into a starting quantitative signal.

Given a causal chain node and the current macro state, return JSON:
{
  "node_id": "matches the input node_id",
  "deltas": {
    "discretionary_spend_pct": "float, e.g. -0.15 for a 15% decrease",
    "savings_rate_pct": "float",
    "essential_cost_index_pct": "float",
    "credit_availability_pct": "float"
  },
  "rationale": "one sentence explaining the mapping"
}

Rules:
- Deltas must be directionally consistent with the node's description and
  magnitude (major nodes should generally produce larger-magnitude deltas than
  minor nodes, but use judgement — a "major" policy announcement can have a
  smaller immediate numeric effect than a "moderate" supply shock).
- These deltas seed the environment state only. They are not final outcomes —
  the agent policies will react to them during simulation.
- Do not include any text outside the JSON object.
```

### 8.5 Agent Narrator (flavor text for the 3D scene)

```
You are the Agent Narrator for EcoSim-MAS. Given one agent's persona, the
action its policy just took (Spend/Save/Default and magnitude), its current
needs state, and the macro event driving this tick, write exactly one short
sentence (under 20 words) in the third person explaining why it made this
choice.

Do not invent facts about the agent's life that were not in its persona or
state (no fabricated family members, jobs, or backstory beyond what's given).
Do not use exclamation marks or dramatic language — this is a financial
simulation, not a story.

Return JSON:
{ "agent_id": "...", "rationale": "one sentence, under 20 words" }
```

### 8.6 Peer Interaction Narrator (co-located agent pairs, §7.5)

```
You are the Peer Interaction Narrator for EcoSim-MAS. Two agents are
co-located in the same zone this tick. Given both agents' personas, their
most recent actions, and the needs-state nudge that just occurred between
them, write exactly one short sentence (under 25 words) narrating what
their exchange looked like, in third person.

This is flavor text for a 3D scene, not a driver of behaviour — the
numeric nudge has already been applied. Do not invent facts about either
agent's life beyond their given persona and state. Do not use exclamation
marks or dramatic language.

Return JSON:
{ "agent_a_id": "...", "agent_b_id": "...", "narration": "one sentence, under 25 words" }
```

---

## 9. Build briefs — paste directly into Antigravity or Codex

### 9.1 2D world scene (Canvas, top-down, sprite-based)

```
Build a zone-based 2D scene for EcoSim-MAS using plain HTML5 Canvas
(via a React component wrapping a <canvas> ref) inside the existing
React + Vite frontend. This replaces the earlier 3D/React-Three-Fiber
approach after it hit a persistent, unresolved skinned-mesh rendering
bug — no Three.js dependency needed for this scene.

Asset source (see §9.2 for the exact download/setup): Kenney.nl's
"Roguelike/RPG Pack" (tiles) and "Roguelike Characters" pack (sprite
sheets) — both CC0 (public domain, no attribution required, safe for
a public repository), a substantial step up in visual quality from
flat shapes while remaining simple and consistent with a minimal
aesthetic (these are clean, flat-shaded pixel-art tiles, not painterly
or gradient-heavy).

Requirements:
- Six fixed zone tiles on a flat 2D canvas: Home, Workplace, Mall,
  Café, Theater, Grocery. Each zone is represented by an appropriate
  tile/building sprite from the Kenney tileset (e.g. a house tile for
  Home, a storefront tile for Mall, etc. — pick the closest visual
  match available in the pack), placed at a fixed (x, y) coordinate,
  spaced clearly apart, with a text label above or below it. Reuse the
  same relative layout the old 3D scene used.
- Agents are ONE shared static character sprite (composed from Kenney's
  Roguelike Characters modular parts — body + one outfit combination,
  a single fixed pose, not a walk-cycle animation sheet), same
  reasoning as before — agents are deliberately NOT visually distinct
  from each other by sprite choice, only by a name label drawn as text
  above the sprite. Pick one clean, neutral-looking composed character
  and use it for all 10 agent instances.
- Movement animation: since this asset is a single static pose (not a
  multi-frame walk cycle), animate movement via smooth position
  tweening only — the sprite visibly glides between zones over ~1
  second using requestAnimationFrame, rather than a frame-swapped walk
  cycle. This is consistent with the minimal aesthetic already in use
  elsewhere and avoids overpromising animation the asset doesn't
  provide. (Optional, low-effort polish if time allows: a subtle 1-2px
  vertical bob while moving, to read as motion without needing real
  walk frames.)
- Each agent's position updates on every simulation tick received over
  the WebSocket connection (agent_actions[agent_id].action_type,
  zone[agent_id] from the tick payload — unchanged by this rendering
  swap). Tween the sprite's (x, y) toward its new zone's tile
  coordinates over ~1 second; hold still once arrived.
- Represent action state via a small, subtle visual cue layered on top
  of the sprite (not a sprite swap) — e.g. a thin colored ring/badge
  in the corner of the sprite's bounding box: accent blue for Spend,
  muted green for Save, muted red/grey for Defeated agents (who also
  stop animating and freeze on their last frame at their last
  position, since the agent is terminated in the environment on this
  tick).
- Camera/viewport: fixed, no pan/zoom needed for six tiles in a small
  area — render the whole map in the canvas at a fixed scale.
- Colors/style: keep everything else (background, UI chrome, labels)
  matching the existing flat, no-gradient design system (§9.4) — the
  sprites are the one place pixel-art detail is allowed, everything
  around them stays minimal.
- Performance target: this should run trivially well — 10 animated
  sprites + 6 tile sprites redrawn every frame is negligible load on
  Canvas 2D, no special optimization needed.
- Do not model interiors, roads, or anything beyond the six zone tiles
  and ten agent sprites — same minimal-diorama philosophy as before,
  just with real character/tile art now.
```

### 9.2 Sprite asset setup (Kenney.nl, CC0 — replaces the Mixamo pipeline)

```
Set up the sprite assets for EcoSim-MAS's 2D scene. Both packs below
are CC0 (public domain) — safe to commit into a public repository with
no attribution requirement, unlike the earlier Mixamo-based 3D
pipeline this replaces.

1. Download Kenney's "Roguelike/RPG Pack" from kenney.nl/assets
   (search "Roguelike RPG Pack") for the zone tile sprites, and
   Kenney's "Roguelike Characters" pack (search "Roguelike Characters")
   for the agent sprite sheet. Both are free direct downloads, no
   account needed.
2. Extract the specific tile images needed for the six zones (house,
   storefront/shop, office/building, restaurant/café, theater/
   entertainment venue, market/grocery — pick the closest matches
   available in the pack) and ONE character sprite sheet for agents.
3. Store them at frontend/public/sprites/tiles/ and
   frontend/public/sprites/agent.png (or .json + spritesheet if the
   pack provides an atlas format — either is fine, whichever is
   simpler to slice frames from in Canvas 2D drawImage calls).
4. frontend/public/models/agents/agent_base.glb and
   scripts/convert_agent.py (the old Mixamo pipeline output) remain in
   the repo as a deferred artifact per §7.4, unused by the running app.
5. Document the source and license in a short
   frontend/public/sprites/CREDITS.md — even though CC0 doesn't
   require attribution, crediting Kenney is good practice and costs
   nothing.

Implement the action_type → visual state mapping directly in the
Canvas rendering code (§9.1):
  - action_type 0 (Spend) → tween toward the zone, accent-blue corner
    badge on arrival
  - action_type 1 (Save) → tween toward Home, muted-green corner badge
    on arrival
  - action_type 2 (Default) → muted-red/grey corner badge, freeze in
    place and stop moving — the agent is terminated in the environment
    on this tick
When no action has changed an agent's state this tick, keep whatever
visual state it currently has rather than resetting it every frame.
```

### 9.3 Agent needs-state and zone selection

```
Implement a lightweight needs-state layer between the RL policy's
Spend/Save/Default decision and the scene's zone assignment. This is a
rule-based state machine — not an LLM call and not a second RL policy —
keep it simple and inspectable. This logic is entirely independent of
the 2D/3D rendering choice and does not change based on §9.1/§9.2.

Each agent has three needs, updated once per simulation tick, range 0-1:
- budget_anxiety: increases when the RL policy's chosen action magnitude
  drops available liquidity below a persona-specific threshold; decreases
  slowly each tick the agent isn't stressed.
- essential_pressure: driven directly by the causal chain's
  essential_cost_index_pct delta for the current event.
- discretionary_appetite: inverse of budget_anxiety, modulated by the
  persona's spending_bias trait.

Zone selection rule (deterministic given the needs state, small tie-break
only):
- essential_pressure > 0.7 → Grocery
- budget_anxiety > 0.7 → Home (agent pulls back, no discretionary trips)
- discretionary_appetite > 0.6 and budget_anxiety < 0.4 → Mall, Café, or
  Theater (rotate based on which the agent hasn't visited in the last 3
  ticks, to avoid repetitive-looking movement)
- default → Workplace during simulated "day" ticks, Home during simulated
  "night" ticks

Expose the needs state and resulting zone choice on the WebSocket tick
payload so the frontend can render a small needs readout next to each
agent (three thin horizontal bars, no gradients, matching the design
system) — same as before, unaffected by the 2D rendering swap.

Peer influence (§7.5): after zone assignment, check for agents co-located
in the same zone this tick. For each co-located pair, apply a symmetric
needs-state nudge based on each agent's most recent action:
- If a peer's last action was Default: nudge the other agent's
  budget_anxiety up by a small fixed amount (e.g. +0.05), scaled down by
  (1 - financial_literacy) — more literate agents are less swayed.
- If a peer's last action was Spend at a discretionary zone (Mall/Café/
  Theater): nudge the other agent's discretionary_appetite up slightly,
  same literacy scaling.
- If a peer's last action was Save: nudge the other agent's
  budget_anxiety down slightly (peer caution is mildly reassuring).
Clamp all needs values to [0, 1] after nudging. Log which pairs were
co-located and what nudge was applied each tick — this is the one place
in the system where one agent's behaviour numerically affects another,
and it should be fully inspectable, not a black box.
```

### 9.3b Peer Interaction Narrator wiring (optional, §8.6)

```
For each co-located pair from §9.3's peer-influence step, optionally call
the Peer Interaction Narrator prompt (§8.6) — reuse the existing Groq/
Ollama/mock fallback driver from backend/app/services/llm.py, don't
duplicate it. This should be genuinely optional/toggleable (e.g. an
env var or query param on the simulate/start endpoint) since it adds one
LLM call per co-located pair per tick — keep it off by default for fast
iteration, on for the actual demo. Attach the narration string to the
WebSocket tick payload alongside the pair's agent IDs so the frontend can
render it as a small text label near the two circles on the 2D canvas.
```

### 9.4 Frontend design system (no gradients, minimal, presentation-grade)

```
Define and enforce a design system for EcoSim-MAS's dashboard before building
individual screens.

Palette: off-white background (#FAFAF8), near-black text (#1A1A18), one
accent color used only for the single most important number or active state
on any given screen (a muted blue, #2F6FED, used sparingly — never as a
background fill). No gradients anywhere, including charts, buttons, or the
2D canvas scene's fills.

Typography: a single sans-serif family (Inter or system-ui stack), two
weights only (regular, medium) — no bold, no italics for emphasis; use size
and spacing instead.

Surfaces: flat fills with a single 1px hairline border (#E5E5E0), no drop
shadows, no elevation layers. Corners: 8px radius, consistently applied.

Layout: one primary visualization per screen (the 2D scene, or a single
chart, or the validation scorecard) with generous whitespace around it —
target at least 15% of viewport as empty margin. Secondary data (agent list,
causal chain steps) collapses into a dismissible side panel rather than
permanently competing for attention.

Motion: transitions only where they carry meaning (an agent moving between
zones, a number counting up after a tick). Ease-out timing, 200-400ms. No
decorative motion, no parallax, no hover glow.

Apply this as shared CSS variables / a Tailwind config, not per-component ad
hoc styles, so every screen inherits it automatically.
```

---

## 10. ML prediction layer (replacing formulas with learned models)

This is what makes the dashboard numbers real instead of derived.

1. **Run many simulations offline** (synthetic shocks + backtested historical shocks) through the trained MARL agents, logging every tick: macro state, all 10 agents' states, actions, and terminal outcomes (which agents crossed into default, final inequality spread).
2. **Train two downstream models on those logs:**
   - **LightGBM regressor/classifier** — baseline, fast, interpretable (feature importances double as an explainability tool for your report) — predicts Failure Frontier threshold and per-agent Risk Score from a macro-state + agent-state snapshot.
   - **Temporal model (LSTM or a small Temporal Fusion Transformer)** — predicts how Risk Score and Inequality Index evolve *forward in time* over the scenario horizon, since these are sequences, not single points.
3. **The dashboard calls these trained models**, not the raw simulation, for live scenario runs — the simulation still runs live (so the agent behaviour is genuinely emergent), but the *headline numbers* shown to the user come from the models trained on thousands of prior runs, giving you calibrated, non-formulaic outputs with an actual error distribution you can report.

---

## 11. Validation mode

A dedicated dashboard tab, separate from live scenario runs:

1. Maintain a curated set of **known historical Indian macro events** with published outcomes (e.g. 2020 COVID lockdown consumption collapse, 2021–22 fuel price surge, RBI repo rate hikes of 2022–23) sourced from RBI reports / CMIE data.
2. For each, feed the *actual* historical macro conditions into the causal chain engine and simulation exactly as if it were a live scenario.
3. Compare the model's predicted Failure Frontier / Inequality Index / aggregate savings-rate change against the *actually observed* historical figures.
4. Report **MAPE and RMSE per event**, and surface this as a validation scorecard in the dashboard — this is your strongest evidence for the review panel that the outputs aren't arbitrary.

---

## 12. Suggested build order (solo, tool-agnostic)

You're building this alone, so drop the multi-owner framing — one module at a time, one tool session at a time. The "needs live keys?" column matters most right now: build the No-rows first and stub the Yes-rows with fixture data, so you're never blocked waiting on an API key.

| # | Module | Needs live API key? |
|---|---|---|
| 1 | Data models (Postgres schema + TimescaleDB hypertables) + ingestion scrapers, run against fixture/sample data first | No (stub GDELT/NewsAPI/RBI responses as JSON fixtures) |
| 2 | Grounding middleware + Scenario Parser endpoint | Groq (stub with a fixed mock response until the key exists) |
| 3 | Causal Chain Engine with Groq/Ollama fallback | Groq + local Ollama |
| 4 | PettingZoo environment + reward functions (hand-code a random policy first) | No |
| 5 | Ray RLlib training pipeline, offline | No |
| 6 | Semantic-to-Numerical Mapper wiring the causal chain into the environment | Groq (reuses §3's key) |
| 7 | Qdrant episodic memory integration | No (self-hosted) |
| 8 | LightGBM + temporal model training on simulation logs | No |
| 9 | FastAPI endpoints + WebSocket streaming | No |
| 10 | (Deferred — was Mixamo character pipeline; see §7.4) | — |
| 11 | 2D world scene + needs-state zone logic (§9.1, §9.2, §9.3) | No |
| 12 | React dashboard: design system, Scenario Parser confirmation card, Validation Mode tab (§9.4) | No |
| 13 | Swap fixtures for live GDELT/NewsAPI/RBI/Groq calls | Yes — all of them |

Modules 1, 4, 5, 7–12 (eight of thirteen) need nothing but a laptop. That's most of the project — don't wait on API key signup to start building.

Building in this order means every module is independently testable before the next depends on it — a hard requirement when an agentic coding tool is doing the implementation, since it gives you a clean checkpoint to verify before moving on.

---

## 13. Solo build workflow

Earlier this doc assumed a 4-person split across Antigravity and Codex — that doesn't apply when you're building alone. Simpler rules for a solo build:

**Pick one daily driver.** Use **Antigravity** for everything by default — it handles backend and frontend equally well, its Manager Surface still gives you internal parallelism (e.g. it can scaffold the 2D canvas scene and the needs-state logic as two sub-tasks while you review something else), and it already talks to Ollama locally, which you need anyway for the causal-chain fallback.

**Bring in Codex only as a second opinion, not a co-owner.** Once a module is working, optionally open the same repo in Codex and ask it to review that module against this spec ("read ARCHITECTURE.md §7, review /backend/simulation against it, flag anything that violates the design") — a review pass, not parallel construction. You never need two tools editing the repo at the same time when you're the only human in the loop; the risk that made §13.1/§13.2 necessary for a team (two agents colliding on the same files) doesn't exist when there's only one of you directing one tool at a time.

**One module, one session, one commit.** Don't ask the tool to "build the whole thing" — feed it exactly one row from the §12 table per session, using the matching build brief or prompt from §8/§9 verbatim. Review the diff yourself before committing (an agent's own "looks correct" isn't a substitute for you reading the change, especially for the RL reward function and the environment step logic, where a subtle bug won't throw an error — it'll just quietly train a policy that doesn't behave right). Commit after each verified module so you always have a clean rollback point if a later session goes sideways.

**Still branch per module**, even solo: `git checkout -b module/2-scenario-parser`, work, merge to `main` once it passes your own review. This costs nothing and means a bad agent session never corrupts your working `main`.
