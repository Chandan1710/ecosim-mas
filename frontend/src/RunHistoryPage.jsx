/**
 * RunHistoryPage (Recent runs) — every simulation ever run, newest first. Each run is stored on disk, so
 * it can be replayed without any LLM calls, exported as PDFs, or downloaded as its raw event log.
 */

import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import './history.css'
import { listTownRuns } from './api'
import RunsTable from './RunsTable'

const FILTERS = [
  ['all', 'All'],
  ['done', 'Completed'],
  ['running', 'Running'],
  ['other', 'Stopped or failed'],
]
const matches = (r, f) => f === 'all' || (f === 'other' ? !['done', 'running'].includes(r.status) : r.status === f)

// Filter switch with a pill that slides to the chosen option
function Filter({ value, onChange }) {
  const box = useRef(null)
  const [thumb, setThumb] = useState(null)
  useLayoutEffect(() => {
    const b = box.current?.querySelector('.is-on')
    if (b) setThumb({ x: b.offsetLeft, w: b.offsetWidth })
  }, [value])
  return (
    <div className="hist-seg" role="group" aria-label="Filter by status" ref={box}>
      {thumb && <span className="hist-seg__thumb" style={{ width: thumb.w, transform: `translateX(${thumb.x}px)` }} />}
      {FILTERS.map(([id, label]) => (
        <button type="button" key={id} className={value === id ? 'is-on' : ''} aria-pressed={value === id} onClick={() => onChange(id)}>{label}</button>
      ))}
    </div>
  )
}

export default function RunHistoryPage({ onOpen }) {
  const [runs, setRuns] = useState(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')

  useEffect(() => {
    let alive = true
    let t
    const load = () => listTownRuns()
      .then((r) => {
        if (!alive) return
        setRuns(r)
        if (r.some((x) => x.status === 'running')) t = setTimeout(load, 4000)
      })
      .catch((e) => alive && setErr(e.message || 'Could not load the runs.'))
    load()
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [])

  const sorted = useMemo(() => [...(runs || [])].sort((a, b) => (b.created_at || 0) - (a.created_at || 0)), [runs])
  const shown = sorted.filter((r) => matches(r, filter) && (!q.trim() || `${r.title} ${r.run_id}`.toLowerCase().includes(q.trim().toLowerCase())))
  const done = sorted.filter((r) => r.status === 'done').length
  const daysTotal = sorted.reduce((s, r) => s + (r.days_done || 0), 0)

  return (
    <div className="hist">
      <div className="hist__inner">
        <h1 className="hist__title">Recent runs</h1>
        <p className="hist__lede">
          Every simulation is saved automatically. Replay any run without using the API, export its reports,
          or download the full event log.
        </p>

        {err && <p className="hist__err" role="alert">{err}</p>}
        {!runs && !err && <p className="hist__lede">Loading runs…</p>}

        {runs && runs.length === 0 && (
          <p className="home__empty">No runs yet. Start one from the home page and it will appear here.</p>
        )}

        {runs && runs.length > 0 && (
          <>
            <dl className="hist__stats">
              <div><dt>Runs</dt><dd>{sorted.length}</dd></div>
              <div><dt>Completed</dt><dd>{done}</dd></div>
              <div><dt>Days simulated</dt><dd>{daysTotal}</dd></div>
            </dl>

            <div className="hist__tools">
              <Filter value={filter} onChange={setFilter} />
              <input
                className="hist__search" type="search" placeholder="Search by scenario or run id"
                aria-label="Search runs" value={q} onChange={(e) => setQ(e.target.value)}
              />
            </div>

            <RunsTable runs={shown} onOpen={onOpen} withLog animate />
            {shown.length === 0 && <p className="home__empty hist__none">No runs match.</p>}
          </>
        )}
      </div>
    </div>
  )
}
