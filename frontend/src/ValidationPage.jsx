/**
 * ValidationPage — "does the town behave roughly like the real thing?"
 *
 *  run        pick a real event (published figures, with sources) or type in your own; the town is given only what was
 *             imposed from outside, never the results
 *  scorecard  the town's results beside the real figures, each judged against a tolerance band
 *  history    earlier validation runs and their match score
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import './dashboard.css'
import './validation.css'
import { StatusDot } from './DashCharts'
import { validationEvents, startValidation, validationScorecard, validationRuns, stopTownRun } from './api'
import { when } from './RunsTable'

const KEY = 'ecosim-val-run'
const read = () => { try { return sessionStorage.getItem(KEY) } catch { return null } }
const write = (v) => { try { if (v) sessionStorage.setItem(KEY, v); else sessionStorage.removeItem(KEY) } catch { /* private window */ } }

const VERDICT = {
  close: { label: 'Close', dot: 'Coping', text: 'Inside the band' },
  roughly: { label: 'Roughly', dot: 'Under strain', text: 'Up to twice the band away, same direction' },
  off: { label: 'Off', dot: 'In crisis', text: 'Further away, or the wrong way' },
  unknown: { label: 'Not enough days', dot: null, text: 'Run is too short to measure this' },
}
const OVERALL = {
  close: 'Close to reality',
  roughly: 'Roughly right',
  off: 'Far from reality',
}
const SIGNED = new Set(['jobless_rise', 'income_change', 'spending_change'])

function fmt(measure, unit, v) {
  if (v == null) return '–'
  const n = Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 10) / 10
  const sign = SIGNED.has(measure) ? (v > 0 ? '+' : v < 0 ? '−' : '') : ''
  return `${sign}${Math.abs(n)}${unit === 'pp' ? ' pp' : '%'}`
}

/** real figure (tick, with its band) and the town's result (dot) on one shared scale */
function Dumbbell({ real, sim, band }) {
  const lo0 = Math.min(real - 2 * band, sim ?? real)
  const hi0 = Math.max(real + 2 * band, sim ?? real)
  const pad = (hi0 - lo0) * 0.06
  const lo = lo0 - pad
  const hi = hi0 + pad
  const at = (v) => `${((v - lo) / (hi - lo)) * 100}%`
  const zero = lo < 0 && hi > 0
  return (
    <div className="vdb" role="img" aria-label={`Real ${real}, town ${sim ?? 'not measured'}, band plus or minus ${band}`}>
      <div className="vdb__track" />
      {zero && <i className="vdb__zero" style={{ left: at(0) }} />}
      <i className="vdb__wide" style={{ left: at(real - 2 * band), width: `${(4 * band / (hi - lo)) * 100}%` }} />
      <i className="vdb__band" style={{ left: at(real - band), width: `${(2 * band / (hi - lo)) * 100}%` }} />
      <i className="vdb__real" style={{ left: at(real) }} />
      {sim != null && <>
        <i className="vdb__link" style={{ left: at(Math.min(real, sim)), width: `${(Math.abs(sim - real) / (hi - lo)) * 100}%` }} />
        <i className="vdb__sim" style={{ left: at(sim) }} />
      </>}
    </div>
  )
}

function Scorecard({ card, onDashboard, onStop, stopping }) {
  const running = card.run.status === 'running'
  const e = card.event
  const inputs = describeInputs(e.inputs)
  return (
    <div className="vcard" key={card.run.run_id}>
      <div className="vcard__top">
        <div>
          <div className="prop__eyebrow">
            <span className={`prop__badge is-${running ? 'working' : 'yours'}`}>{running ? 'Running' : 'Finished'}</span>
            {when(card.run.created_at)} · {card.run.days_done} of {card.run.days} days · {card.run.brain === 'llm' ? 'language model' : 'offline mock brain'}
          </div>
          <h2 className="vcard__title">{e.title}</h2>
          {e.summary && <p className="vcard__sum">{e.summary}</p>}
          <div className="vcard__in"><span>Given to the town</span>{inputs.map((t) => <em key={t}>{t}</em>)}</div>
        </div>
        <div className="vscore">
          {card.score == null ? (
            <div className="vscore__wait">{running ? 'Waiting for enough days…' : 'Nothing to score'}</div>
          ) : (
            <>
              <div className="vscore__n">{card.score}<span>%</span></div>
              <div className={`vscore__v is-${card.verdict}`}>{card.verdict && <StatusDot status={VERDICT[card.verdict].dot} />}{OVERALL[card.verdict]}{running ? ' so far' : ''}</div>
              <div className="vscore__c">{card.counts.close} close · {card.counts.roughly} roughly · {card.counts.off} off{card.counts.unknown ? ` · ${card.counts.unknown} unmeasured` : ''}</div>
            </>
          )}
          <div className="vscore__act">
            {running && <button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={onStop} disabled={stopping}>Stop run</button>}
            <button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={onDashboard}>Open in Dashboard</button>
          </div>
        </div>
      </div>

      <div className="vkey" aria-hidden="true">
        <span><i className="vkey__band" />Real figure, with its band</span>
        <span><i className="vkey__sim" />What the town produced</span>
      </div>
      <div className="vtable" role="table" aria-label="Real figures against the town">
        <div className="vrow vrow--head" role="row" aria-hidden="true">
          <span>What was measured</span><span className="vr">Real</span><span className="vr">Town</span><span>Where they sit</span><span>Verdict</span>
        </div>
        {card.rows.map((r, i) => {
          const v = VERDICT[r.verdict]
          return (
            <div className="vrow" role="row" key={`${r.measure}-${i}`} style={{ '--i': i }}>
              <span className="vwhat">
                <b>{r.label}</b>
                <small>{r.group}</small>
                <details><summary>How measured, and the source</summary>
                  <p>{r.how}</p>
                  <p>Town figure is the effect of the event: the run minus the same days with no shock{r.control != null ? ` (event ${fmt(r.measure, r.unit, r.raw)}, no shock ${fmt(r.measure, r.unit, r.control)})` : ''}.</p>
                  <p>{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.source}</a> : r.source}</p>
                </details>
              </span>
              <span className="vr vnum">{fmt(r.measure, r.unit, r.real)}</span>
              <span className="vr vnum">{fmt(r.measure, r.unit, r.sim)}</span>
              <span className="vwhere"><Dumbbell real={r.real} sim={r.sim} band={r.band} />
                <small>{r.gap == null ? '' : `${r.gap > 0 ? '+' : r.gap < 0 ? '−' : ''}${Math.abs(r.gap)} ${r.unit === 'pp' ? 'pp' : 'points'} from real · band ±${r.band}`}</small></span>
              <span className={`vverdict is-${r.verdict}`} title={v.text}>{v.dot ? <StatusDot status={v.dot} /> : <i className="vverdict__none" />}{v.label}</span>
            </div>
          )
        })}
      </div>

      <div className="vnotes">
        <div>
          <h3>How to read this</h3>
          <p>The town was given only the inputs above and never saw the real results. Its effect is measured as the run minus the same days with no shock, because even a calm town drifts a little.</p>
          <p>{card.band_rule} With 20 residents one person is 5 points, so being <i>around</i> the real figure is the most this can show; it is not expected to match exactly.</p>
        </div>
        {e.caveats && <div><h3>Limits of this comparison</h3><p>{e.caveats}</p></div>}
      </div>
    </div>
  )
}

function describeInputs(i = {}) {
  const t = []
  if (i.lockdown) t.push('Stay-at-home order, only essential shops open')
  if (i.essential_cost) t.push(`Essentials ${i.essential_cost > 0 ? '' : 'cheaper by '}${Math.abs(Math.round(i.essential_cost * 100))}%${i.essential_cost > 0 ? ' dearer' : ''}`)
  if (i.demand) t.push(`People cut spending by ${Math.abs(Math.round(i.demand * 100))}%`)
  if (i.credit_tightness) t.push(`Banks lend ${Math.abs(Math.round(i.credit_tightness * 100))}% ${i.credit_tightness > 0 ? 'less' : 'more'}`)
  return t.length ? t : ['No change at all']
}

const DAY_CHOICES = [[10, '10 days, quick'], [20, '20 days'], [30, '30 days, closest to a real month']]

function EventCard({ ev, busy, onRun, measures }) {
  const [days, setDays] = useState(ev.run.days)
  return (
    <article className="vev">
      <header><h3>{ev.title}</h3></header>
      <p className="vev__sum">{ev.summary}</p>
      <div className="vev__cols">
        <div>
          <div className="prop__cardh">Given to the town</div>
          <ul className="vev__ul">{describeInputs(ev.inputs).map((t) => <li key={t}>{t}</li>)}</ul>
          <p className="vev__note">{ev.inputs.note}</p>
        </div>
        <div>
          <div className="prop__cardh">Compared with ({ev.outcomes.length})</div>
          <ul className="vev__ul">
            {ev.outcomes.map((o, i) => (
              <li key={i}>{o.label} <b>{fmt(o.measure, measures[o.measure]?.unit, o.real)}</b>
                <small>{o.url ? <a href={o.url} target="_blank" rel="noreferrer">{o.source.split(':')[0]}</a> : o.source}</small></li>
            ))}
          </ul>
        </div>
      </div>
      <footer>
        <label>Run for <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {DAY_CHOICES.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
        </select></label>
        <button type="button" className="town-btn" disabled={busy} onClick={() => onRun({ event_id: ev.id, days })}>Run validation</button>
      </footer>
    </article>
  )
}

const BLANK_ROW = { measure: 'borrowed', group: 'all', real: '', source: '' }

function CustomForm({ busy, onRun, meta }) {
  const [f, setF] = useState({ title: '', summary: '', lockdown: false, essential: '', demand: '', credit: '', days: 20 })
  const [rows, setRows] = useState([{ ...BLANK_ROW }])
  const [err, setErr] = useState('')
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }))
  const setRow = (i, k, v) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  const pct = (v) => (v === '' || isNaN(Number(v)) ? 0 : Number(v) / 100)
  const submit = () => {
    setErr('')
    const outcomes = rows.filter((r) => r.real !== '' && !isNaN(Number(r.real))).map((r) => ({ ...r, real: Number(r.real) }))
    if (!f.title.trim()) return setErr('Give the event a name.')
    if (!outcomes.length) return setErr('Enter at least one real figure to compare with.')
    onRun({
      title: f.title.trim(), summary: f.summary.trim(), days: f.days, outcomes,
      inputs: { lockdown: f.lockdown, essential_cost: pct(f.essential), demand: -Math.abs(pct(f.demand)), credit_tightness: pct(f.credit) },
    })
  }
  return (
    <div className="vform">
      <p className="vform__lead">Describe an event that really happened, say what was imposed, then add the published figures for what followed. Only the first part is given to the town.</p>
      <div className="vform__grid">
        <label className="vf vf--wide">Name of the event
          <input type="text" maxLength={120} value={f.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Onion export ban, December 2023" /></label>
        <label className="vf vf--wide">One line about it (optional)
          <input type="text" maxLength={300} value={f.summary} onChange={(e) => set('summary', e.target.value)} /></label>
      </div>

      <div className="prop__cardh vform__h">1. What was imposed (given to the town)</div>
      <div className="vform__grid vform__grid--4">
        <label className="vf">Essentials dearer by (%)<input type="number" min="-60" max="60" value={f.essential} onChange={(e) => set('essential', e.target.value)} placeholder="0" /></label>
        <label className="vf">People cut spending by (%)<input type="number" min="0" max="60" value={f.demand} onChange={(e) => set('demand', e.target.value)} placeholder="0" /></label>
        <label className="vf">Banks lend less by (%)<input type="number" min="-60" max="60" value={f.credit} onChange={(e) => set('credit', e.target.value)} placeholder="0" /></label>
        <label className="vf vf--check"><input type="checkbox" checked={f.lockdown} onChange={(e) => set('lockdown', e.target.checked)} /> Stay-at-home order</label>
      </div>
      <p className="vform__hint">Use only things that were imposed from outside. Job losses, hunger and borrowing are results, so they go below.</p>

      <div className="prop__cardh vform__h">2. What really happened (compared, never given to the town)</div>
      <div className="vform__rows">
        {rows.map((r, i) => (
          <div className="vform__row" key={i}>
            <select value={r.measure} onChange={(e) => setRow(i, 'measure', e.target.value)} aria-label="What was measured">
              {Object.entries(meta.measures).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
            </select>
            <select value={r.group} onChange={(e) => setRow(i, 'group', e.target.value)} aria-label="Which residents">
              {Object.entries(meta.groups).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <input type="number" step="any" value={r.real} onChange={(e) => setRow(i, 'real', e.target.value)} placeholder={meta.measures[r.measure]?.unit === 'pp' ? 'points' : '%'} aria-label="Real figure" />
            <input type="text" value={r.source} maxLength={200} onChange={(e) => setRow(i, 'source', e.target.value)} placeholder="Source (e.g. survey name, year)" aria-label="Source" />
            {rows.length > 1 && <button type="button" className="vform__x" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} aria-label="Remove this figure">×</button>}
          </div>
        ))}
      </div>
      <div className="vform__hint">{meta.measures[rows[rows.length - 1]?.measure]?.how}</div>
      {rows.length < 6 && <button type="button" className="prop__link vform__add" onClick={() => setRows((rs) => [...rs, { ...BLANK_ROW }])}>+ Add another figure</button>}

      {err && <p className="prop__error" role="alert">{err}</p>}
      <footer className="vform__foot">
        <label>Run for <select value={f.days} onChange={(e) => set('days', Number(e.target.value))}>
          {DAY_CHOICES.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
        </select></label>
        <button type="button" className="town-btn" disabled={busy} onClick={submit}>Run validation</button>
      </footer>
    </div>
  )
}

export default function ValidationPage({ onOpenDashboard }) {
  const [meta, setMeta] = useState(null)
  const [tab, setTab] = useState('events')
  const [runs, setRuns] = useState(null)
  const [sel, setSel] = useState(read())
  const [card, setCard] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [stopping, setStopping] = useState(false)
  const cardRef = useRef(null)

  const loadRuns = useCallback(() => validationRuns().then((l) => { setRuns(l); return l }).catch(() => setRuns([])), [])
  useEffect(() => { validationEvents().then(setMeta).catch((e) => setErr(/404|not found/i.test(e.message || '') ? 'The running backend is out of date and has no validation endpoints yet. Stop it (Ctrl+C) and run ./start.sh again, then reload this page.' : (e.message || 'Could not load the events.'))) }, [])
  useEffect(() => { loadRuns().then((l) => { if (!read() && l && l[0]) { setSel(l[0].run_id) } }) }, [loadRuns])

  const running = card?.run?.status === 'running'
  useEffect(() => {
    if (!sel) { setCard(null); return undefined }
    let alive = true
    const go = () => validationScorecard(sel).then((c) => { if (alive) { setCard(c); setErr('') } })
      .catch((e) => { if (alive) { if (/409/.test(e.message || '')) setCard(null); else { setCard(null); setErr(e.message || 'Could not load the scorecard.') } } })
    go()
    const t = running || card == null ? setInterval(() => { go(); loadRuns() }, 3000) : null
    return () => { alive = false; if (t) clearInterval(t) }
  }, [sel, running, card == null]) // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (id) => { write(id); setSel(id); setCard(null); setErr('') }
  const run = async (body) => {
    setBusy(true); setErr('')
    try {
      const m = await startValidation(body)
      pick(m.run_id); loadRuns()
      setTimeout(() => cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120)
    } catch (e) { setErr(e.message || 'Could not start the run.') } finally { setBusy(false) }
  }
  const stop = () => { setStopping(true); stopTownRun(sel).catch(() => {}).finally(() => setStopping(false)) }
  const locked = busy || (runs || []).some((r) => r.status === 'running')

  return (
    <div className="dash val">
      <div className="vwrap">
        <h1 className="vh">Validation</h1>
        <p className="vlede">Does the town behave like the real thing? Pick something that really happened. The town is given only what was imposed, such as a lockdown, and never told what followed. Then what it produced is set beside the published figures.</p>
        {err && <p className="prop__error" role="alert">{err}</p>}
        {locked && !busy && <p className="vbanner" role="status">A validation run is going. Only one run can go at a time, so new ones start when it finishes.</p>}

        <div className="town-seg vtabs" role="group" aria-label="Choose an event">
          <button type="button" className={tab === 'events' ? 'is-on' : ''} onClick={() => setTab('events')}>Real events</button>
          <button type="button" className={tab === 'custom' ? 'is-on' : ''} onClick={() => setTab('custom')}>Your own event</button>
        </div>

        {!meta && !err && <p className="prop__loading">Loading…</p>}
        {meta && tab === 'events' && (
          <div className="vevs">{meta.events.map((ev) => <EventCard key={ev.id} ev={ev} busy={locked} measures={meta.measures} onRun={run} />)}</div>
        )}
        {meta && tab === 'custom' && <CustomForm busy={locked} onRun={run} meta={meta} />}

        <section className="vsec" ref={cardRef}>
          <h2 className="vsec__h">Scorecard</h2>
          {card ? <Scorecard card={card} onDashboard={() => onOpenDashboard(card.run.run_id)} onStop={stop} stopping={stopping} />
            : <p className="vsec__empty">{sel && !err ? 'Waiting for the first day to finish…' : 'Run a validation above, or open an earlier one below.'}</p>}
        </section>

        {runs && runs.length > 0 && (
          <section className="vsec">
            <h2 className="vsec__h">Earlier validation runs</h2>
            <div className="vhist">
              {runs.map((r) => (
                <button type="button" key={r.run_id} className={`vhist__row ${r.run_id === sel ? 'is-on' : ''}`} onClick={() => { pick(r.run_id); cardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}>
                  <span className="vhist__t"><b>{r.title.replace(/^Validation: /, '')}</b><small>{when(r.created_at)} · {r.days_done ?? 0}/{r.days} days · {r.brain === 'llm' ? 'language model' : 'mock brain'}</small></span>
                  <span className={`vhist__s is-${r.verdict || r.status}`}>
                    {r.score != null ? <><StatusDot status={VERDICT[r.verdict].dot} />{r.score}% · {OVERALL[r.verdict]}</> : r.status === 'running' ? 'Running…' : r.status}
                  </span>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
