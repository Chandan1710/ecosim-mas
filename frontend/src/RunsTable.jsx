/**
 * RunsTable — the table of saved runs, shared by the home page (latest three) and the
 * Recent runs page (all of them). `withLog` adds a link to the raw event log of each run.
 *
 * With `animate`, changing the list (for example switching a filter) plays in three short steps:
 * rows that no longer belong fade out, the rest glide to their new places (FLIP), and new rows
 * fade in. Reduced-motion users get an instant swap.
 */

import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { eventsUrl, reportUrl } from './api'

export function when(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

const FADE_OUT_MS = 150
const REDUCED = () => typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const sameIds = (a, b) => a.length === b.length && a.every((r, i) => r.run_id === b[i].run_id)

export default function RunsTable({ runs, onOpen, withLog = false, animate = false }) {
  const [rows, setRows] = useState(runs)
  const [leaving, setLeaving] = useState(() => new Set())
  const rowsRef = useRef(runs)
  const trs = useRef(new Map())
  const before = useRef(null) // row positions + which rows are new, captured just before the swap
  const timer = useRef(null)

  useEffect(() => {
    clearTimeout(timer.current)
    const prev = rowsRef.current
    const apply = (next, snapshot) => {
      before.current = snapshot
      rowsRef.current = next
      setLeaving(new Set())
      setRows(next)
    }
    if (!animate || REDUCED() || sameIds(prev, runs)) {
      // same people in the same order (or no animation wanted): just refresh the data
      apply(runs, null)
      return undefined
    }
    const nextIds = new Set(runs.map((r) => r.run_id))
    const gone = prev.filter((r) => !nextIds.has(r.run_id))
    const swap = () => {
      const pos = new Map()
      trs.current.forEach((el, id) => pos.set(id, el.getBoundingClientRect().top))
      const prevIds = new Set(prev.map((r) => r.run_id))
      apply(runs, { pos, fresh: new Set(runs.filter((r) => !prevIds.has(r.run_id)).map((r) => r.run_id)) })
    }
    if (gone.length === 0) {
      swap()
    } else {
      setLeaving(new Set(gone.map((r) => r.run_id)))
      timer.current = setTimeout(swap, FADE_OUT_MS)
    }
    return () => clearTimeout(timer.current)
  }, [runs, animate])

  // after the swap: slide the rows that stayed, fade in the new ones
  useLayoutEffect(() => {
    const snap = before.current
    before.current = null
    if (!snap) return
    let n = 0
    trs.current.forEach((el, id) => {
      if (snap.fresh.has(id)) {
        el.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
          { duration: 280, delay: 90 + Math.min(n++, 6) * 30, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)', fill: 'backwards' })
        return
      }
      const dy = (snap.pos.get(id) ?? 0) - el.getBoundingClientRect().top
      if (snap.pos.has(id) && Math.abs(dy) > 1) {
        el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }],
          { duration: 320, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)' })
      }
    })
  }, [rows])

  return (
    <table className="home__runs">
      <thead>
        <tr><th>Run</th><th>Started</th><th>Days</th><th>Status</th><th>Moneylender<br />borrowers</th><th>Defaults</th><th /></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr
            key={r.run_id}
            ref={(el) => {
              if (el) trs.current.set(r.run_id, el)
              else trs.current.delete(r.run_id)
            }}
            className={leaving.has(r.run_id) ? 'is-leaving' : undefined}
          >
            <td><b>{r.title}</b><div className="muted">{r.run_id}</div></td>
            <td className="muted">{when(r.created_at)}</td>
            <td>{r.days_done}/{r.days}</td>
            <td><span className={`home__status home__status--${r.status}`}>{r.status}</span></td>
            <td className="muted">{r.town ? r.town.moneylender_borrowers : '—'}</td>
            <td className="muted">{r.town ? r.town.defaulted : '—'}</td>
            <td className="home__acts">
              <button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={() => onOpen(r.run_id)}>
                {r.status === 'running' ? 'Watch' : 'Replay'}
              </button>
              {r.status !== 'running' && r.days_done > 0 && (
                <>
                  <a className="town-btn town-btn--ghost town-btn--sm" href={reportUrl(r.run_id, 'summary')}>Summary PDF</a>
                  <a className="town-btn town-btn--ghost town-btn--sm" href={reportUrl(r.run_id, 'agents')}>Agents PDF</a>
                </>
              )}
              {withLog && r.days_done > 0 && (
                <a className="town-btn town-btn--ghost town-btn--sm" href={eventsUrl(r.run_id)} download={`${r.run_id}-log.json`}>Log</a>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
