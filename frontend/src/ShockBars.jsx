/**
 * ShockBars — the five numbers a chain of events adds up to, as centred bars (zero in the middle).
 * Used in the chain studio (live, as events are included or excluded) and on the Event propagation page.
 */

import React from 'react'

export const SHOCK_ROWS = [
  ['essential_cost', 'Essential prices', 'dearer', 'cheaper'],
  ['income', 'Incomes', 'higher', 'lower'],
  ['credit_tightness', 'Credit', 'tighter', 'looser'],
  ['demand', 'Spending', 'higher', 'lower'],
  ['savings', 'Savings', 'higher', 'lower'],
]

const pct = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(Math.round(v * 100))}%`

export default function ShockBars({ shock, pending = 0, compact = false }) {
  if (!shock) return null
  return (
    <div className={`shock ${compact ? 'shock--compact' : ''}`} role="group" aria-label="What the chain adds up to">
      {SHOCK_ROWS.map(([k, label]) => {
        const v = shock[k] || 0
        const w = Math.min(50, Math.abs(v) * 50) // ±100% fills one side
        return (
          <div className="shock__row" key={k}>
            <span className="shock__k">{label}</span>
            <span className="shock__track" aria-hidden="true">
              <i className="shock__zero" />
              <i className={`shock__bar ${v >= 0 ? 'pos' : 'neg'}`} style={{ width: `${w}%`, [v >= 0 ? 'left' : 'right']: '50%' }} />
            </span>
            <b className="shock__v">{pct(v)}</b>
          </div>
        )
      })}
      {pending > 0 && <p className="shock__note">{pending} {pending === 1 ? 'event is' : 'events are'} still being quantified…</p>}
    </div>
  )
}
