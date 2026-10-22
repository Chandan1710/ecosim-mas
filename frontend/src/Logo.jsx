/**
 * Logo — the EcoSim-MAS mark: a shock at the centre spreading ring by ring through the town (animated; still when the
 * visitor prefers reduced motion).
 */

import React from 'react'

// The mark is the hero animation from the Describe screen in miniature: a shock at the centre sends rings outward,
// and each resident (dot) lights up as a ring passes. Timings are derived so the dots flash exactly when a ring arrives.
const PERIOD = 3.6 // seconds for a ring to travel from the core to the edge
const R0 = 3 // radius a ring starts at
const R1 = 17 // radius at which a ring has faded out
const PASS = PERIOD / 3 // three rings, evenly spaced, so a dot is passed every PERIOD / 3
const SATELLITES = []
const orbit = (n, r, turn) => {
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + turn
    const reach = (((r - R0) / (R1 - R0)) * PERIOD) % PASS // when, within each PASS, a ring is at this radius
    SATELLITES.push({ x: 18 + r * Math.cos(a), y: 18 + r * Math.sin(a), delay: reach })
  }
}
orbit(6, 9, 0)
orbit(9, 14.4, 0.3)

export function LogoMark({ size = 28 }) {
  return (
    <svg className="logo__mark" width={size} height={size} viewBox="0 0 36 36" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <circle key={i} className="logo__ring" cx="18" cy="18" r={R0} style={{ animationDelay: `${-i * PASS}s`, '--grow': R1 / R0 }} />
      ))}
      {SATELLITES.map((d, i) => (
        <circle key={i} className="logo__dot" cx={d.x} cy={d.y} r="1.15" style={{ animationDelay: `${d.delay}s` }} />
      ))}
      <circle className="logo__core" cx="18" cy="18" r="2.7" />
    </svg>
  )
}

export default function Logo() {
  return (
    <span className="logo" aria-label="EcoSim-MAS">
      <LogoMark />
      <span className="logo__word" aria-hidden="true">EcoSim<span className="logo__sub">MAS</span></span>
    </span>
  )
}
