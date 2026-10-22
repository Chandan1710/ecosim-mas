/**
 * api.js — thin client for the EcoSim-MAS backend (proxied by Vite in dev).
 * Every function throws an Error whose message is safe to show to the user.
 */

async function request(path, body, method = 'POST') {
  let res
  try {
    res = await fetch(path, method === 'GET' ? { method } : {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new Error('Cannot reach the backend. Is uvicorn running on port 8000?')
  }
  if (!res.ok) {
    let detail = ''
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `Request failed (${res.status})`)
  }
  return res.json()
}

/** Module 2 — parse a free-text scenario into understood bullets + open questions. */
export const parseScenario = ({ description, date, location }) =>
  request('/scenarios/parse', {
    description,
    date_override: date || null,
    location_override: location || null,
  })

/** Create the scenario row the chain and simulation hang off. */
export const createScenario = ({ name, description }) =>
  request('/scenarios', { name, description })

/** Module 3 — generate and persist the causal chain. */
export const createCausalChain = (scenarioId, body) =>
  request(`/scenarios/${scenarioId}/causal-chain`, body)

/** Module 9 — map the chain to a shock and start a run. Returns { run_id, shock, ... }. */
export const startSimulation = (scenarioId) =>
  request(`/scenarios/${scenarioId}/simulate/start`)

/* ── Town of generative agents (§7.6) ───────────────────────────────────── */
const get = (path) => request(path, undefined, 'GET')

export const townPresets = () => get('/town/presets')
export const listTownRuns = () => get('/town/runs')
export const townAgents = () => get('/town/agents?seed=7&n=20')
export const getTownRun = (runId) => get(`/town/runs/${runId}`)
export const townDashboard = (runId) => get(`/town/runs/${runId}/dashboard`)
export const validationEvents = () => get('/town/validation/events')
export const validationRuns = () => get('/town/validation/runs')
export const validationScorecard = (runId) => get(`/town/runs/${runId}/validation`)
export const startValidation = (body) => request('/town/validation/run', body)
export const stopTownRun = (runId) => request(`/town/runs/${runId}/stop`)

/** Start a run from a preset ({ preset }) or a scenario ({ scenario_id }). Returns the run's meta. */
export const startTownRun = (opts) => request('/town/runs', { learning: getLearning(), ...opts })

/** Do the residents learn from earlier runs? 'learn' (default) | 'off'. (The backend still accepts 'frozen', "use only", but the page no longer offers it.) Remembered per browser. */
export const LEARNING_MODES = [
  { id: 'learn', label: 'Learn', hint: 'They use what they learned before, and add what this run teaches them.' },
  { id: 'off', label: 'Fresh', hint: 'Everyone starts with no experience, and nothing from this run is kept.' },
]
export const getLearning = () => {
  try {
    const v = localStorage.getItem('ecosim-learning')
    return LEARNING_MODES.some((m) => m.id === v) ? v : 'learn'
  } catch { return 'learn' }
}
export const setLearning = (v) => { try { localStorage.setItem('ecosim-learning', v) } catch { /* private window */ } }

export const townLearning = () => get('/town/learning?seed=7&n=20')
export const resetTownLearning = (agent) => request('/town/learning/reset', agent ? { agent } : {})

export const eventsUrl = (runId) => `/town/runs/${runId}/events`
export const reportUrl = (runId, kind) => `/town/runs/${runId}/report/${kind}`

export const townSocketUrl = (runId) => {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/town/${runId}`
}

/* ── Event propagation: the editable chain of events behind each scenario ──── */
export const propagationList = () => get('/town/propagation')
export const propagationGet = (key) => get(`/town/propagation/${key}`)
export const createChain = (body) => request('/town/propagation/custom', body)
export const regenerateChain = (sid, clarifications) => request(`/town/propagation/custom/${sid}/regenerate`, { clarifications })
export const saveChain = (sid, body) => request(`/town/propagation/custom/${sid}`, body, 'PUT')
export const finalizeChain = (sid, body) => request(`/town/propagation/custom/${sid}/finalize`, body)
export const forgetChain = (sid) => request(`/town/propagation/custom/${sid}`, undefined, 'DELETE')
export const forgetMany = (ids) => request('/town/propagation/forget', { scenario_ids: ids })
export const keepOnlyChain = (sid) => request(`/town/propagation/custom/${sid}/keep-only`, {})
export const previewShock = (nodes) => request('/town/propagation/shock', { nodes })
