/**
 * IntakeFlow — Module 2 frontend (§5, §4 layer 2, §9.4).
 *
 *   describe  →  studio  →  working  →  (onStarted → the town)
 *
 * describe : free-text scenario + editable Simulation context (date, location)
 * studio   : questions on the left, and on the right the chain of events Groq drew, as a flowchart you can edit
 *            (ChainStudio). "Run simulation" stays disabled until every question is answered or skipped
 * working  : the kept chain goes back to Groq in the background to be quantified and written up as the simulation
 *            brief; then the town starts
 *
 * Flat colours, hairline borders, motion only where it carries meaning.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import './intake.css'
import ChainStudio from './ChainStudio'
import { createChain, finalizeChain, parseScenario, propagationGet, regenerateChain, startTownRun } from './api'

const EXAMPLES = [
  'RBI raises the repo rate by 100 basis points',
  'Crude oil jumps 30% after a supply shock',
  'Onion export ban and a weak monsoon',
  'Major IT employer announces 20,000 layoffs',
]

const todayISO = () => {
  const d = new Date() // local date, not UTC (IST is ahead of UTC)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/* ── Hero: a shock spreading outward. Pure SVG, flat strokes, no gradients. ── */
function ShockRipple() {
  const satellites = useMemo(() => {
    const out = []
    const ring = (n, r, delay) => {
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + (r > 100 ? 0.3 : 0)
        out.push({ x: 180 + r * Math.cos(a), y: 180 + r * Math.sin(a), delay })
      }
    }
    ring(6, 70, 1.3)
    ring(10, 125, 2.5)
    ring(12, 168, 3.6)
    return out
  }, [])

  return (
    <svg className="ripple" viewBox="0 0 360 360" role="img" aria-label="A shock spreading through an economy">
      {[0, 1, 2].map((i) => (
        <circle key={i} className="ripple__ring" cx="180" cy="180" r="12" style={{ animationDelay: `${i * 1.6}s` }} />
      ))}
      {satellites.map((s, i) => (
        <circle key={i} className="ripple__node" cx={s.x} cy={s.y} r="3.5" style={{ animationDelay: `${s.delay}s` }} />
      ))}
      <circle className="ripple__core" cx="180" cy="180" r="9" />
    </svg>
  )
}

function Check({ size = 16 }) {
  return (
    <svg className="check" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.5 8.5l3 3 6-7" fill="none" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/* ── Screen 1 ─────────────────────────────────────────────────────────────── */
function Describe({ initial, busy, error, onSubmit, onOpenRun }) {
  const [description, setDescription] = useState(initial.description)
  const [date, setDate] = useState(initial.date)
  const [location, setLocation] = useState(initial.location)
  const [runId, setRunId] = useState('')
  const canSubmit = description.trim().length >= 8 && !busy

  const submit = (e) => {
    e.preventDefault()
    if (canSubmit) onSubmit({ description: description.trim(), date, location: location.trim() })
  }

  return (
    <div className="intake-screen intake-describe">
      <div className="intake-describe__copy">
        <h1 className="intake-title">
          Drop a shock.
          <br />
          Watch the economy react.
        </h1>
        <p className="intake-lede">
          Describe an economic event in plain language. Twenty simulated residents, each with their own
          habits, will respond.
        </p>

        <form onSubmit={submit} className="intake-form">
          <label className="intake-label" htmlFor="scenario-text">Scenario</label>
          <textarea
            id="scenario-text"
            className="intake-textarea"
            rows={3}
            placeholder="e.g. The RBI raises the repo rate by 100 basis points next month"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            autoFocus
          />

          <div className="intake-chips" aria-label="Example scenarios">
            {EXAMPLES.map((ex) => (
              <button type="button" key={ex} className="intake-chip" onClick={() => setDescription(ex)}>
                {ex}
              </button>
            ))}
          </div>

          <div className="intake-context">
            <div className="intake-field">
              <label className="intake-label" htmlFor="ctx-date">Simulation date</label>
              <input id="ctx-date" type="date" className="intake-input" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <div className="intake-field">
              <label className="intake-label" htmlFor="ctx-loc">Location</label>
              <input
                id="ctx-loc"
                type="text"
                className="intake-input"
                placeholder="Auto-detected"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </div>
          </div>

          {error && <p className="intake-error" role="alert">{error}</p>}

          <div className="intake-actions">
            <button type="submit" className="intake-btn intake-btn--primary" disabled={!canSubmit}>
              {busy ? 'Analysing…' : 'Analyse scenario'}
              <span className="intake-btn__arrow" aria-hidden="true">→</span>
            </button>
            {busy && <span className="intake-dots" aria-hidden="true"><i /><i /><i /></span>}
          </div>
        </form>

        <form
          className="intake-openrun"
          onSubmit={(e) => {
            e.preventDefault()
            if (runId.trim()) onOpenRun(runId.trim())
          }}
        >
          <label htmlFor="open-run">Already have a run ID?</label>
          <input id="open-run" className="intake-input intake-input--small" placeholder="Paste run_id" value={runId} onChange={(e) => setRunId(e.target.value)} />
          <button type="submit" className="intake-btn intake-btn--ghost" disabled={!runId.trim()}>Open</button>
        </form>
      </div>

      <div className="intake-describe__art" aria-hidden="true">
        <ShockRipple />
      </div>
    </div>
  )
}

/* ── Screen 3 ─────────────────────────────────────────────────────────────── */
const STEPS = [
  ['Saving your chain of events', 'Keeping the events you included, without the ones you excluded'],
  ['Quantifying the events', 'Groq turns each event into numbers: prices, incomes, credit, spending, savings'],
  ['Writing the simulation brief', 'A detailed briefing and news timeline, written only from your chain'],
  ['Starting the town', 'Twenty residents, one month, your shock'],
]

function Working({ step, error, title, onRetry, onBack, detail }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    if (error) return undefined
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [error])

  return (
    <div className="intake-screen intake-working">
      <p className="intake-eyebrow">Step 3 of 3 · Setting up</p>
      <h1 className="intake-title intake-title--md">Preparing your simulation.</h1>
      <p className="intake-lede intake-lede--clip">{title}</p>

      <ol className="intake-steps">
        {STEPS.map(([name, sub], i) => {
          const state = error && i === step ? 'failed' : i < step ? 'done' : i === step ? 'active' : 'todo'
          return (
            <li key={name} className={`intake-step is-${state}`}>
              <span className="intake-step__dot">{state === 'done' ? <Check size={14} /> : state === 'failed' ? '!' : null}</span>
              <span className="intake-step__body">
                <span className="intake-step__name">{name}</span>
                <span className="intake-step__sub">{state === 'failed' ? error : (state === 'active' && detail) || sub}</span>
              </span>
              {state === 'active' && <span className="intake-step__time">{secs}s</span>}
            </li>
          )
        })}
      </ol>

      {error && (
        <div className="intake-actions">
          <button type="button" className="intake-btn intake-btn--primary" onClick={onRetry}>Try again</button>
          <button type="button" className="intake-btn intake-btn--ghost" onClick={onBack}>Back to scenario</button>
        </div>
      )}
    </div>
  )
}

/* ── Orchestrator ─────────────────────────────────────────────────────────── */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const questionsOf = (parsed) => parsed?.ambiguous_or_missing || []

export default function IntakeFlow({ onStarted, onOpenRun, onExit, runOptions = { days: 7, seed: 7 }, resume = null }) {
  // `resume`: a saved scenario from the Event propagation page, reopened in the studio
  const fromRecord = resume ? {
    parsed: {
      primary_event: resume.title, region: resume.region || null, time_horizon_months: resume.time_horizon_months || null,
      affected_sectors: resume.affected_sectors || [], understood: resume.understood || [],
      ambiguous_or_missing: (resume.clarifications || []).map((c) => ({ field: c.field, question: c.question })),
    },
    answers: Object.fromEntries((resume.clarifications || []).map((c) => [c.field, { text: c.answer || '', skipped: !c.answer }])),
  } : null

  const [phase, setPhase] = useState(resume ? 'studio' : 'describe') // describe | studio | working
  const [input, setInput] = useState({ description: resume?.description || '', date: resume?.date || todayISO(), location: resume?.location || '' })
  const [parsed, setParsed] = useState(fromRecord?.parsed || null)
  const [answers, setAnswers] = useState(fromRecord?.answers || {})
  const [chain, setChain] = useState(resume ? { status: 'ready', rec: resume, error: '', version: 1 } : { status: 'idle', rec: null, error: '', version: 0 })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [step, setStep] = useState(0)
  const [detail, setDetail] = useState('')
  const [runError, setRunError] = useState('')
  const lastRun = useRef(null)

  const clarifications = (qs, ans) => qs.map((q) => ({ field: q.field, question: q.question, answer: ans[q.field]?.skipped ? '' : (ans[q.field]?.text || '').trim() }))

  const buildChain = async (values, result) => {
    setChain((c) => ({ ...c, status: 'writing', error: '' }))
    try {
      const rec = await createChain({
        description: values.description, primary_event: result.primary_event, region: result.region, time_horizon_months: result.time_horizon_months,
        affected_sectors: result.affected_sectors || [], understood: result.understood || [], date: values.date || null, location: values.location || null,
        clarifications: [],
      })
      setChain((c) => ({ status: 'ready', rec, error: '', version: c.version + 1 }))
    } catch (e) {
      setChain((c) => ({ ...c, status: 'error', error: e.message }))
    }
  }

  const analyse = async (values) => {
    setInput(values)
    setBusy(true)
    setError('')
    try {
      const result = await parseScenario(values)
      setParsed(result)
      setAnswers({})
      setChain({ status: 'writing', rec: null, error: '', version: 0 })
      setPhase('studio')
      buildChain(values, result)          // the chain is drawn while the questions are answered
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const retryChain = () => (chain.rec ? null : buildChain(input, parsed))

  const redraw = async () => {
    const sid = chain.rec?.scenario_id
    if (!sid) return
    setChain((c) => ({ ...c, status: 'writing' }))
    try {
      const rec = await regenerateChain(sid, clarifications(questionsOf(parsed), answers))
      setChain((c) => ({ status: 'ready', rec, error: '', version: c.version + 1 }))
    } catch (e) {
      setChain((c) => ({ ...c, status: 'error', error: e.message }))
    }
  }

  const run = async (payload) => {
    const { nodes } = payload || lastRun.current
    lastRun.current = { nodes }
    const sid = chain.rec.scenario_id
    const title = parsed.primary_event
    setPhase('working')
    setRunError('')
    setDetail('')
    try {
      setStep(0)
      await finalizeChain(sid, { nodes, title, clarifications: clarifications(questionsOf(parsed), answers) })
      const t0 = Date.now()
      for (;;) {                                  // Groq works in the background; follow it
        await sleep(1200)
        const rec = await propagationGet(`custom:${sid}`)
        const job = rec.job || {}
        if (rec.status === 'ready') break
        if (rec.status === 'failed' || job.state === 'failed') throw new Error(job.message || 'Writing the brief failed')
        setStep(job.state === 'writing' ? 2 : 1)
        setDetail(job.message || '')
        if (Date.now() - t0 > 180000) throw new Error('This is taking too long. Groq may be rate-limited; try again in a minute.')
      }
      setStep(3)
      setDetail('')
      const started = await startTownRun({ scenario_id: sid, title, ...runOptions })
      onStarted({ runId: started.run_id, shock: started.shock || null, title })
    } catch (e) {
      setRunError(e.message)
    }
  }

  return (
    <div className="intake-root" key={phase}>
      {phase === 'describe' && <Describe initial={input} busy={busy} error={error} onSubmit={analyse} onOpenRun={onOpenRun} />}
      {phase === 'studio' && parsed && (
        <ChainStudio
          parsed={parsed} questions={questionsOf(parsed)} answers={answers} setAnswers={setAnswers} chain={chain}
          onRetryChain={retryChain} onRegenerate={redraw} resumed={Boolean(resume)}
          onBack={() => (resume && onExit ? onExit() : setPhase('describe'))}
          onRun={run}
        />
      )}
      {phase === 'working' && (
        <Working step={step} error={runError} detail={detail} title={parsed?.primary_event || ''}
          onRetry={() => run(null)} onBack={() => setPhase('studio')} />
      )}
    </div>
  )
}
