/**
 * TownHome — start a run of the town (a ready-made shock or your own
 * scenario) and see the latest runs, with replay and the two PDF reports.
 * The full archive lives on the Recent runs page.
 */

import React, { useEffect, useState } from 'react'
import './town.css'
import { LEARNING_MODES, getLearning, listTownRuns, setLearning, startTownRun, townPresets } from './api'
import RunsTable from './RunsTable'

const DAY_OPTIONS = [5, 7, 10, 30]
// measured on the free-tier keys with 20 agents: short (fast-paced) runs re-plan almost daily
const secondsPerDay = (days) => (days <= 10 ? 120 : 90)
const SHOCK_LABELS = [
  ['essential_cost', 'Essentials'], ['income', 'Incomes'], ['credit_tightness', 'Credit'],
  ['demand', 'Demand'], ['savings', 'Saving'],
]
const pct = (v) => `${v > 0 ? '+' : '−'}${Math.abs(Math.round(v * 100))}%`

function duration(days) {
  const m = Math.round((days * secondsPerDay(days)) / 60)
  return m < 60 ? `about ${m} min` : `about ${(m / 60).toFixed(1)} h`
}

export default function TownHome({ onOpen, onDescribe, onViewAll, days, setDays, seed }) {
  const [presets, setPresets] = useState([])
  const [runs, setRuns] = useState(null)
  const [choice, setChoice] = useState('severe')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [learning, setLearningState] = useState(getLearning)

  useEffect(() => {
    townPresets().then(setPresets).catch((e) => setErr(e.message))
  }, [])

  useEffect(() => {
    let alive = true
    let t
    const load = () => listTownRuns()
      .then((r) => {
        if (!alive) return
        setRuns(r)
        if (r.some((x) => x.status === 'running')) t = setTimeout(load, 4000)
      })
      .catch((e) => alive && setErr(e.message))
    load()
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [])

  const latest = [...(runs || [])].sort((a, b) => (b.created_at || 0) - (a.created_at || 0)).slice(0, 3)
  const active = (runs || []).find((r) => r.status === 'running')

  const start = async () => {
    setBusy(true)
    setErr('')
    try {
      const meta = await startTownRun({ preset: choice, days, seed: Number(seed) || 7, learning })
      onOpen(meta.run_id)
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }

  return (
    <div className="home">
      <div className="home__inner">
        <h1 className="home__title">How does an economic shock spread through a town?</h1>
        <p className="home__lede">
          A simulated town of 20 residents, each an AI agent with their own income, bills, savings, memories and
          neighbours. Apply a shock, observe how households adapt, borrow and cope, then export the findings.
        </p>
        <ol className="home__steps">
          <li><b>1</b> Choose a scenario</li>
          <li><b>2</b> Observe the town day by day</li>
          <li><b>3</b> Review and export the findings</li>
        </ol>

        {active && (
          <div className="home__active">
            <span className="town-pill town-pill--live"><i />Live</span>
            <span><b>{active.title}</b> · day {active.days_done} of {active.days}</span>
            <span className="town-bar__spacer" />
            <button type="button" className="town-btn" onClick={() => onOpen(active.run_id)}>Open</button>
          </div>
        )}

        <h2 className="home__h">Scenario</h2>
        <div className="home__cards">
          {presets.map((p) => (
            <button type="button" key={p.id} className={`home-card ${choice === p.id ? 'is-on' : ''}`} onClick={() => setChoice(p.id)}>
              <span className="home-card__t">{p.title}</span>
              <span className="home-card__d">{p.blurb || p.headlines[0]}</span>
              <span className="home-card__chips">
                {(p.tags || []).map((t) => <span key={t} className="home-chip home-chip--rule">{t}</span>)}
                {SHOCK_LABELS.filter(([k]) => Math.abs(p.shock[k] || 0) >= 0.005).map(([k, l]) => (
                  <span key={k} className="home-chip">{l} {pct(p.shock[k])}</span>
                ))}
              </span>
            </button>
          ))}
          <button type="button" className="home-card home-card--own" onClick={onDescribe}>
            <span className="home-card__plus" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M9 3.5v11M3.5 9h11" />
              </svg>
            </span>
            <span className="home-card__own-text">
              <span className="home-card__t">Describe your own</span>
              <span className="home-card__d">Write any economic event in plain words. The AI traces its knock-on effects and turns them into a shock.</span>
            </span>
          </button>
        </div>

        <h2 className="home__h">Settings</h2>
        <div className="home__opts">
          <div className="home__opt">
            Duration
            <div className="town-seg" role="group" aria-label="Days to simulate">
              {DAY_OPTIONS.map((d) => (
                <button type="button" key={d} className={days === d ? 'is-on' : ''} onClick={() => setDays(d)}>{d}</button>
              ))}
            </div>
            days
          </div>
          <div className="home__opt">
            Residents
            <div className="town-seg" role="group" aria-label="Learning from earlier runs">
              {LEARNING_MODES.map((m) => (
                <button type="button" key={m.id} className={learning === m.id ? 'is-on' : ''} title={m.hint}
                  onClick={() => { setLearningState(m.id); setLearning(m.id) }}>{m.label}</button>
              ))}
            </div>
          </div>
          <span className="home__est">{LEARNING_MODES.find((m) => m.id === learning)?.hint}</span>
          {choice === 'hyperinflation' && days < 7 && (
            <span className="home__est">This scenario needs at least 7 days to reach the crash after the price boom.</span>
          )}
          <span className="home__est">
            {duration(days)} live · {days <= 10 ? 'shock begins on day 2, full effect by day 5' : 'shock begins on day 3, full effect by day 10'}
          </span>
        </div>

        <div className="home__go">
          <button type="button" className="town-btn" onClick={start} disabled={busy || Boolean(active)}>
            {busy ? 'Starting…' : 'Run simulation →'}
          </button>
          {active && <span className="home__est">One run at a time: the agents share the same API keys.</span>}
          {err && <span className="home__err" role="alert">{err}</span>}
        </div>

        <h2 className="home__h">Recent runs</h2>
        {runs && runs.length === 0 && <p className="home__empty">No runs yet. Every run is saved automatically and can be replayed at any time without using the API.</p>}
        {runs && runs.length > 0 && (
          <>
            <RunsTable runs={latest} onOpen={onOpen} />
            {runs.length > latest.length && onViewAll && (
              <button type="button" className="town-btn town-btn--ghost town-btn--sm home__more" onClick={onViewAll}>
                View all {runs.length} runs →
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
