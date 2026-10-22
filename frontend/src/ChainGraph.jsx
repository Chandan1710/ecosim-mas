/**
 * ChainGraph — the chain of events as a flowchart.
 *
 * One straight vertical line of events; when an event has a second effect the line branches to the right, and
 * an event that follows from several branches joins them again. Cards are laid out on a CSS grid (so they grow
 * with their text) and the connectors are drawn as an SVG on top, measured from the real card positions.
 *
 * mode="view"  read-only: click an event to light up everything that follows from it
 * mode="edit"  the same, plus per-event tools: edit the wording, exclude / include, delete, add an effect
 *
 * No gradients, no shadows. Motion: cards settle in one after another, connectors draw themselves, and the
 * path of the selected event flows downstream. All of it is switched off by prefers-reduced-motion.
 */

import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import './chain.css'
import { ancestors, descendants, layoutChain } from './chainLayout'

export const CATEGORIES = [
  ['prices', 'Prices'], ['employment', 'Jobs & income'], ['credit', 'Credit'], ['policy', 'Policy'],
  ['consumer_behaviour', 'Behaviour'], ['trade', 'Trade'], ['other', 'Other'],
]
export const CATEGORY_LABEL = Object.fromEntries(CATEGORIES)
export const MAGNITUDES = [['major', 'Major'], ['moderate', 'Moderate'], ['minor', 'Minor']]
const BARS = { major: 3, moderate: 2, minor: 1 }

const COL_GAP = 64 // widest gap, used when there are one or two lanes
const MIN_CARD = 184
const gapFor = (lanes) => (lanes >= 4 ? 36 : lanes === 3 ? 48 : COL_GAP)
const ROW_GAP = 52
const R = 10

export function Magnitude({ value }) {
  const n = BARS[value] || 2
  return (
    <span className={`cg-mag cg-mag--${value}`} title={`${value} effect`} aria-label={`${value} effect`}>
      {[1, 2, 3].map((i) => <i key={i} className={i <= n ? 'on' : ''} style={{ height: 4 + i * 3 }} />)}
    </span>
  )
}

const Ico = ({ d, size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
)
const ICON = {
  edit: 'M3 13l.6-2.8L11 2.8a1.4 1.4 0 0 1 2 2L5.8 12.4 3 13z',
  add: 'M8 3v10M3 8h10',
  off: 'M2 8s2.3-4 6-4 6 4 6 4-2.3 4-6 4-6-4-6-4zM3 13L13 3',
  on: 'M2 8s2.3-4 6-4 6 4 6 4-2.3 4-6 4-6-4-6-4zM8 6.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z',
  del: 'M3.5 4.5h9M6.5 4.5V3h3v1.5M5 4.5l.5 8h5l.5-8',
}

/** a polyline with softly rounded corners */
function rounded(points, r = R) {
  if (points.length < 2) return ''
  let d = `M${points[0][0]} ${points[0][1]}`
  for (let i = 1; i < points.length - 1; i += 1) {
    const [x0, y0] = points[i - 1]
    const [x1, y1] = points[i]
    const [x2, y2] = points[i + 1]
    const l1 = Math.hypot(x1 - x0, y1 - y0)
    const l2 = Math.hypot(x2 - x1, y2 - y1)
    const rr = Math.min(r, l1 / 2, l2 / 2)
    if (rr < 0.5) { d += ` L${x1} ${y1}`; continue }
    const ax = x1 - ((x1 - x0) / l1) * rr
    const ay = y1 - ((y1 - y0) / l1) * rr
    const bx = x1 + ((x2 - x1) / l2) * rr
    const by = y1 + ((y2 - y1) / l2) * rr
    d += ` L${ax} ${ay} Q${x1} ${y1} ${bx} ${by}`
  }
  const [lx, ly] = points[points.length - 1]
  return `${d} L${lx} ${ly}`
}

function Editor({ node, onCommit, onCancel }) {
  const [text, setText] = useState(node.description)
  const [category, setCategory] = useState(node.category)
  const [magnitude, setMagnitude] = useState(node.magnitude)
  const ref = useRef(null)
  useEffect(() => { ref.current?.focus(); ref.current?.setSelectionRange(text.length, text.length) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const ok = text.trim().length >= 3
  const save = () => ok && onCommit({ description: text.trim(), category, magnitude })
  return (
    <div className="cg-edit" onClick={(e) => e.stopPropagation()}>
      <textarea
        ref={ref} rows={3} maxLength={220} value={text} placeholder="What happens? One clear sentence."
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel()
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save()
        }}
      />
      <div className="cg-edit__row">
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <select value={magnitude} onChange={(e) => setMagnitude(e.target.value)} aria-label="Size">
          {MAGNITUDES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      <div className="cg-edit__row cg-edit__row--end">
        <button type="button" className="cg-btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="cg-btn cg-btn--ink" disabled={!ok} onClick={save}>Save</button>
      </div>
    </div>
  )
}

export default function ChainGraph({
  nodes, mode = 'view', selectedId = null, onSelect = () => {}, editingId = null,
  onToggle, onRemove, onAdd, onStartEdit, onCommit, onCancelEdit, detail = true, flow = true, cardMax = 276,
}) {
  const layout = useMemo(() => layoutChain(nodes), [nodes])
  const colGap = gapFor(layout.lanes)
  const [avail, setAvail] = useState(0)
  // cards shrink (down to a floor) so that a wide chain fits its box instead of scrolling sideways
  const cardW = avail ? Math.max(MIN_CARD, Math.min(cardMax, Math.floor((avail - 30 - (layout.lanes - 1) * colGap) / layout.lanes))) : cardMax
  const wrap = useRef(null)
  const cards = useRef(new Map())
  const [geo, setGeo] = useState({ w: 0, h: 0, paths: [] })
  const lineage = useMemo(() => {
    if (selectedId == null || !nodes.some((n) => n.id === selectedId)) return null
    return { down: descendants(nodes, selectedId), up: ancestors(nodes, selectedId) }
  }, [nodes, selectedId])

  const measure = useCallback(() => {
    const host = wrap.current
    if (!host) return
    const box = (id) => {
      const el = cards.current.get(id)
      return el ? { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight } : null
    }
    const paths = []
    layout.edges.forEach((e) => {
      const a = box(e.from)
      const b = box(e.to)
      if (!a || !b) return
      const fx = a.x + a.w / 2
      const fy = a.y + a.h
      const tx = b.x + b.w / 2
      const ty = b.y
      let pts
      if (e.direct) {
        const mid = ty - ROW_GAP / 2
        pts = Math.abs(fx - tx) < 1 ? [[fx, fy], [tx, ty]] : [[fx, fy], [fx, mid], [tx, mid], [tx, ty]]
      } else {
        // skips a row: leave by the gutter right of the two lanes so the line never crosses a card
        const lane = Math.max(layout.pos.get(e.from).lane, layout.pos.get(e.to).lane)
        const gx = (a.w + colGap) * (lane + 1) - colGap / 2
        pts = [[fx, fy], [fx, fy + ROW_GAP / 2], [gx, fy + ROW_GAP / 2], [gx, ty - ROW_GAP / 2], [tx, ty - ROW_GAP / 2], [tx, ty]]
      }
      paths.push({ key: `${e.from}-${e.to}`, from: e.from, to: e.to, d: rounded(pts), tip: [tx, ty] })
    })
    const w = host.scrollWidth
    const h = host.scrollHeight
    setGeo((g) => {
      const sig = JSON.stringify([w, h, paths.map((p) => p.d)])
      return g.sig === sig ? g : { w, h, paths, sig }
    })
  }, [layout, colGap])

  useLayoutEffect(() => { measure() }, [measure, nodes, selectedId, editingId, cardW])
  useEffect(() => {
    const parent = wrap.current?.parentElement
    if (!parent || typeof ResizeObserver === 'undefined') return undefined
    const read = () => {
      const cs = getComputedStyle(parent)
      const w = Math.floor(parent.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight))
      setAvail((a) => (Math.abs(a - w) >= 2 ? w : a))
    }
    read()
    const ro = new ResizeObserver(read)
    ro.observe(parent)
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    const host = wrap.current
    if (!host || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => measure())
    ro.observe(host)
    cards.current.forEach((el) => ro.observe(el))
    return () => ro.disconnect()
  }, [measure, nodes])

  const edgeState = (p) => {
    if (!lineage) return ''
    const inDown = (id) => id === selectedId || lineage.down.has(id)
    const inUp = (id) => id === selectedId || lineage.up.has(id)
    if (inDown(p.from) && inDown(p.to)) return 'is-flow'
    return inUp(p.from) && inUp(p.to) ? '' : 'is-dim'
  }
  const cardState = (id) => {
    if (!lineage || id === selectedId) return ''
    return lineage.down.has(id) ? 'is-down' : lineage.up.has(id) ? '' : 'is-dim'
  }

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const edit = mode === 'edit'

  return (
    <div className="cg" ref={wrap} style={{ '--cg-lanes': layout.lanes, '--cg-w': `${cardW}px` }}>
      <svg className="cg__edges" width={geo.w} height={geo.h} aria-hidden="true">
        {geo.paths.map((p) => {
          const off = !nodeById.get(p.from)?.included || !nodeById.get(p.to)?.included
          return (
            <g key={p.key} className={`cg-edge ${edgeState(p)} ${off ? 'is-off' : ''}`}>
              <path className="cg-edge__line" d={p.d} pathLength="1" />
              {flow && <path className="cg-edge__flow" d={p.d} />}
              <path className="cg-edge__tip" d={`M${p.tip[0] - 4.5} ${p.tip[1] - 7} L${p.tip[0]} ${p.tip[1] - 1.5} L${p.tip[0] + 4.5} ${p.tip[1] - 7}`} />
            </g>
          )
        })}
      </svg>
      <div className="cg__grid" style={{ gridTemplateColumns: `repeat(${layout.lanes}, var(--cg-w))`, columnGap: colGap, rowGap: ROW_GAP }}>
        {nodes.map((n) => {
          const p = layout.pos.get(n.id)
          const selected = selectedId === n.id
          const editing = editingId === n.id
          return (
            <article
              key={n.id}
              ref={(el) => (el ? cards.current.set(n.id, el) : cards.current.delete(n.id))}
              data-id={n.id}
              className={`cg-card cat-${n.category} ${selected ? 'is-selected' : ''} ${n.included ? '' : 'is-excluded'} ${n.added ? 'is-added' : ''} ${cardState(n.id)}`}
              style={{ gridRow: p.row + 1, gridColumn: p.lane + 1, '--i': layout.number.get(n.id) }}
              onClick={() => onSelect(selected && !editing ? null : n.id)}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(selected ? null : n.id) }
                if (edit && selected && (e.key === 'Delete' || e.key === 'Backspace')) { e.preventDefault(); onRemove?.(n.id) }
              }}
              aria-pressed={selected}
            >
              <header className="cg-card__head">
                <span className="cg-card__n">{layout.number.get(n.id)}</span>
                <span className="cg-card__cat"><i />{CATEGORY_LABEL[n.category] || 'Other'}</span>
                <Magnitude value={n.magnitude} />
                {n.added && <span className="cg-card__tag">yours</span>}
                {!n.included && <span className="cg-card__tag cg-card__tag--off">excluded</span>}
              </header>

              {editing ? (
                <Editor node={n} onCommit={(patch) => onCommit(n.id, patch)} onCancel={() => onCancelEdit(n.id)} />
              ) : (
                <p className="cg-card__t">{n.description}</p>
              )}

              {selected && !editing && detail && (n.note || n.rationale || n.deltas) && (
                <div className="cg-card__more">
                  {n.note && <p>{n.note}</p>}
                  {!n.note && n.rationale && <p>{n.rationale}</p>}
                  {n.deltas && <DeltaChips deltas={n.deltas} />}
                  <span className="cg-card__conf">Confidence {Math.round((n.confidence ?? 0) * 100)}%</span>
                </div>
              )}

              {edit && selected && !editing && (
                <div className="cg-tools" onClick={(e) => e.stopPropagation()}>
                  <button type="button" className="cg-tool" onClick={() => onStartEdit(n.id)}><Ico d={ICON.edit} />Edit</button>
                  <button type="button" className="cg-tool" onClick={() => onAdd(n.id)}><Ico d={ICON.add} />Add effect</button>
                  <button type="button" className="cg-tool" onClick={() => onToggle(n.id)}>
                    <Ico d={n.included ? ICON.off : ICON.on} />{n.included ? 'Exclude' : 'Include'}
                  </button>
                  <button type="button" className="cg-tool cg-tool--danger" onClick={() => onRemove(n.id)}><Ico d={ICON.del} />Delete</button>
                </div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}

const DELTA_LABEL = {
  essential_cost_index_pct: 'Essentials', discretionary_spend_pct: 'Spending', credit_availability_pct: 'Credit', savings_rate_pct: 'Savings',
}
export function DeltaChips({ deltas }) {
  return (
    <div className="cg-deltas">
      {Object.entries(DELTA_LABEL).map(([k, l]) => (deltas[k] === undefined ? null : (
        <span key={k} className={deltas[k] > 0.004 ? 'up' : deltas[k] < -0.004 ? 'down' : ''}>
          {l} {deltas[k] > 0 ? '+' : ''}{(deltas[k] * 100).toFixed(0)}%
        </span>
      )))}
    </div>
  )
}

/** placeholder while the first chain is being written */
export function ChainSkeleton({ n = 5 }) {
  return (
    <div className="cg cg--skeleton" style={{ '--cg-lanes': 1 }} aria-label="Writing the chain of events" role="status">
      <div className="cg__grid" style={{ gridTemplateColumns: 'var(--cg-w)', rowGap: ROW_GAP }}>
        {Array.from({ length: n }).map((_, i) => (
          <div className="cg-card cg-card--ghost" key={i} style={{ '--i': i }}>
            <span className="cg-ghost cg-ghost--s" />
            <span className="cg-ghost" />
            <span className="cg-ghost cg-ghost--m" />
            {i < n - 1 && <i className="cg-ghost-line" />}
          </div>
        ))}
      </div>
    </div>
  )
}
