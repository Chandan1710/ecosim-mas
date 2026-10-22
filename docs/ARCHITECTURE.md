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

## 0.1 Current state (23 October 2026)

**What the product is now.** A town of 20 LLM "generative agents" (§7.6) living in a pixel-art Indian town. A shock (a preset, or a scenario the user describes and edits as a chain of events, §7.9) is turned into numbers and rules the code enforces; the residents perceive, remember, decide, act, talk and reflect each simulated day; the results are read on a Dashboard (§7.10), checked against published figures in Validation mode (§11.1) and carried between runs as lessons (§7.8). The RL personas of §7.2 are kept only as a baseline.

**Layers, top to bottom.**

| Layer | What | Where |
|---|---|---|
| Frontend | React 18 + Vite: Home, Dashboard, Agent profiles, Event propagation, Validation, Recent runs, live town view | `frontend/src/` |
| API | FastAPI: REST for runs, scenarios, propagation, dashboard, validation; WebSocket for the live and replayed event stream | `backend/app/api/endpoints/` (`town.py`, `propagation.py`, `scenarios.py`) |
| Town engine | Economy rules, shocks, 20 resident agents, daily loop, rewards and lessons | `backend/town/` |
| LLM pool | Groq, Cerebras, Gemini, Mistral, OpenRouter, Ollama, with per-key budgets and fallback; an offline `MockBrain` for tests | `backend/town/llm_pool.py`, `brain.py` |
| Storage | PostgreSQL or SQLite (experience, lessons, trust, scenarios), Qdrant (agent memory, in-process fallback), run logs as JSONL | `backend/town/experience.py`, `memory.py`, `backend/runs/` |

**Pages and the section that explains each.** Home and live view §7.6, scenarios §7.7, Agent profiles §7.7 and §7.8, Event propagation §7.9, Dashboard §7.10, Validation §11.1.

**Run it.** `./start.sh` starts the backend and the frontend (new backend endpoints need a restart); `docker compose up` starts PostgreSQL and Qdrant. Keys go in `.env` (never committed). Offline, with no keys, everything runs on the mock brain.

**What has been measured, and what has not.**

| Claim | Evidence | Status |
|---|---|---|
| Experience helps in a hard scenario | Offline brain, lockdown: summed town reward -22.9 to -9.0 after one month (`test_experience_improves_a_hard_scenario`) | Measured, mock brain only |
| The town reproduces real shocks | COVID-2020 scorecard 42% (2 close, 1 roughly, 3 off); COVID-2021 0% (§11.1) | Measured, mock brain only |
| LLM agents improve with experience | No run compares *Fresh* and *Learn* with a real LLM | Not measured |
| Real-LLM validation | No validation or Dashboard run has been made with a real LLM | Not tested |
| Cost of a real run | About 20 calls, ~31K tokens and 75 s to 2 min per simulated day for 20 agents (§7.6) | Measured |

**Known limits.** One run at a time (all runs share the same API keys), so runs cannot be compared side by side live; a lockdown is all-or-nothing, so partial restrictions are not modelled; credit assignment for lessons is crude (§7.8); with 20 residents one person is 5 points of any percentage; populations of 30 or more fail in `generate_population`.

**Next steps, in order of value.** (1) Run the COVID-2020 validation and a *Fresh* versus *Learn* pair with the real LLM, and record the numbers in §11.1 and §7.8. (2) Add a partial-lockdown rule so the 2021 wave can be tested fairly. (3) A compare view that overlays two saved runs on the Dashboard (saved runs make this a read-only feature, with no need for parallel live runs).

**Tests.** Backend: `pytest backend/tests` (town, scenarios, learning, propagation, dashboard, validation, shock dynamics). Frontend: `node frontend/src/chainLayout.test.mjs`. Tests that need the database use a throwaway SQLite file (`tests/conftest.py`).

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

> **Superseded for the live simulation by §7.6 (October 2026).** The RL policies below are kept as the *baseline* that the LLM agents are compared against.

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

### 7.6 v2 — a town of generative agents (decision, October 2026)

**Why it changed.** The persona + RL design produced learned policies, but behaviour came from 10 archetype labels, zone choice and peer influence were hand-written formulas, memory was write-only, and agents could not reason. v2 replaces the live simulation with individual agents that perceive, remember, reason in language, talk to each other and act, inside a town whose economic rules are enforced by code. The RL personas (§7.2) remain as a baseline for comparison.

**Code:** `backend/town/` (`world.py`, `population.py`, `economy.py`, `memory.py`, `brain.py`, `llm_pool.py`, `engine.py`, `runs.py`, `analysis.py`, `report.py`); API in `backend/app/api/endpoints/town.py`; tests in `backend/tests/test_town.py` and `test_town_api.py`; headless runner `python -m town.run_cli`; key checker `python -m town.check_llm`. Frontend: `TownHome.jsx` (start / saved runs), `TownView.jsx` (live map and player), `townScene.js` (pixel-art tile map), `townSprites.js` (character sprites), `townGeometry.js` (roads, doorways, standing spots), `town.css`.

**Agents are individuals, not personas.** `population.py` samples each agent attribute by attribute: name, age, job and employer, pay type (monthly / daily wage / self-employed / shop profit / pension / allowance), household and children, home, rent, vehicle, chronic illness and medicine cost, loans (home, vehicle, credit card, moneylender) with EMIs and due dates, savings, whether they follow the news, relationships (neighbours, co-workers, friends, regular customers) and goals that follow from their circumstances. There are no personality labels; behavioural differences must come from circumstances, memories and reasoning. Seeded, so a town is reproducible.

**The town (`world.py`).** 20 places on a 64×40 tile grid with roads: 4 residential areas, kirana (khata credit), supermarket, Sabzi market, pharmacy, fuel station, café, restaurant, mall & cinema, TechPark, garment factory, construction site, school & college, clinic, auto/delivery stand, cooperative bank, park. The same map JSON is served to the frontend.

**Economic rules (`economy.py`)** — the LLM decides, the code enforces:
- The scenario `Shock` (§8.4 deltas collapsed by `simulation/shock.py`) ramps in over time. Pace `normal` (30-day runs): starts day 3, full by day 10, job cuts on day 10. Pace `fast` (runs of 10 days or fewer, the default for demos): starts day 2, full by day 5, job cuts on day 5, headlines daily. Essential-cost shock → shop prices (pass-through: groceries 1.0, fuel 1.3, medicine 0.5, eating out 0.6). Income shock → fewer daily-wage shifts and a round of job cuts. Demand shock → fewer customers for auto drivers, delivery riders and the café. Credit tightening → the bank demands a higher credit score, lends less, caps EMI-to-income lower, charges more.
- Shop owners earn the day's margin on sales to other agents plus background customers. A one-person shop (kirana, café) is only open while its owner is there; the Sabzi Market has many stalls, so it stays open and the agent vendor only earns when at their stall. Salaried workers must be at work in the morning or afternoon on workdays or it is recorded as skipping work.
- Groceries, fuel and medicine are stocks that run out; running out of food or medicine is recorded.
- Bills (rent day 5, utilities day 10, school fees, EMIs, weekly moneylender instalments) are auto-debited; missed payments cost late fees and credit score, and two missed instalments on a loan is a default.

**Cognition loop (`engine.py`, `brain.py`), once per simulated day:**
1. *Perceive*: income, bills, news (only agents who follow news read it), job cuts, prices noticed while shopping, yesterday's outcomes.
2. *Retrieve*: top memories scored by recency (0.85/day) + importance (1–10) + relevance (all-MiniLM-L6-v2 embeddings), as in Park et al. (2023). Memories are persisted to Qdrant (`agent_memory`, filtered by run and agent).
3. *Decide*: an LLM, prompted as that person, returns a first-person thought and a JSON plan for morning / afternoon / evening (place, activity, spend), money actions (bank loan, moneylender, repay, send money home, deliberately skip a bill) and whom to talk to. The plan is normalised and validated; invalid parts are repaired and logged.
4. *Act*: agents move and act; the economy accepts or refuses each action.
5. *Talk*: agents who seek someone out, or who know each other and meet at social places, hold an LLM-written conversation; each side's takeaway becomes a memory. This is how information (e.g. news) reaches agents who never read it — peer influence is emergent, not a coded nudge.
6. *Reflect*: after enough important experience (summed importance ≥ 60, at most every 6 days) the agent writes 1–3 first-person conclusions, stored as high-importance memories that are shown in later decisions.

Agents with nothing new skip the LLM and follow yesterday's routine (re-planning at least every 3 days); this is shown as `routine` in the event stream, never disguised as reasoning.

**LLM providers (`llm_pool.py`).** OpenAI-compatible calls to any configured subset of Groq, Cerebras, Gemini, Mistral, OpenRouter and local Ollama, with per-provider requests/tokens-per-minute budgets, automatic fallback on 429s and errors, a circuit breaker, JSON validation with one corrective retry, and usage accounting. If no provider answers, an agent keeps its routine (`fallback` in the stream). `MockBrain` is a labelled rule-based stand-in used only for tests and offline runs. Measured (22 Oct 2026, `gpt-oss-120b` on one Groq key + two Cerebras keys, reasoning effort low): about 20 calls and ~31K tokens per simulated day for 20 agents, ~75 s per simulated day, zero fallbacks — so a 30-day run is roughly 600 calls, ~0.95M tokens and ~40 minutes. Free-tier limits that bind: Cerebras 5 requests/min and 1M tokens/day per key; Groq 1,000 requests/day for gpt-oss-120b. Each comma-separated key gets its own budget, and the budget is corrected to the real token count after each reply. A 7-day `fast` run (news every day, so nearly everyone re-plans daily) measured 130 LLM plans, 40 conversations and 20 reflections in 845 s — about 2 minutes per simulated day — plus ~1 minute for the stories.

**Runs, live view and replay (`runs.py`, `/town/*` API).** `POST /town/runs` starts a run from a preset (`none`, `mild`, `severe`) or from a scenario created in the intake flow (`scenario_id` — its causal chain is mapped to a `Shock`). One run at a time, because all runs share the same API keys. Each run is saved in `backend/runs/` as `<id>.jsonl` (every event) and `<id>.meta.json` (settings, status, latest town stats). `WS /ws/town/{id}` sends the events so far and then live ones; the same socket replays a finished run from disk without any LLM calls. **Look (Pokémon-style, all drawn in code, no image files, no copyrighted assets):** `townScene.js` paints the 64 × 40 tile town once onto an offscreen canvas at 16 px per tile — grass, sand roads that autotile their edges, a lake, trees, lamps, and every building as a furnished cutaway (walls on top, floor and furniture inside, doorway on the road side; markets, parks, the fuel station, auto stand and construction site are open-air). `townSprites.js` draws each person as an 18 × 24 px sprite with four directions and a four-frame walking cycle; the outfit comes from the job (hard hat, nurse cap, saree, tie, apron…) and hair, skin and colours from the agent id, so a person always looks the same. TownView scales the scene with nearest-neighbour, draws people back to front, tints the whole town by time of day, greys out closed buildings, and hangs a name board under each building. The frontend paces the events so they can be watched: thought bubbles as agents plan, walking at a steady pace out of one doorway, along the roads (BFS over road tiles) and into another, speech bubbles for conversations, a feed, an agent inspector (situation, plan, thoughts, memory) and town indicators; replays run at 1×/2×/4× or skip to the end.

**Reports (`analysis.py`, `report.py`).** Findings are computed from the event log: per-day town indicators, each agent's outcome (*In crisis* = defaulted, lost their job or 2+ days without food; *Under strain* = new moneylender loan, shop credit, a skipped bill, a day without food or over 40% of cash lost; else *Coping* — the live view uses the same rules), *major decisions* (the first plan, every plan that moves money, and each plan made the morning after a pivotal point, quoted in the agent's own words) and *pivotal points* (job loss, default, going hungry, refusals, moneylender borrowing, big bills, falling sales; repeats collapsed). After a run, the LLM writes a 3–5 sentence story and turning point per agent plus a town summary from those facts only (`<id>.stories.json`, labelled as LLM-written in the PDFs). `GET /town/runs/{id}/report/summary` is a 1–2 page PDF (KPIs, what happened, charts, who was hit hardest, key events, method); `/report/agents` is the per-agent report (overview table, then each person's numbers, cash sparkline, story, major decisions, pivotal points, conversations and conclusions). Built with ReportLab (`reportlab<5` for Python 3.9).

**Event stream.** Every run emits `run_start, day_start, decision, move, action, conversation, reflection, day_end, lessons, run_end` events (documented in `engine.py`); the CLI saves them to `backend/runs/<run_id>.jsonl`. The same events drive the live view, replays, the dashboard and the PDF report.

### 7.7 Scenarios, rules and the app shell (October 2026)

**Seven presets plus your own** (`town/scenarios.py`): *Severe fuel and credit shock*, *Deadly pandemic* (grain shortage with rationing), *World war*, *Natural disasters*, *Hyperinflation and extreme deflation*, *Baseline*, *Emergency strict lockdown*, and *Describe your own* (the intake flow). A scenario is a `Shock` (the five deltas) plus `Rules` the economy enforces: a lockdown (only essential shops open; office staff and students work from home, others lose the day), a shift part-way through (boom then bust), place closures for some days, one-off damage to some homes, per-category rationing, and whether layoffs happen. `GET /town/presets` returns each scenario's text, shock, rules and tags; `day_start` carries the list of closed places and the map greys them out.

**App shell (`frontend/src/`).** A sidebar with *Home*, *Agent profiles* (every resident's full profile, `GET /town/agents`), *Event propagation* (§7.9) and *Recent runs* (all saved runs with filter, search and a log download; Home shows the latest three). Light and dark themes (`ThemeSwitch.jsx`, tokens on `:root[data-theme]`, no gradients, cross-fade via the View Transitions API), a 3×3 block logo that returns to Home. Tests: `test_town_scenarios.py`.

### 7.8 Learning from experience (October 2026)

**What the agents are.** They are LLM agents, not reinforcement-learning agents: nothing updates a neural network. The learning is *Reflexion-style*: experience is written down, distilled into lessons, stored in a database and put back into the next prompt. The RL personas (§7.2) remain only as a baseline.

**The loop (`town/learning.py`, `town/experience.py`).**
1. *Reward.* After every simulated day each agent gets a reward from what actually happened, computed by code and visible in the event stream (`day_end.rewards`): food (-1.0 went hungry, -0.25 nearly out, +0.1 well stocked), medicine (-0.8), bills (-0.4 per missed payment, -1.5 per default, small + for paid bills), debt (-0.3 per moneylender loan, ±0.3 for debt rising/falling relative to income), cash runway (+0.1 / -0.1 / -0.3), job (-2.0 on losing it, -0.15 a day unemployed), fuel (-0.1). The total is clipped to [-3, +1]. Rewards are measured in every run, whatever the learning mode.
2. *Experience.* Per agent per day: the situation (cash, food days, bills due, price, lockdown, ...), the plan, the main outcomes and the reward, stored in `town_experience`.
3. *Lessons.* At the end of a run each agent distils lessons from its worst and best days: rule-based detectors (stock food earlier, avoid the moneylender except for food and medicine, pay bills first, build a buffer after a layoff, refuel early, cut treats when the shock hits, prepare for a lockdown), and, with a real LLM brain, an LLM pass (`LLMBrain.distil`) that words them in the agent's voice. A lesson has a strength: confirmed by a later run it grows; if it was in use and the month went worse than that agent's previous month of the same kind it shrinks (a lesson that keeps hurting fades below 0.2 and is no longer shown). At most 40 lessons are kept per agent.
4. *Other people.* When a conversation is followed next day by a changed plan, the agent compares that day's reward with its own average and moves its *trust* in that person up or down (`town_social`; 0..1, starting at 0.5). Strongly good or bad advisers become lessons ("Arjun's advice helped me"). Which talk influenced which decision is logged in `town_influence`.
5. *Next prompt.* Before each decision the agent's prompt gets three short blocks (~1,700 characters at most): **What you have learned from earlier months** (the top 4 lessons, ranked by relevance to today's news and the same scenario, strength and confirmations), **Similar days you remember** (up to two past days with the plan and its reward) and **Whose advice you trust**. The same lessons carry `hint` numbers that the offline `MockBrain` applies so that tests and offline demos change behaviour too.

**Modes** (per run, `learning` in `POST /town/runs`; Home → Settings → Residents offers two): *Learn* (use and record, the default) and *Fresh* (`off`: no memory, nothing recorded). The API still accepts `frozen` (use what was learned, record nothing, a fair test of training); the page no longer shows it. If no database can be reached the run proceeds as *Fresh* and says so.

**Database (`experience.py`).** SQLAlchemy Core with four tables (`town_experience`, `town_lessons`, `town_social`, `town_influence`), created on first use. URL: `ECOSIM_EXPERIENCE_DB`, else the project's PostgreSQL (`db/session.py`), else a SQLite file `backend/runs/experience.db`. An agent's identity is `s<seed>-<id>-<name>`, so the same seed gives the same residents across runs. `GET /town/learning` returns per-resident learning curve, lessons, trust and recent influences (shown under *Agent profiles → What I have learned*); `POST /town/learning/reset` forgets one resident or everyone. Tests use a throwaway SQLite file (`tests/conftest.py`), never the real database.

**What was measured.** With the offline `MockBrain` most scenarios are mild enough that nothing goes wrong, so there is little to learn there. In the lockdown scenario, where the rule-based agents are caught unprepared, one month of experience raised the summed reward of the town from -22.9 to -9.0 in a frozen test run, and `test_experience_improves_a_hard_scenario` guards this. Whether LLM agents improve is an empirical question for the real runs: compare the average reward of the same scenario in *Fresh* and *Use only* mode, and plot a resident's learning curve across repeated runs.

**Limits, stated plainly.** Credit assignment is crude (a month-level comparison, not a counterfactual), so a lesson can be wrong for a while before it is weakened; the offline brain applies lessons through a few hand-written hints, not understanding; with a population of 30 or more `generate_population` currently fails (the profile and learning endpoints are capped at 25).

### 7.9 Event propagation: the editable chain of events (October 2026)

**What it is.** Every scenario spreads through the town as a chain of events (oil jumps, so transport costs rise, so vegetables get dearer, ...). This feature draws that chain as a flowchart, lets the user edit it, sends the edited chain back to Groq to be quantified and written up as a detailed brief, and stores every scenario with its chain in one place.

**Flow for "Describe your own".** *Describe* (free text, date, location) → *Studio* → *Setting up* → the town. The Studio is two columns. Left: what the parser understood and the questions it could not answer (each must be answered or skipped). Right: the chain Groq drew (`generate_causal_chain`, 10 to 15 events). The chain is a straight spine of cause and effect with branches where one event has several effects: the first effect stays on the spine (lane 0), each further effect opens a lane to the right, and an event with two causes returns to the leftmost cause's lane. Edges that skip a row run through a gutter so a line never crosses a card (`chainLayout.js`, `ChainGraph.jsx`). Cards shrink to fit the box (down to 184 px) before the chart scrolls sideways.

**Editing.** Select an event to light up everything that follows from it (animated flow) and dim the rest. *Edit* rewrites an event (text, category, size); *Add effect* attaches a new event to the selected one (two on the same event create a branch; with nothing selected it is added at the end); *Exclude* keeps the event on the chart, struck through and not counted, so it can be brought back; *Delete* removes it, and its effects are relinked to its causes. *Undo* steps back. The five totals (essential prices, incomes, credit, spending, savings) are recomputed live from the kept events (`POST /town/propagation/shock`). Every change is autosaved after 1.4 s. A blank event that is still being typed is never stored or counted.

**What goes back to Groq, in the background** (`town/propagation.py`). On *Run simulation* the kept chain (excluded events are removed and the rest renumbered, relinking effects to causes) goes through a job (`finalize`): (1) events with no numbers yet are quantified with the existing per-node mapper (`map_node_to_deltas`; Groq, then Ollama, then a mock); (2) Groq writes the **simulation brief**: a 150 to 250 word account of how the shock unfolds, 5 to 8 news headlines in the order they reach the town, and 4 to 6 effects residents will feel, using only the events in the chain (`BRIEF_PROMPT`; Ollama, then a template if no LLM answers, and the source is shown on the page); (3) the kept chain is written to the older `causal_chains` table so existing code finds it. The run then starts from the stored scenario; its headlines come from the brief. The brief shapes the news the residents hear and what the UI shows; it is not pasted into agent prompts directly.

**The page (sidebar → Event propagation).** Left: every scenario, searchable and filterable (All, Yours, Built-in, Drafts), each with a small picture of its chain, a status and "N events, M runs". Right, for the selected one: the title and description, *Run*, *Edit the chain* and *Forget* (your own only); five figures (events, branches, depth, runs, who drew the chain); the brief or the explanation; the five totals as centred bars; the rules the town enforces; the full flowchart with an inspector (what the event does to the numbers, what it follows from and leads to, confidence); the headlines the residents hear; and a table of every run made from the scenario with *Replay*. The seven built-in scenarios carry hand-written chains (`town/propagation_presets.py`) that match what the simulator actually does. Scenarios made before this page existed are imported once.

**Storage.** Table `town_propagation` (key `preset:<id>` or `custom:<scenario id>`, status draft / working / ready / failed / hidden, the record as JSON) in the same database as the learning data (§7.8: `ECOSIM_EXPERIENCE_DB`, else PostgreSQL, else SQLite). *Forget* hides a scenario; its runs stay in Recent runs. Endpoints (`app/api/endpoints/propagation.py`): `GET /town/propagation`, `GET /town/propagation/{key}`, `POST /town/propagation/custom`, `POST .../custom/{id}/regenerate`, `PUT .../custom/{id}`, `POST .../custom/{id}/finalize`, `DELETE .../custom/{id}`, `POST /town/propagation/shock`. Tests: `test_propagation.py` (chain repair, exclusion relinking, shock sums, the whole create-edit-finalize flow against a throwaway database, regenerate and forget, legacy import, run linking) and `chainLayout.test.mjs`.

**Limits.** Quantifying each event is one LLM call, so under Groq rate limits some events fall back to the mock mapper; the chain is only as good as the model's economics, which is why the user reviews it; excluding an event changes the shock, because the totals are the sum of the kept events.

### 7.10 Dashboard: one run on one page (October 2026)

**What it is.** Sidebar → *Dashboard* (between Home and Agent profiles). It shows one simulation at a time, the latest run by default, and a drop-down at the top switches to any other saved run; the whole page follows it. The choice is remembered for the browser session. While the selected run is still going the page refreshes every 3 seconds.

**Sections, top to bottom.** *Results*: the run's title, state and scenario, three or four plain-language findings, one headline figure (how many of the 20 residents ended the run struggling, with a coping / under strain / in crisis bar) and eight tiles (average and median cash, groceries and fuel price index, people borrowing from the moneylender, without work, in default, who went hungry), each with its change since day 1 coloured by whether it is good or bad. *How it unfolded*: three line charts drawn as plain SVG: residents in trouble per day, grocery and fuel price index, and average cash, each with the shaded days where the shock builds up, a hover crosshair with one tooltip for all series, keyboard arrows and a Table switch. *Residents*: every resident with status, a cash sparkline, start to end cash and what went wrong, filterable by status. *Event propagation*: the scenario's flowchart (the same component as the Event propagation page, with its inspector) and the numbers the scenario added up to, plus a link that opens it on the Event propagation page. *The Groq brief*: the brief Groq wrote (or the built-in explanation for ready-made scenarios), the news the residents heard in order, and what to watch for. *Turning points*: key moments in order.

**Backend.** `GET /town/runs/{run_id}/dashboard` (`town/dashboard.py`) builds everything from the run's event log with the same `analyse()` the PDF report uses, so the page and the report agree. The scenario record (chain, brief, headlines) is looked up from the ready-made scenarios or the saved ones; if the scenario has since been deleted the page says so and still shows the run. 404 for an unknown run, 409 for a run that has not produced events yet. Tests: `tests/test_dashboard.py`.

**Frontend.** `DashboardPage.jsx` (page, run picker, tiles, residents), `DashCharts.jsx` (line chart, sparkline, status bar), `dashboard.css`. Chart colours come from a fixed, colour-blind-checked set of four per theme; status is always an icon shape plus a label, never colour alone.

**Limits.** Charts show per-day town totals, not per-resident paths (the sparkline covers cash only). A run can be opened from Validation ("Open in Dashboard") and a validation run has an "Open scorecard" button on the Dashboard; two runs cannot yet be overlaid.

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


### 11.1 How it is built for the town (October 2026)

Sidebar → *Validation*. The page has two ways in and one scorecard.

**Real events** (`town/validation_events.py`). Each event keeps two halves strictly apart. *Inputs* are what was imposed from outside (a stay-at-home order, a price rise, a rate change) and are the only thing the town is given. *Outcomes* are published results (jobs lost, households eating less, informal borrowing, spending), each with its source link, and are never shown to the town. Two events ship: the 2020 national lockdown (six figures from CMIE, the Azim Premji University survey and the NSO) and the 2021 second wave (one figure, CMIE). To add one, add an entry to `EVENTS`. **Your own event**: type what was imposed and up to six real figures with a source each.

**Run.** `POST /town/validation/run` starts an ordinary town run (so it appears in Recent runs and on the Dashboard) with `source = {validation: <id>}`, the inputs as the shock, fresh residents (no learning), 30 days by default (one simulated day for one real day; 10 and 20 are offered for speed).

**Scorecard** (`town/validation.py`, `GET /town/runs/{id}/validation`). Five measures are computed from the run's event log: workers without work, residents short of food, residents who borrowed informally, change in casual workers' earnings, change in household spending. Each is taken for the group the real survey covered (all residents, lower-income residents, or daily-wage and self-employed residents). The town drifts a little even with no shock (people stock up on day 1, pay arrives on set days), so the same days are also run with no shock on the offline brain, in memory and never saved, and the **difference** is what is compared. Each figure is then judged against a tolerance band: *close* inside the larger of 7.5 points and 25% of the real figure; *roughly* up to twice that away and moving the same way; *off* otherwise. The event's match score is the share of its figures that are close (1) or roughly right (0.5).

**What the first scorecards showed (offline mock brain, 22 October 2026).** COVID-2020, 30 days, six figures: *close* on informal borrowing (40 against 37 real) and household spending (-33.6 against -26.7); *roughly* on casual workers losing work (100 against 67); *off* on the overall rise in joblessness (+47.1 against +14.8 points, because every non-essential worker loses the day under an all-or-nothing lockdown), on residents short of food (30 against 74) and on casual workers' earnings (-100 against -47). Match score 42%. COVID-2021 scores 0% for the same reason: the real 2021 restrictions were partial. These are results of the model with a rule-based brain; the language-model brain has not been run through validation yet, and nothing was tuned to move these numbers.

**What this is not.** Nothing in the town is tuned against these figures. A low score is a finding about the model (for example, its lockdown is all-or-nothing, so it loses more work than the partial restrictions of 2021 did), not something to hide. With 20 residents one person is 5 points, so the claim is "around the real figure", never "equal". The no-shock control uses the offline brain even when the event run used the language model. Spending is in rupees, not adjusted for price changes.

**Endpoints.** `GET /town/validation/events`, `POST /town/validation/run`, `GET /town/validation/runs`, `GET /town/runs/{id}/validation`. Tests: `tests/test_validation.py`. Frontend: `ValidationPage.jsx`, `validation.css`.

---

## 12. Suggested build order (solo, tool-agnostic)

> **Status (23 October 2026).** This table is the original plan, written when the live simulation was RL agents. The live simulation is now the town of LLM agents (§7.6 to §7.10) and Validation mode is built (§11.1); see §0.1 for the current state. Rows 4, 5 and 8 describe the RL baseline, which is kept but not part of the main flow.

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
