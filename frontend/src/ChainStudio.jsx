/**
 * ChainStudio — the second step of "Describe your own".
 *
 *   left   what we understood, and the questions that still need an answer
 *   right  the chain of events Groq drew, as a flowchart you can edit: add effects and branches, reword events,
 *          exclude the ones that don't fit (they stay on the chart, greyed, and stop counting), or delete them
 *
 * Edits are saved as you go. "Run simulation" sends the chain you kept back to Groq (in the background) to
 * quantify it and to write the detailed simulation brief — see IntakeFlow's working screen.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './chain.css'
import './studio.css'
import ChainGraph, { ChainSkeleton } from './ChainGraph'
import ShockBars, { SHOCK_ROWS } from './ShockBars'
import { addEffect, keptCount, patchNode, removeNode, setIncluded } from './chainLayout'
import { previewShock, propagationGet, saveChain } from './api'

const Check = () => (
  <svg className="check" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M3.5 8.5l3 3 6-7" fill="none" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const answersKey = (questions, answers) => JSON.stringify(questions.map((q) => {
  const a = answers[q.field]
  return a && !a.skipped ? (a.text || '').trim() : ''
}))

export default function ChainStudio({
  parsed, questions, answers, setAnswers, chain, onRetryChain, onRegenerate, onBack, onRun, resumed = false,
}) {
  const sid = chain.rec?.scenario_id
  const [nodes, setNodes] = useState([])
  const [history, setHistory] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [shockOpen, setShockOpen] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [shock, setShock] = useState(null)
  const [saved, setSaved] = useState('')
  const [generatedFor, setGeneratedFor] = useState(() => answersKey(questions, answers))
  const [regenBusy, setRegenBusy] = useState(false)
  const seeded = useRef(null)

  // a new chain from the server (first load, or after "update with my answers") replaces what is on screen
  useEffect(() => {
    if (chain.status === 'ready' && chain.rec && seeded.current !== chain.version) {
      seeded.current = chain.version
      setNodes(chain.rec.nodes)
      setHistory([])
      setSelectedId(null)
      setEditingId(null)
      setGeneratedFor(answersKey(questions, answers))
    }
  }, [chain.status, chain.rec, chain.version]) // eslint-disable-line react-hooks/exhaustive-deps

  const change = useCallback((fn) => {
    setNodes((cur) => {
      const next = fn(cur)
      if (next !== cur) setHistory((h) => [...h.slice(-29), cur])
      return next
    })
  }, [])
  const undo = () => setHistory((h) => {
    if (!h.length) return h
    setNodes(h[h.length - 1])
    setEditingId(null)
    return h.slice(0, -1)
  })

  // numbers for events the server has quantified in the background: merge in, never overwrite your wording
  const unquantified = nodes.some((n) => n.included && !n.deltas)
  useEffect(() => {
    if (!sid || !unquantified || chain.status !== 'ready') return undefined
    let alive = true
    let tries = 0
    const tick = async () => {
      tries += 1
      try {
        const rec = await propagationGet(`custom:${sid}`)
        if (!alive) return
        const fresh = new Map(rec.nodes.filter((n) => n.deltas).map((n) => [n.id, n]))
        setNodes((cur) => {
          let changed = false
          const next = cur.map((n) => {
            const f = fresh.get(n.id)
            if (f && !n.deltas && f.description === n.description) {
              changed = true
              return { ...n, deltas: f.deltas, rationale: f.rationale }
            }
            return n
          })
          return changed ? next : cur
        })
      } catch { /* try again */ }
      if (alive && tries < 40) timer = setTimeout(tick, 2200)
    }
    let timer = setTimeout(tick, 1800)
    return () => { alive = false; clearTimeout(timer) }
  }, [sid, unquantified, chain.status, nodes.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // live "what this adds up to"
  useEffect(() => {
    if (!nodes.length) { setShock(null); return undefined }
    let alive = true
    const t = setTimeout(() => {
      previewShock(nodes.filter((n) => n.description.trim()).map((n) => ({ ...n, deltas: n.deltas || null })))
        .then((r) => alive && setShock(r)).catch(() => {})
    }, 250)
    return () => { alive = false; clearTimeout(t) }
  }, [nodes])

  // autosave
  const first = useRef(true)
  useEffect(() => {
    if (!sid || chain.status !== 'ready') return undefined
    if (first.current) { first.current = false; return undefined }
    if (!nodes.length) return undefined
    setSaved('saving')
    const t = setTimeout(() => {
      saveChain(sid, {
        nodes: nodes.filter((n) => n.description.trim()),
        clarifications: questions.map((q) => ({ field: q.field, question: q.question, answer: answers[q.field]?.skipped ? '' : (answers[q.field]?.text || '') })),
      }).then(() => setSaved('saved')).catch(() => setSaved('failed'))
    }, 1400)
    return () => clearTimeout(t)
  }, [nodes]) // eslint-disable-line react-hooks/exhaustive-deps

  // actions
  const onToggle = (id) => change((cur) => setIncluded(cur, id, !cur.find((n) => n.id === id).included))
  const onRemove = (id) => { change((cur) => removeNode(cur, id)); setSelectedId(null); setEditingId(null) }
  const onAdd = (parentId) => {
    if (parentId == null && nodes.length) {            // nothing selected: continue from the end of the chain
      const parents = new Set(nodes.flatMap((n) => n.depends_on))
      parentId = [...nodes].reverse().find((n) => !parents.has(n.id))?.id ?? null
    }
    let newId = null
    change((cur) => { const r = addEffect(cur, parentId); newId = r.id; return r.nodes })
    setTimeout(() => { setSelectedId(newId); setEditingId(newId) }, 0)
  }
  const onCommit = (id, patch) => { change((cur) => patchNode(cur, id, { ...patch, deltas: undefined, rationale: undefined })); setEditingId(null) }
  const onCancelEdit = (id) => {
    const n = nodes.find((x) => x.id === id)
    if (n && !n.description.trim()) { setNodes((cur) => removeNode(cur, id)); setSelectedId(null) } // an empty new event is dropped
    setEditingId(null)
  }

  // questions
  const resolved = questions.filter((q) => { const a = answers[q.field]; return a && (a.skipped || a.text.trim()) }).length
  const questionsDone = resolved === questions.length
  const setAnswer = (field, patch) => setAnswers((prev) => ({ ...prev, [field]: { text: '', skipped: false, ...prev[field], ...patch } }))
  const stale = chain.status === 'ready' && questions.length > 0 && answersKey(questions, answers) !== generatedFor
  const edited = history.length > 0 || nodes.some((n) => n.added)

  const regenerate = async () => {
    if (edited && !window.confirm('Updating the chain replaces the events on screen, including your edits. Continue?')) return
    setRegenBusy(true)
    try { await onRegenerate() } finally { setRegenBusy(false) }
  }

  const kept = keptCount(nodes)
  const canRun = chain.status === 'ready' && kept >= 1 && questionsDone && !editingId

  const facts = useMemo(() => [
    ['Event', parsed.primary_event],
    ['Region', parsed.region || 'Not specified'],
    ['Horizon', parsed.time_horizon_months ? `${parsed.time_horizon_months} months` : 'Not specified'],
  ], [parsed])

  return (
    <div className="intake-screen intake-screen--wide studio">
      <div className="studio__head">
        <div>
          <p className="intake-eyebrow">Step 2 of 3 · Shape the chain of events</p>
          <h1 className="intake-title intake-title--md studio__title">Tell us more. Edit how it spreads.</h1>
        </div>
      </div>

      <div className="studio__cols">
        {/* ── inputs ── */}
        <section className="studio__inputs" aria-label="What we understood">
          <div className="studio__card">
            <h2 className="studio__h">What we understood</h2>
            <dl className="studio__facts">
              {facts.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
              <div><dt>Sectors</dt><dd className="studio__tags">
                {(parsed.affected_sectors || []).length ? parsed.affected_sectors.map((s) => <span className="intake-tag" key={s}>{s}</span>) : 'Not specified'}
              </dd></div>
            </dl>
            {(parsed.understood || []).length > 0 && (
              <ul className="intake-understood studio__understood">
                {parsed.understood.map((u, i) => (<li key={i}><Check /><span>{u}</span></li>))}
              </ul>
            )}
          </div>

          {questions.length > 0 && (
            <div className="studio__card">
              <h2 className="studio__h">Needs your input <span className="intake-count">{resolved} of {questions.length}</span></h2>
              {questions.map((q) => {
                const a = answers[q.field] || { text: '', skipped: false }
                const done = a.skipped || a.text.trim().length > 0
                return (
                  <div className={`intake-q ${done ? 'is-done' : ''}`} key={q.field}>
                    <p className="intake-q__text">{q.question}</p>
                    <div className="intake-q__row">
                      <input className="intake-input" placeholder={a.skipped ? 'Skipped' : 'Your answer'} value={a.text} disabled={a.skipped}
                        onChange={(e) => setAnswer(q.field, { text: e.target.value })} />
                      <button type="button" className="intake-btn intake-btn--ghost" onClick={() => setAnswer(q.field, { skipped: !a.skipped, text: '' })}>
                        {a.skipped ? 'Undo skip' : 'Skip'}
                      </button>
                    </div>
                  </div>
                )
              })}
              {stale && (
                <div className="studio__stale">
                  <span>Your answers changed after the chain was drawn.</span>
                  <button type="button" className="intake-btn intake-btn--ghost" disabled={regenBusy} onClick={regenerate}>
                    {regenBusy ? 'Redrawing…' : 'Redraw the chain with my answers'}
                  </button>
                </div>
              )}
            </div>
          )}

          <div className="studio__card studio__howto">
            <h2 className="studio__h">How to edit</h2>
            <ul>
              <li><b>Select</b> an event to light up everything that follows from it.</li>
              <li><b>Add effect</b> puts a new event after it; add two and the line branches.</li>
              <li><b>Exclude</b> keeps an event on the chart but stops it counting. <b>Delete</b> removes it.</li>
              <li>The kept chain goes back to Groq to be quantified and written up as the simulation brief.</li>
            </ul>
          </div>
        </section>

        {/* ── the chain ── */}
        <section className="studio__chain" aria-label="Chain of events">
          <div className="studio__bar">
            <div className="studio__count">
              <b>{chain.status === 'ready' ? `${kept} of ${nodes.length}` : '…'}</b> events kept
              {chain.status === 'ready' && saved && <span className={`studio__saved is-${saved}`}>{saved === 'saving' ? 'Saving…' : saved === 'saved' ? 'Saved' : 'Not saved'}</span>}
            </div>
            <div className="studio__actions">
              <button type="button" className="cg-btn" onClick={undo} disabled={!history.length}>Undo</button>
              <button type="button" className="cg-btn" onClick={() => onAdd(selectedId)} disabled={chain.status !== 'ready'}>
                {selectedId ? 'Add effect to selected' : '+ Add event'}
              </button>
            </div>
          </div>

          <div className="studio__scroll">
            {shock && chain.status === 'ready' && (
              <div className={`studio__shock ${shockOpen ? 'is-open' : ''}`}>
                <button type="button" className="studio__shockbtn" onClick={() => setShockOpen((o) => !o)} aria-expanded={shockOpen}>
                  <span className="studio__shockh">What this chain adds up to</span>
                  {!shockOpen && (
                    <span className="studio__shocksum">
                      {SHOCK_ROWS.map(([k, label]) => {
                        const v = Math.round((shock.shock[k] || 0) * 100)
                        return <span key={k}>{label.split(' ')[0]} <b>{v > 0 ? '+' : v < 0 ? '\u2212' : ''}{Math.abs(v)}%</b></span>
                      })}
                    </span>
                  )}
                  <span className="studio__chev" aria-hidden="true">{shockOpen ? 'Hide' : 'Details'}</span>
                </button>
                {shockOpen && <ShockBars shock={shock.shock} pending={shock.pending} compact />}
                {!shockOpen && shock.pending > 0 && <p className="shock__note">{shock.pending} {shock.pending === 1 ? 'event is' : 'events are'} still being quantified…</p>}
              </div>
            )}

            {chain.status === 'writing' && (
              <>
                <p className="studio__writing"><span className="intake-dots" aria-hidden="true"><i /><i /><i /></span>Groq is drawing how this spreads…</p>
                <ChainSkeleton />
              </>
            )}
            {chain.status === 'error' && (
              <div className="studio__error" role="alert">
                <p>{chain.error || 'The chain could not be drawn.'}</p>
                <button type="button" className="intake-btn intake-btn--primary" onClick={onRetryChain}>Try again</button>
              </div>
            )}
            {chain.status === 'ready' && nodes.length === 0 && (
              <div className="studio__empty">
                <p>The chain is empty.</p>
                <button type="button" className="cg-btn cg-btn--ink" onClick={() => onAdd(null)}>Add the first event</button>
              </div>
            )}
            {chain.status === 'ready' && nodes.length > 0 && (
              <ChainGraph
                mode="edit" nodes={nodes} selectedId={selectedId} onSelect={setSelectedId} editingId={editingId}
                onToggle={onToggle} onRemove={onRemove} onAdd={onAdd} onStartEdit={setEditingId}
                onCommit={onCommit} onCancelEdit={onCancelEdit}
              />
            )}
          </div>
        </section>
      </div>

      <div className="intake-bar studio__foot">
        <div className="intake-progress" aria-hidden="true">
          {questions.map((q, i) => {
            const a = answers[q.field]
            const done = a && (a.skipped || a.text.trim())
            return <i key={q.field} className={done ? 'is-on' : ''} style={{ '--i': i }} />
          })}
        </div>
        <button type="button" className="intake-btn intake-btn--ghost" onClick={onBack}>{resumed ? 'Back' : 'Edit scenario'}</button>
        <button type="button" className="intake-btn intake-btn--primary" disabled={!canRun}
          onClick={() => onRun({ nodes, kept })}>
          Run simulation
          <span className="intake-btn__arrow" aria-hidden="true">→</span>
        </button>
      </div>
      {!canRun && chain.status === 'ready' && (
        <p className="intake-hint">
          {!questionsDone ? 'Answer or skip every question to continue.' : kept < 1 ? 'Keep at least one event in the chain.' : editingId ? 'Save or cancel the event you are editing.' : ''}
        </p>
      )}
    </div>
  )
}
