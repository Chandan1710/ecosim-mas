/**
 * DashboardPage — one finished (or running) simulation on a single page.
 *
 *  top bar    the run switcher (a drop-down of every saved run; the whole page follows it) and jump links
 *  results    the headline, what happened in plain sentences, eight numbers, and who coped
 *  charts     who is struggling, day by day, and what things cost
 *  residents  every resident: status, cash across the run, what went wrong
 *  spread     the scenario's chain of events, as the flowchart from Event propagation
 *  brief      the brief Groq wrote (or the built-in explanation), the news residents heard and what to expect
 *  moments    the turning points in order
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './dashboard.css'
import ChainGraph from './ChainGraph'
import { Inspector } from './PropagationPage'
import ShockBars from './ShockBars'
import { LineChart, Sparkline, StatusBar, StatusDot, useOutside } from './DashCharts'
import { listTownRuns, reportUrl, townDashboard } from './api'
import { when } from './RunsTable'

const rupees = (v) => `₹${Math.round(v || 0).toLocaleString('en-IN')}`
const pct = (v, d = 0) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(d)}%`
const STORE_KEY = 'ecosim-dash-run'
const read = () => { try { return sessionStorage.getItem(STORE_KEY) } catch { return null } }
const write = (v) => { try { sessionStorage.setItem(STORE_KEY, v) } catch { /* private window */ } }

const STATE = { running: 'Running', done: 'Done', stopped: 'Stopped', failed: 'Failed', interrupted: 'Interrupted' }

/* ── the run switcher ─────────────────────────────────────────────────────── */
function RunPicker({ runs, current, onPick }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [cursor, setCursor] = useState(0)
  const box = useRef(null)
  const btn = useRef(null)
  const close = useCallback(() => { setOpen(false); setQ('') }, [])
  useOutside(box, close, open)

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return runs.filter((r) => !s || (r.title || '').toLowerCase().includes(s) || r.run_id.includes(s))
  }, [runs, q])
  const cur = runs.find((r) => r.run_id === current)

  useEffect(() => { if (open) setCursor(Math.max(0, shown.findIndex((r) => r.run_id === current))) }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const choose = (r) => { onPick(r.run_id); close(); btn.current?.focus() }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(shown.length - 1, c + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)) }
    else if (e.key === 'Enter' && shown[cursor]) { e.preventDefault(); choose(shown[cursor]) }
    else if (e.key === 'Escape') { close(); btn.current?.focus() }
  }
  useEffect(() => { // keep the highlighted row in view
    if (open) box.current?.querySelector('.dpick__opt.is-cursor')?.scrollIntoView({ block: 'nearest' })
  }, [cursor, open])

  return (
    <div className="dpick" ref={box}>
      <button type="button" ref={btn} className="dpick__btn" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}>
        <span className="dpick__lab">Simulation</span>
        <span className="dpick__cur">
          <b>{cur ? cur.title : 'Choose a run'}</b>
          {cur && <small>{when(cur.created_at)} · {cur.days_done ?? 0}/{cur.days} days · {STATE[cur.status] || cur.status}</small>}
        </span>
        <svg className="dpick__chev" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 5.2 7 9l4-3.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div className="dpick__pop" onKeyDown={onKey}>
          {runs.length > 6 && (
            <input className="dpick__search" autoFocus type="search" placeholder="Search runs" value={q}
              onChange={(e) => { setQ(e.target.value); setCursor(0) }} aria-label="Search runs" />
          )}
          <ul role="listbox" aria-label="Simulations" tabIndex={-1} ref={(el) => { if (el && runs.length <= 6) el.focus() }}>
            {shown.map((r, i) => (
              <li key={r.run_id} role="option" aria-selected={r.run_id === current}
                className={`dpick__opt ${r.run_id === current ? 'is-on' : ''} ${i === cursor ? 'is-cursor' : ''}`}
                onPointerEnter={() => setCursor(i)} onClick={() => choose(r)}>
                <span className="dpick__t">{r.title}</span>
                <span className="dpick__m">
                  <i className={`dpick__st is-${r.status}`} aria-hidden="true" />{STATE[r.status] || r.status} · {when(r.created_at)} · {r.days_done ?? 0}/{r.days} days
                </span>
                {!/=\s*[+-]?\d/.test(r.shock_text || '') && <span className="dpick__s">{r.shock_text}</span>}
              </li>
            ))}
            {shown.length === 0 && <li className="dpick__none">No run matches.</li>}
          </ul>
        </div>
      )}
    </div>
  )
}

/* ── small parts ──────────────────────────────────────────────────────────── */
function Tile({ label, value, sub, delta, goodWhen = 'down', i = 0 }) {
  let tone = 'flat'
  let arrow = ''
  if (delta != null && Math.abs(delta.raw) > 1e-9) {
    const up = delta.raw > 0
    arrow = up ? '▲' : '▼'
    tone = (goodWhen === 'up') === up ? 'good' : 'bad'
  }
  return (
    <div className="dtile" style={{ '--i': i }}>
      <div className="dtile__l">{label}</div>
      <div className="dtile__v">{value}</div>
      <div className="dtile__s">
        {delta != null && <span className={`dtile__d is-${tone}`}>{arrow && <i aria-hidden="true">{arrow}</i>}{delta.text}</span>}
        {sub && <span>{sub}</span>}
      </div>
    </div>
  )
}

function Section({ id, title, aside, children, refs }) {
  return (
    <section className="dsec" id={`dash-${id}`} ref={(el) => { if (refs) refs.current[id] = el }}>
      <header className="dsec__h"><h2>{title}</h2>{aside && <div className="dsec__a">{aside}</div>}</header>
      {children}
    </section>
  )
}

const FLAGS = (a) => [
  a.defaulted && ['Defaulted', 'bad'],
  !a.employed && ['No work', 'bad'],
  a.days_hungry > 0 && [`Hungry ${a.days_hungry}d`, 'bad'],
  a.used_moneylender && ['Moneylender', 'warn'],
].filter(Boolean)

function Residents({ agents, counts, onOpenAgent }) {
  const [f, setF] = useState('all')
  const rows = agents.filter((a) => f === 'all' || a.status === f)
  const lo = Math.min(...agents.map((a) => Math.min(a.start_money, a.end_money)), 0)
  void lo
  return (
    <>
      <div className="town-seg town-seg--small dres__filter" role="group" aria-label="Filter residents">
        {[['all', 'All', agents.length], ['In crisis', 'In crisis', counts['In crisis']], ['Under strain', 'Under strain', counts['Under strain']], ['Coping', 'Coping', counts.Coping]].map(([k, l, n]) => (
          <button type="button" key={k} className={f === k ? 'is-on' : ''} onClick={() => setF(k)}>{l} <small>{n || 0}</small></button>
        ))}
      </div>
      <div className="dres">
        <div className="dres__row dres__row--head" aria-hidden="true">
          <span>Resident</span><span>Status</span><span>Cash across the run</span><span className="dres__r">Start → end</span><span>What went wrong</span>
        </div>
        {rows.map((a, i) => {
          const change = a.start_money ? (a.end_money - a.start_money) / Math.abs(a.start_money) : 0
          const flags = FLAGS(a)
          return (
            <div className="dres__row" key={a.id} style={{ '--i': i }}>
              <span className="dres__who"><button type="button" className="dres__name" onClick={() => onOpenAgent(a.id)} title={`Open ${a.name}'s profile`}>{a.name}</button><small>{a.job}{a.age ? ` · ${a.age}` : ''}</small></span>
              <span className="dres__st"><StatusDot status={a.status} />{a.status}</span>
              <span className="dres__spark"><Sparkline values={a.money_series} /></span>
              <span className="dres__r dres__cash">{rupees(a.start_money)} → {rupees(a.end_money)}<small className={change < -0.05 ? 'is-bad' : change > 0.05 ? 'is-good' : ''}>{pct(change)}</small></span>
              <span className="dres__flags">{flags.length ? flags.map(([t, tone]) => <em key={t} className={`is-${tone}`}>{t}</em>) : <span className="dres__ok">Nothing serious</span>}</span>
            </div>
          )
        })}
        {rows.length === 0 && <p className="dres__none">No resident in this group.</p>}
      </div>
    </>
  )
}

function Moments({ events }) {
  const [all, setAll] = useState(false)
  const shown = all ? events : events.slice(0, 8)
  if (!events.length) return <p className="dsec__empty">No turning points were recorded in this run.</p>
  return (
    <>
      <ol className="dmom">
        {shown.map((e, i) => <li key={i}><span>Day {e.day}</span>{e.text}</li>)}
      </ol>
      {events.length > 8 && <button type="button" className="prop__link" onClick={() => setAll((a) => !a)}>{all ? 'Show fewer' : `Show all ${events.length}`}</button>}
    </>
  )
}

/* ── the page ─────────────────────────────────────────────────────────────── */
export default function DashboardPage({ lastRunId, onOpenRun, onOpenScenario, onOpenAgent, onOpenValidation, onHome }) {
  const [runs, setRuns] = useState(null)
  const [runId, setRunId] = useState(null)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [sel, setSel] = useState(null)
  const refs = useRef({})
  const scroller = useRef(null)

  // the list of runs, kept fresh while one of them is still running
  const loadRuns = useCallback(() => listTownRuns().then((l) => { setRuns(l); setErr('') }).catch((e) => setErr(e.message || 'Could not load the runs.')), [])
  useEffect(() => { loadRuns() }, [loadRuns])
  useEffect(() => {
    if (!runs) return
    if (runId && runs.some((r) => r.run_id === runId)) return
    const pick = [read(), lastRunId].find((id) => id && runs.some((r) => r.run_id === id)) || runs[0]?.run_id || null
    setRunId(pick)
  }, [runs, runId, lastRunId])

  const running = data?.run?.status === 'running'
  useEffect(() => {
    if (!runId) return undefined
    let alive = true
    const go = () => { setBusy(true); return townDashboard(runId).then((d) => { if (alive) { setData(d); setErr('') } }).catch((e) => alive && setErr(
      /409/.test(e.message || '') ? 'This run has not produced any events yet.' : (e.message || 'Could not load this run.'))).finally(() => alive && setBusy(false)) }
    go()
    const t = running ? setInterval(() => { go(); loadRuns() }, 3000) : null
    return () => { alive = false; if (t) clearInterval(t) }
  }, [runId, running, loadRuns])

  const pick = (id) => { write(id); setRunId(id); setSel(null) }
  const jump = (id) => refs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  const d = data && data.run.run_id === runId ? data : null
  const n = d?.agents.length || 0
  const k = d?.kpis
  const days = useMemo(() => (d ? d.series.map((r) => r.day) : []), [d])
  const prop = d?.propagation
  const brief = prop?.brief
  const heads = brief?.headlines?.length ? brief.headlines : prop?.headlines || []
  const text = brief?.brief || prop?.explain || prop?.description || ''
  const struggling = d ? (d.status_counts['In crisis'] || 0) + (d.status_counts['Under strain'] || 0) : 0
  // runs from a described scenario store the raw numbers as their shock text; show the scenario's own words instead
  const raw = /=\s*[+-]?\d/.test(d?.run.shock_text || '')
  const blurb = raw ? (prop?.description || '') : d?.run.shock_text
  const selected = prop?.nodes.find((x) => x.id === sel) || null

  if (runs && runs.length === 0) {
    return (
      <div className="dash" ref={scroller}>
        <div className="dash__empty">
          <h1>Dashboard</h1>
          <p>Nothing to show yet. Run a simulation and its results will appear here: who coped, what things cost, how the shock spread.</p>
          <button type="button" className="town-btn" onClick={onHome}>Go to Home</button>
        </div>
      </div>
    )
  }

  const priceRise = (v, end) => (end ? v / (end - v) : 0)
  return (
    <div className="dash" ref={scroller}>
      <div className="dbar">
        <div className="dbar__row">
          <h1 className="dbar__title">Dashboard</h1>
          {runs && runId && <RunPicker runs={runs} current={runId} onPick={pick} />}
          <div className="dbar__act">
            {d && <button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={() => onOpenRun(d.run.run_id)}>{running ? 'Watch live' : 'Replay in town'}</button>}
            {d?.run.source?.validation && <button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={() => onOpenValidation(d.run.run_id)}>Open scorecard</button>}
            {d && !running && <a className="town-btn town-btn--ghost town-btn--sm" href={reportUrl(d.run.run_id, 'summary')}>Summary PDF</a>}
          </div>
        </div>
        {d && (
          <nav className="dbar__nav" aria-label="On this page">
            {[['results', 'Results'], ['charts', 'Charts'], ['residents', 'Residents'], ['spread', 'Event propagation'], ['brief', 'Groq brief'], ['moments', 'Turning points']].map(([id, l]) => (
              <button type="button" key={id} onClick={() => jump(id)}>{l}</button>
            ))}
          </nav>
        )}
      </div>

      <div className={`dash__body ${busy && d ? 'is-busy' : ''}`}>
        {err && <p className="prop__error" role="alert">{err}</p>}
        {!d && !err && <p className="prop__loading">Loading the run…</p>}
        {d && (
          <>
            {/* results ─────────────────────────────────────────────────── */}
            <Section id="results" title="Results" refs={refs}>
              <div className="dhero" key={d.run.run_id}>
                <div className="dhero__txt">
                  <div className="prop__eyebrow">
                    <span className={`prop__badge is-${d.run.status === 'done' ? 'yours' : d.run.status === 'running' ? 'working' : 'draft'}`}>{STATE[d.run.status] || d.run.status}</span>
                    {when(d.run.created_at)} · {d.run.days_run} of {d.run.days_planned} days · {n} residents
                  </div>
                  <h2 className="dhero__title">{d.run.title}</h2>
                  {blurb && <p className="dhero__shock">{blurb}</p>}
                  {(d.run.rules || []).length > 0 && <div className="prop__tags">{d.run.rules.map((r) => <span key={r} className="prop__tag">{r}</span>)}</div>}
                  <ul className="dhero__find">{d.findings.map((s, i) => <li key={i} style={{ '--i': i }}>{s}</li>)}</ul>
                </div>
                <div className="dhero__fig">
                  <div className="dhero__n">{struggling}<span>/{n}</span></div>
                  <div className="dhero__cap">residents ended the run struggling</div>
                  <StatusBar counts={d.status_counts} />
                </div>
              </div>

              <div className="dtiles">
                <Tile i={0} label="Average cash" value={rupees(k.avg_money_end)} goodWhen="up"
                  delta={{ raw: k.avg_money_end - k.avg_money_start, text: pct(k.avg_money_start ? (k.avg_money_end - k.avg_money_start) / k.avg_money_start : 0) }} sub="since day 1" />
                <Tile i={1} label="Median cash" value={rupees(k.median_money_end)} goodWhen="up"
                  delta={{ raw: k.median_money_end - k.median_money_start, text: pct(k.median_money_start ? (k.median_money_end - k.median_money_start) / k.median_money_start : 0) }} sub="since day 1" />
                <Tile i={2} label="Groceries" value={`×${k.grocery_index_end.toFixed(2)}`}
                  delta={{ raw: k.grocery_price_change, text: pct(priceRise(k.grocery_price_change, k.grocery_index_end)) }} sub="vs day 1" />
                <Tile i={3} label="Fuel" value={`×${k.fuel_index_end.toFixed(2)}`}
                  delta={{ raw: k.fuel_price_change, text: pct(priceRise(k.fuel_price_change, k.fuel_index_end)) }} sub="vs day 1" />
                <Tile i={4} label="Owe the moneylender" value={`${k.moneylender_end}`} sub={`of ${n}`}
                  delta={{ raw: k.moneylender_end - k.moneylender_start, text: `${k.moneylender_end - k.moneylender_start >= 0 ? '+' : '−'}${Math.abs(k.moneylender_end - k.moneylender_start)}` }} />
                <Tile i={5} label="Without work" value={`${k.unemployed_end}`} sub={`of ${n}`} />
                <Tile i={6} label="Defaulted on a loan" value={`${k.defaulted_end}`} sub={`of ${n}`} />
                <Tile i={7} label="Went hungry" value={`${k.ever_hungry}`} sub={`of ${n} at least a day`} />
              </div>
            </Section>

            {/* charts ──────────────────────────────────────────────────── */}
            <Section id="charts" title="How it unfolded" refs={refs}>
              <div className="dcharts">
                <LineChart
                  title="Residents in trouble" days={days} band={[d.run.onset_day, d.run.full_day]} note={`Out of ${n} residents, each day.`}
                  series={[
                    { key: 'moneylender', label: 'Owe the moneylender', color: 'var(--series-1)', values: d.series.map((r) => r.moneylender) },
                    { key: 'unemployed', label: 'Without work', color: 'var(--series-2)', values: d.series.map((r) => r.unemployed) },
                    { key: 'low_food', label: 'Low on food', color: 'var(--series-3)', values: d.series.map((r) => r.low_food) },
                    { key: 'defaulted', label: 'Defaulted', color: 'var(--series-4)', values: d.series.map((r) => r.defaulted) },
                  ]}
                />
                <LineChart
                  title="What things cost" days={days} yMin={1} band={[d.run.onset_day, d.run.full_day]} note="Price index: 1.00 is what it cost before the shock."
                  fmt={(v) => v.toFixed(2)}
                  series={[
                    { key: 'groceries', label: 'Groceries', color: 'var(--series-1)', values: d.series.map((r) => r.groceries) },
                    { key: 'fuel', label: 'Fuel', color: 'var(--series-2)', values: d.series.map((r) => r.fuel) },
                  ]}
                />
                <LineChart
                  title="Average cash per resident" days={days} fmt={(v) => (v >= 1000 ? `₹${(v / 1000).toFixed(v % 1000 ? 1 : 0)}K` : `₹${Math.round(v)}`)} band={[d.run.onset_day, d.run.full_day]}
                  note="The mean across all residents, at the end of each day."
                  series={[{ key: 'cash', label: 'Average cash', color: 'var(--series-1)', values: d.series.map((r) => r.avg_money) }]}
                />
              </div>
            </Section>

            {/* residents ───────────────────────────────────────────────── */}
            <Section id="residents" title="Residents" aside={`${n} people · worst off first`} refs={refs}>
              <Residents agents={d.agents} counts={d.status_counts} onOpenAgent={onOpenAgent} />
            </Section>

            {/* event propagation ───────────────────────────────────────── */}
            <Section id="spread" title="Event propagation" refs={refs}
              aside={prop && <button type="button" className="prop__link" onClick={() => onOpenScenario(prop.key)}>Open in Event propagation →</button>}>
              {prop ? (
                <>
                  <p className="dsec__lead">How <b>{prop.title}</b> spreads through the town: each box is one event, and each line says what follows from what. Select one to see what it does to the numbers.</p>
                  <div className="prop__chainwrap">
                    <Inspector node={selected} nodes={prop.nodes} onJump={setSel} />
                    <div className="prop__chain"><ChainGraph nodes={prop.nodes} mode="view" selectedId={sel} onSelect={setSel} detail={false} /></div>
                  </div>
                </>
              ) : (
                d.run.source?.validation
                  ? <p className="dsec__empty">This is a validation run: the town was given only the real event's inputs, so there is no chain of events to show. Its scorecard is on the Validation page.</p>
                  : <p className="dsec__empty">The scenario this run was started from is no longer on file, so its chain of events can't be shown. The numbers it applied are below.</p>
              )}
              <div className="dcard dcard--shock">
                <div className="prop__cardh">What the scenario added up to (applied to the town)</div>
                <ShockBars shock={d.run.shock} compact />
              </div>
            </Section>

            {/* brief ───────────────────────────────────────────────────── */}
            <Section id="brief" title={brief ? 'The Groq brief' : 'About the scenario'} refs={refs}
              aside={brief && <span className={`prop__src is-${brief.source}`}>{brief.source === 'groq' ? 'Written by Groq' : brief.source === 'ollama' ? 'Written by Ollama' : 'Template: no LLM answered'}</span>}>
              {text ? (
                <div className="dbrief">
                  <div className="prop__prose">{String(text).split(/\n{2,}/).filter(Boolean).map((p, i) => <p key={i}>{p}</p>)}</div>
                  <div className="dbrief__side">
                    {heads.length > 0 && (
                      <div>
                        <div className="prop__cardh">The news residents heard, in order</div>
                        <ol className="prop__news">{heads.map((h, i) => <li key={i} style={{ '--i': i }}><span>{i + 1}</span>{h}</li>)}</ol>
                      </div>
                    )}
                  </div>
                </div>
              ) : <p className="dsec__empty">No brief was written for this scenario.</p>}
              {((brief?.effects || []).length > 0 || (prop?.watch || []).length > 0) && (
                <>
                  <h3 className="dsec__sub">{'What to watch for'}</h3>
                  <ul className="prop__watch">{(brief?.effects?.length ? brief.effects : prop.watch).map((w, i) => <li key={i}>{w}</li>)}</ul>
                </>
              )}
            </Section>

            {/* moments + under the hood ────────────────────────────────── */}
            <Section id="moments" title="Turning points" refs={refs}>
              <Moments events={d.key_events} />
            </Section>
          </>
        )}
      </div>
    </div>
  )
}
