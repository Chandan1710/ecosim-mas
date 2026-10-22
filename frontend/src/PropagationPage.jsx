/**
 * PropagationPage — "Event propagation" in the sidebar.
 *
 * Every scenario the town can run, with how its shock spreads: the seven ready-made ones (hand-written chains that
 * match what the simulator actually does), the ones you described yourself (a chain Groq drew and you edited, plus the
 * detailed brief it wrote), and drafts you have not run yet. Pick one on the left; on the right you get the
 * explanation, the flowchart, what it adds up to, the news the residents hear, and the runs made from it.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import './propagation.css'
import ChainGraph, { CATEGORIES, CATEGORY_LABEL, DeltaChips, Magnitude } from './ChainGraph'
import { layoutChain } from './chainLayout'
import ShockBars from './ShockBars'
import { forgetChain, forgetMany, keepOnlyChain, previewShock, propagationList, startTownRun } from './api'

const FILTERS = [['all', 'All'], ['yours', 'Yours'], ['builtin', 'Built-in'], ['draft', 'Drafts']]

const when = (t) => (t ? new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '')

function statusOf(r) {
  if (r.kind === 'preset') return { id: 'builtin', label: 'Built-in' }
  if (r.working) return { id: 'working', label: 'Writing brief' }
  if (r.status === 'ready' && !r.legacy) return { id: 'yours', label: 'Yours' }
  if (r.status === 'ready') return { id: 'yours', label: 'Yours' }
  return { id: 'draft', label: r.status === 'failed' ? 'Needs attention' : 'Draft' }
}

/** a small picture of a chain's shape: dots for events, lines for what follows what */
export function ChainGlyph({ nodes, width = 56, height = 44, animate = false }) {
  const L = useMemo(() => layoutChain(nodes), [nodes])
  const rows = Math.max(1, L.rows.length)
  const sx = L.lanes > 1 ? (width - 12) / (L.lanes - 1) : 0
  const sy = rows > 1 ? (height - 12) / (rows - 1) : 0
  const at = (id) => {
    const p = L.pos.get(id)
    return [L.lanes > 1 ? 6 + p.lane * sx : width / 2, rows > 1 ? 6 + p.row * sy : height / 2]
  }
  return (
    <svg className={`glyph ${animate ? 'glyph--in' : ''}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      {L.edges.map((e, i) => {
        const [x1, y1] = at(e.from)
        const [x2, y2] = at(e.to)
        const my = (y1 + y2) / 2
        return <path key={i} pathLength="1" className="glyph__edge" d={x1 === x2 ? `M${x1} ${y1} L${x2} ${y2}` : `M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}`} style={{ '--i': i }} />
      })}
      {nodes.map((n) => {
        const [x, y] = at(n.id)
        return <circle key={n.id} className={`glyph__dot cat-${n.category} ${n.included ? '' : 'is-off'}`} cx={x} cy={y} r={width > 100 ? 4.2 : 2.6} style={{ '--i': L.number.get(n.id) }} />
      })}
    </svg>
  )
}

function Rail({ items, current, onPick, filter, setFilter, query, setQuery, onDescribe, tidy, marked, onToggleMark, onStartTidy, onCancelTidy, onApplyTidy }) {
  return (
    <aside className="prop__rail" aria-label="Scenarios">
      <div className="prop__railhead">
        <h1 className="prop__h1">Event propagation</h1>
        <p className="prop__lede">How each shock spreads through the town: the chain of events behind every scenario.</p>
        <button type="button" className="prop__new" onClick={onDescribe}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg>
          New scenario
        </button>
        {!tidy && <button type="button" className="prop__link prop__tidylink" onClick={onStartTidy}>Tidy up my scenarios</button>}
        {tidy && (
          <div className="prop__tidybar" role="group" aria-label="Tidy up">
            <p>Ticked scenarios will be forgotten. Built-in ones are never touched. I left one of each kind unticked; change it as you like.</p>
            <div>
              <button type="button" className="town-btn town-btn--sm" disabled={!marked.size} onClick={onApplyTidy}>Forget {marked.size}</button>
              <button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={onCancelTidy}>Cancel</button>
            </div>
          </div>
        )}
        <input className="prop__search" type="search" placeholder="Search scenarios" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search scenarios" />
        <div className="town-seg town-seg--small prop__filter" role="group" aria-label="Filter">
          {FILTERS.map(([k, l]) => <button type="button" key={k} className={filter === k ? 'is-on' : ''} onClick={() => setFilter(k)}>{l}</button>)}
        </div>
      </div>
      <ul className="prop__list">
        {items.map((r, i) => {
          const st = statusOf(r)
          return (
            <li key={r.key} style={{ '--i': i }} className={tidy ? 'is-tidy' : ''}>
              {tidy && r.kind === 'custom' && (
                <input type="checkbox" className="prop__check" checked={marked.has(r.key)} onChange={() => onToggleMark(r.key)} aria-label={`Forget ${r.title}`} />
              )}
              <button type="button" className={`prop__item ${current === r.key ? 'is-on' : ''}`} onClick={() => onPick(r.key)} aria-current={current === r.key}>
                <span className="prop__glyph"><ChainGlyph nodes={r.nodes} /></span>
                <span className="prop__itemtxt">
                  <span className="prop__itemt">{r.title}</span>
                  <span className="prop__itemm">
                    <span className={`prop__badge is-${st.id}`}>{st.label}</span>
                    {r.nodes.filter((n) => n.included).length} events · {r.runs.length} {r.runs.length === 1 ? 'run' : 'runs'}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
        {items.length === 0 && <li className="prop__none">Nothing matches.</li>}
      </ul>
    </aside>
  )
}

export function Inspector({ node, nodes, onJump }) {
  if (!node) {
    return (
      <div className="prop__insp prop__insp--empty">
        <p>Select an event in the chain to see how it works, what it does to the numbers, and what follows from it.</p>
      </div>
    )
  }
  const L = layoutChain(nodes)
  const num = (id) => L.number.get(id)
  const causes = (node.depends_on || []).map((id) => nodes.find((n) => n.id === id)).filter(Boolean)
  const effects = nodes.filter((n) => (n.depends_on || []).includes(node.id))
  const Links = ({ list }) => (
    <ul className="prop__links">{list.map((c) => <li key={c.id}><button type="button" onClick={() => onJump(c.id)} title={c.description}><b>{num(c.id)}</b>{c.description}</button></li>)}</ul>
  )
  return (
    <div className={`prop__insp cat-${node.category}`} key={node.id}>
      <div className="prop__insp-a">
        <div className="prop__inspn"><b>{num(node.id)}</b>{CATEGORY_LABEL[node.category]}<Magnitude value={node.magnitude} /><span className="prop__conf">Confidence {Math.round((node.confidence ?? 0) * 100)}%</span></div>
        <p className="prop__inspt">{node.description}</p>
        {(node.note || node.rationale) && <p className="prop__inspd">{node.note || node.rationale}</p>}
        {causes.length === 0 && <p className="prop__inspd prop__inspd--quiet">This is the trigger. Everything else follows from it.</p>}
      </div>
      <div className="prop__insp-b">
        {node.deltas && <div><div className="prop__inspk">What it does to the numbers</div><DeltaChips deltas={node.deltas} /></div>}
        {causes.length > 0 && <div><div className="prop__inspk">Follows from</div><Links list={causes} /></div>}
        {effects.length > 0 && <div><div className="prop__inspk">Leads to</div><Links list={effects} /></div>}
      </div>
    </div>
  )
}

function Detail({ rec, days, seed, onOpenRun, onEdit, onForget, onKeepOnly, onChanged }) {
  const [sel, setSel] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { setSel(null); setErr('') }, [rec.key])

  const nodes = rec.nodes
  const st = statusOf(rec)
  const kept = nodes.filter((n) => n.included)
  const L = useMemo(() => layoutChain(kept), [kept])
  const branches = kept.filter((n) => kept.filter((m) => (m.depends_on || []).includes(n.id)).length > 1).length
  const used = [...new Set(kept.map((n) => n.category))]
  const brief = rec.brief
  const heads = brief?.headlines?.length ? brief.headlines : rec.headlines || []
  const text = brief?.brief || rec.explain || rec.description
  const paragraphs = String(text || '').split(/\n{2,}/).filter(Boolean)
  const selected = nodes.find((n) => n.id === sel) || null

  const run = async () => {
    setBusy(true)
    setErr('')
    try {
      const body = rec.kind === 'preset' ? { preset: rec.preset_id } : { scenario_id: rec.scenario_id, title: rec.title }
      const meta = await startTownRun({ ...body, days, seed })
      onOpenRun(meta.run_id)
    } catch (e) {
      setErr(e.message)
      setBusy(false)
    }
  }
  const canRun = rec.kind === 'preset' || (rec.status === 'ready' && !rec.working)

  return (
    <article className="prop__detail" key={rec.key}>
      <header className="prop__hero">
        <div className="prop__herotxt">
          <div className="prop__eyebrow">
            <span className={`prop__badge is-${st.id}`}>{st.label}</span>
            {rec.kind === 'preset' ? 'Ready-made scenario' : rec.legacy ? 'Your scenario · made earlier' : 'Your scenario'}
            {rec.updated_at && rec.kind === 'custom' && <span> · {when(rec.updated_at)}</span>}
          </div>
          <h2 className="prop__title">{rec.title}</h2>
          <p className="prop__desc">{rec.description}</p>
          {(rec.tags || []).length > 0 && <div className="prop__tags">{rec.tags.map((t) => <span key={t} className="prop__tag">{t}</span>)}</div>}
          <div className="prop__actions">
            <button type="button" className="town-btn" onClick={run} disabled={busy || !canRun}>{busy ? 'Starting…' : rec.runs.length ? 'Run again →' : 'Run this scenario →'}</button>
            {rec.editable && <button type="button" className="town-btn town-btn--ghost" onClick={() => onEdit(rec)} disabled={rec.working}>Edit the chain</button>}
            {rec.editable && <button type="button" className="prop__link" onClick={() => onForget(rec)}>Forget</button>}
            {rec.editable && <button type="button" className="prop__link" onClick={() => onKeepOnly(rec)}>Forget all my others</button>}
            {err && <span className="prop__err" role="alert">{err}</span>}
          </div>
        </div>
        <div className="prop__heroart" aria-hidden="true"><ChainGlyph nodes={nodes} width={190} height={150} animate /></div>
      </header>

      <dl className="prop__stats">
        <div><dt>Events</dt><dd>{kept.length}{nodes.length !== kept.length && <small> of {nodes.length}</small>}</dd></div>
        <div><dt>Branches</dt><dd>{branches}</dd></div>
        <div><dt>Steps deep</dt><dd>{L.rows.length}</dd></div>
        <div><dt>Runs</dt><dd>{rec.runs.length}</dd></div>
        <div><dt>Chain by</dt><dd className="prop__stat-sm">{rec.kind === 'preset' ? 'Hand-written' : 'Groq, edited by you'}</dd></div>
      </dl>

      <section className="prop__sec">
        <h3 className="prop__sech">{brief ? 'The simulation brief' : 'How it spreads'}
          {brief && <span className={`prop__src is-${brief.source}`}>{brief.source === 'groq' ? 'Written by Groq' : brief.source === 'ollama' ? 'Written by Ollama' : 'Template: no LLM answered'}</span>}
        </h3>
        <div className="prop__two">
          <div className="prop__prose">{paragraphs.map((p, i) => <p key={i}>{p}</p>)}</div>
          <div className="prop__side">
            <div className="prop__card">
              <div className="prop__cardh">What it adds up to</div>
              {rec.kind === 'custom' ? <Shocky nodes={nodes} fallback={rec.shock} /> : <ShockBars shock={rec.shock} compact />}
              {rec.shock_text && <p className="prop__cardn">{rec.shock_text}</p>}
            </div>
            {(rec.rules || []).length > 0 && (
              <div className="prop__card"><div className="prop__cardh">Rules the town enforces</div>
                <ul className="prop__ul">{rec.rules.map((r) => <li key={r}>{r}</li>)}</ul></div>
            )}
          </div>
        </div>
      </section>

      <section className="prop__sec">
        <h3 className="prop__sech">The chain of events
          <span className="prop__legend">{used.map((c) => <span key={c} className={`cat-${c}`}><i />{CATEGORY_LABEL[c]}</span>)}</span>
        </h3>
        <div className="prop__chainwrap">
          <Inspector node={selected} nodes={nodes} onJump={setSel} />
          <div className="prop__chain">
            <ChainGraph nodes={nodes} mode="view" selectedId={sel} onSelect={setSel} detail={false} />
          </div>
        </div>
      </section>

      {heads.length > 0 && (
        <section className="prop__sec">
          <h3 className="prop__sech">What the residents hear <small>in the order it reaches the town</small></h3>
          <ol className="prop__news">
            {heads.map((h, i) => <li key={i} style={{ '--i': i }}><span>{i + 1}</span>{h}</li>)}
          </ol>
        </section>
      )}

      {((brief?.effects || []).length > 0 || (rec.watch || []).length > 0) && (
        <section className="prop__sec">
          <h3 className="prop__sech">{brief ? 'What residents will feel' : 'What to watch in a run'}</h3>
          <ul className="prop__watch">
            {(brief?.effects?.length ? brief.effects : rec.watch).map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </section>
      )}

      <section className="prop__sec">
        <h3 className="prop__sech">Runs from this scenario</h3>
        {rec.runs.length === 0 ? (
          <p className="prop__empty">Not simulated yet. {canRun ? 'Run it to watch the twenty residents live through this chain.' : 'Finish the chain, then run it.'}</p>
        ) : (
          <table className="prop__runs">
            <thead><tr><th>Started</th><th>Status</th><th>Days</th><th>Moneylender</th><th>Defaults</th><th>No work</th><th /></tr></thead>
            <tbody>
              {rec.runs.map((r) => (
                <tr key={r.run_id}>
                  <td>{when(r.created_at)}<span className="prop__rid">{r.run_id}</span></td>
                  <td className={`prop__st is-${r.status}`}>{r.status === 'done' ? 'Done' : r.status === 'running' ? 'Running' : r.status}</td>
                  <td>{r.days_done ?? 0}/{r.days}</td>
                  <td>{r.town?.moneylender_borrowers ?? '–'}</td>
                  <td>{r.town?.defaulted ?? '–'}</td>
                  <td>{r.town?.unemployed ?? '–'}</td>
                  <td className="prop__rt"><button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={() => onOpenRun(r.run_id)}>{r.status === 'running' ? 'Watch' : 'Replay'}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </article>
  )
}

/** the shock of a custom scenario's kept events, from the numbers already on the nodes */
function Shocky({ nodes, fallback }) {
  const [res, setRes] = useState(null)
  useEffect(() => {
    let alive = true
    previewShock(nodes.map((n) => ({ ...n, deltas: n.deltas || null }))).then((r) => alive && setRes(r)).catch(() => {})
    return () => { alive = false }
  }, [nodes])
  return <ShockBars shock={res?.shock || fallback} pending={res?.pending || 0} compact />
}

export default function PropagationPage({ onOpenRun, onEdit, onDescribe, days = 7, seed = 7 }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [key, setKey] = useState(() => { try { return sessionStorage.getItem('ecosim-prop') || null } catch { return null } })
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [tidy, setTidy] = useState(false)
  const [marked, setMarked] = useState(() => new Set())

  const load = useCallback(() => propagationList().then((d) => { setData(d); setErr('') }).catch((e) => setErr(
    /not found|404/i.test(e.message || '') ? 'The page opened, but the running backend is out of date and has no event propagation endpoint yet. Stop it (Ctrl+C) and run ./start.sh again, then reload this page.' : (e.message || 'Could not load the scenarios.'))), [])
  useEffect(() => { load() }, [load])
  // while a brief is being written, keep refreshing
  useEffect(() => {
    if (!data?.items.some((r) => r.working)) return undefined
    const t = setInterval(load, 2500)
    return () => clearInterval(t)
  }, [data, load])

  const items = useMemo(() => (data?.items || []).filter((r) => {
    const st = statusOf(r).id
    if (filter === 'yours' && !(st === 'yours' || st === 'working')) return false
    if (filter === 'builtin' && st !== 'builtin') return false
    if (filter === 'draft' && st !== 'draft') return false
    const q = query.trim().toLowerCase()
    return !q || r.title.toLowerCase().includes(q) || (r.description || '').toLowerCase().includes(q)
  }), [data, filter, query])

  const current = (data?.items || []).find((r) => r.key === key) || items[0] || (data?.items || [])[0] || null
  const pick = (k) => { setKey(k); try { sessionStorage.setItem('ecosim-prop', k) } catch { /* private window */ } }

  // suggest what to forget: keep the newest onion, fuel and RBI scenarios, mark every other one of yours
  const startTidy = () => {
    const mine = (data?.items || []).filter((r) => r.kind === 'custom')
    const keep = new Set()
    ;[/onion/i, /fuel|petrol|crude|oil/i, /\brbi\b|repo|interest rate/i].forEach((re) => {
      const hit = mine.find((r) => re.test(r.title) && !keep.has(r.key))
      if (hit) keep.add(hit.key)
    })
    setMarked(new Set(mine.filter((r) => !keep.has(r.key)).map((r) => r.key)))
    setTidy(true)
  }
  const toggleMark = (k) => setMarked((m) => { const n = new Set(m); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const applyTidy = async () => {
    const ids = (data?.items || []).filter((r) => marked.has(r.key)).map((r) => r.scenario_id)
    if (!ids.length) return
    if (!window.confirm(`Forget ${ids.length} of your scenarios? Their runs stay in Recent runs.`)) return
    try { await forgetMany(ids); setTidy(false); setMarked(new Set()); setKey(null); setErr(''); load() } catch (e) { setErr(e.message) }
  }

  const forget = async (rec) => {
    if (!window.confirm(`Forget "${rec.title}"? Its runs stay in Recent runs.`)) return
    try { await forgetChain(rec.scenario_id); setKey(null); load() } catch (e) { setErr(e.message) }
  }

  const keepOnly = async (rec) => {
    const others = (data?.items || []).filter((r) => r.kind === 'custom' && r.key !== rec.key).length
    if (!others) { setErr('There are no other scenarios of yours to forget.'); return }
    if (!window.confirm(`Keep only "${rec.title}" and the built-in scenarios? ${others} of your other scenarios will be forgotten. Their runs stay in Recent runs.`)) return
    try { await keepOnlyChain(rec.scenario_id); setErr(''); load() } catch (e) { setErr(e.message) }
  }

  return (
    <div className="prop">
      <Rail items={items} current={current?.key} onPick={pick} filter={filter} setFilter={setFilter} query={query} setQuery={setQuery} onDescribe={onDescribe}
        tidy={tidy} marked={marked} onToggleMark={toggleMark} onStartTidy={startTidy} onCancelTidy={() => setTidy(false)} onApplyTidy={applyTidy} />
      <main className="prop__main">
        {err && <p className="prop__error" role="alert">{err}</p>}
        {!data && !err && <p className="prop__loading">Loading scenarios…</p>}
        {data && !data.stored && <p className="prop__notice">Your own scenarios can't be listed because the database is not reachable. The ready-made ones are shown.</p>}
        {current && <Detail rec={current} days={days} seed={seed} onOpenRun={onOpenRun} onEdit={onEdit} onForget={forget} onKeepOnly={keepOnly} onChanged={load} />}
      </main>
    </div>
  )
}

export { CATEGORIES }
