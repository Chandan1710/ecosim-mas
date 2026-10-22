/**
 * DashCharts — the few charts the Dashboard needs, drawn as plain SVG (no chart library).
 *
 *  LineChart  one value axis, 2px lines, a legend with the last value, a crosshair + one tooltip for every series,
 *             keyboard arrows, a table view, and a shaded band where the shock builds up.
 *  Sparkline  one resident's cash across the run.
 *  StatusBar  how many residents coped / were under strain / were in crisis.
 */

import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

const M = { top: 22, right: 18, bottom: 26, left: 38 }

/** round an axis maximum up to a clean number and give ticks that land on it */
function niceTicks(lo, hi, want = 4) {
  if (hi <= lo) hi = lo + 1
  const raw = (hi - lo) / want
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw
  const start = Math.floor(lo / step) * step
  const ticks = []
  for (let v = start; v <= hi + step * 0.999; v += step) ticks.push(Number(v.toFixed(6)))
  return { ticks: ticks.filter((t, i) => i === 0 || ticks[i - 1] < hi), lo: ticks[0], hi: ticks[ticks.length - 1] }
}

export function LineChart({ title, days, series, fmt = (v) => String(v), yMin = null, band = null, marks = [], height = 232, note }) {
  const wrap = useRef(null)
  const [w, setW] = useState(560)
  const [hover, setHover] = useState(null) // index into days
  const [table, setTable] = useState(false)

  useLayoutEffect(() => {
    const el = wrap.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => setW(Math.max(280, Math.floor(el.clientWidth))))
    ro.observe(el)
    setW(Math.max(280, Math.floor(el.clientWidth)))
    return () => ro.disconnect()
  }, [])

  const all = series.flatMap((s) => s.values.filter((v) => v != null))
  const dataLo = all.length ? Math.min(...all) : 0
  const dataHi = all.length ? Math.max(...all) : 1
  const { ticks, lo, hi } = useMemo(
    () => niceTicks(yMin != null ? Math.min(yMin, dataLo) : 0, Math.max(dataHi, yMin != null ? yMin + 0.1 : 4)),
    [yMin, dataLo, dataHi],
  )

  const n = days.length
  const iw = w - M.left - M.right
  const ih = height - M.top - M.bottom
  const x = (i) => M.left + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw)
  const y = (v) => M.top + ih - ((v - lo) / (hi - lo || 1)) * ih
  const path = (vals) => vals.map((v, i) => (v == null ? null : `${x(i).toFixed(1)} ${y(v).toFixed(1)}`)).filter(Boolean).map((p, i) => `${i ? 'L' : 'M'}${p}`).join(' ')
  const dayX = (d) => { const i = days.indexOf(d); return i < 0 ? null : x(i) }

  const move = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - r.left
    setHover(Math.max(0, Math.min(n - 1, Math.round(((px - M.left) / (iw || 1)) * (n - 1)))))
  }
  const key = (e) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      setHover((h) => Math.max(0, Math.min(n - 1, (h == null ? (e.key === 'ArrowRight' ? -1 : n) : h) + (e.key === 'ArrowRight' ? 1 : -1))))
    } else if (e.key === 'Escape') setHover(null)
  }

  const last = (s) => { for (let i = s.values.length - 1; i >= 0; i -= 1) if (s.values[i] != null) return s.values[i]; return null }
  const bandX0 = band ? dayX(band[0]) : null
  const bandX1 = band ? dayX(band[1]) : null
  const tipLeft = hover == null ? 0 : Math.min(Math.max(x(hover) + 14, 8), w - 190)

  return (
    <figure className="dchart">
      <figcaption className="dchart__head">
        <h3 className="dchart__title">{title}</h3>
        <button type="button" className="dchart__tog" onClick={() => setTable((t) => !t)} aria-pressed={table}>{table ? 'Chart' : 'Table'}</button>
      </figcaption>
      {note && <p className="dchart__note">{note}</p>}
      <ul className="dchart__legend">
        {series.map((s) => (
          <li key={s.key}><i style={{ background: s.color }} aria-hidden="true" />{s.label}<b>{last(s) == null ? '' : fmt(last(s))}</b></li>
        ))}
      </ul>

      {table ? (
        <div className="dchart__tablewrap">
          <table className="dchart__table">
            <thead><tr><th>Day</th>{series.map((s) => <th key={s.key}>{s.label}</th>)}</tr></thead>
            <tbody>{days.map((d, i) => <tr key={d}><td>{d}</td>{series.map((s) => <td key={s.key}>{s.values[i] == null ? '–' : fmt(s.values[i])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="dchart__plot" ref={wrap} onPointerLeave={() => setHover(null)}>
          <svg width={w} height={height} role="img" aria-label={`${title}. ${series.map((s) => `${s.label}: ${last(s) == null ? 'no data' : fmt(last(s))} on the last day`).join('; ')}`}
            tabIndex={0} onKeyDown={key} onFocus={() => hover == null && setHover(n - 1)} onBlur={() => setHover(null)}>
            {band && bandX0 != null && bandX1 != null && (
              <g>
                <rect x={bandX0} y={M.top} width={Math.max(0, bandX1 - bandX0)} height={ih} className="dchart__band" />
                <text x={bandX0 + 4} y={M.top - 8} className="dchart__marklab">Shock builds</text>
              </g>
            )}
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={w - M.right} y1={y(t)} y2={y(t)} className="dchart__grid" />
                <text x={M.left - 8} y={y(t) + 4} textAnchor="end" className="dchart__tick">{fmt(t)}</text>
              </g>
            ))}
            {days.map((d, i) => (n <= 12 || i % Math.ceil(n / 10) === 0 || i === n - 1) && (
              <text key={d} x={x(i)} y={height - 6} textAnchor="middle" className="dchart__tick">{d}</text>
            ))}
            {marks.map((m) => dayX(m.day) != null && (
              <g key={m.label}>
                <line x1={dayX(m.day)} x2={dayX(m.day)} y1={M.top} y2={M.top + ih} className="dchart__mark" />
                {!band && <text x={dayX(m.day) + 4} y={M.top - 8} className="dchart__marklab">{m.label}</text>}
              </g>
            ))}
            {series.map((s) => <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="dchart__line" />)}
            {series.map((s) => {
              const li = s.values.map((v) => v != null).lastIndexOf(true)
              return li >= 0 && <circle key={s.key} cx={x(li)} cy={y(s.values[li])} r="4" fill={s.color} className="dchart__end" />
            })}
            {hover != null && (
              <g pointerEvents="none">
                <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + ih} className="dchart__cross" />
                {series.map((s) => s.values[hover] != null && <circle key={s.key} cx={x(hover)} cy={y(s.values[hover])} r="4" fill={s.color} className="dchart__end" />)}
              </g>
            )}
            <rect x={M.left} y={M.top} width={iw} height={ih} fill="transparent" onPointerMove={move} onPointerDown={move} />
          </svg>
          {hover != null && (
            <div className="dchart__tip" style={{ left: tipLeft, top: M.top }} role="status">
              <div className="dchart__tipday">Day {days[hover]}</div>
              {series.map((s) => (
                <div key={s.key} className="dchart__tiprow"><i style={{ background: s.color }} /><b>{s.values[hover] == null ? '–' : fmt(s.values[hover])}</b><span>{s.label}</span></div>
              ))}
            </div>
          )}
        </div>
      )}
    </figure>
  )
}

export function Sparkline({ values, width = 96, height = 26, end = 'var(--color-text)' }) {
  if (!values || values.length < 2) return <span className="spark spark--none">–</span>
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const x = (i) => 3 + (i / (values.length - 1)) * (width - 6)
  const y = (v) => 3 + (height - 6) - ((v - lo) / (hi - lo || 1)) * (height - 6)
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const li = values.length - 1
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={`Cash from ${Math.round(values[0])} to ${Math.round(values[li])} rupees`}>
      <path d={d} fill="none" className="spark__line" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={x(li)} cy={y(values[li])} r="3" fill={end} className="spark__end" />
    </svg>
  )
}

export const STATUS = {
  Coping: { id: 'coping', label: 'Coping' },
  'Under strain': { id: 'strain', label: 'Under strain' },
  'In crisis': { id: 'crisis', label: 'In crisis' },
}

/** the status icon is a different shape per state so colour is never the only cue */
export function StatusDot({ status }) {
  const id = STATUS[status]?.id || 'coping'
  return (
    <svg className={`sdot sdot--${id}`} width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      {id === 'coping' && <circle cx="6" cy="6" r="4.5" />}
      {id === 'strain' && <path d="M6 1.2 11 10.4H1z" />}
      {id === 'crisis' && <rect x="1.6" y="1.6" width="8.8" height="8.8" rx="1.4" transform="rotate(45 6 6)" />}
    </svg>
  )
}

export function StatusBar({ counts }) {
  const order = ['Coping', 'Under strain', 'In crisis']
  const total = order.reduce((a, k) => a + (counts[k] || 0), 0) || 1
  return (
    <div className="sbar">
      <div className="sbar__track" role="img" aria-label={order.map((k) => `${counts[k] || 0} ${k.toLowerCase()}`).join(', ')}>
        {order.map((k) => (counts[k] || 0) > 0 && <span key={k} className={`sbar__seg sbar__seg--${STATUS[k].id}`} style={{ flexGrow: counts[k] }} title={`${k}: ${counts[k]}`} />)}
      </div>
      <ul className="sbar__legend">
        {order.map((k) => <li key={k}><StatusDot status={k} />{k}<b>{counts[k] || 0}</b><small>{Math.round(((counts[k] || 0) / total) * 100)}%</small></li>)}
      </ul>
    </div>
  )
}

export function useOutside(ref, onOut, active) {
  useEffect(() => {
    if (!active) return undefined
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onOut() }
    document.addEventListener('pointerdown', h)
    return () => document.removeEventListener('pointerdown', h)
  }, [ref, onOut, active])
}
