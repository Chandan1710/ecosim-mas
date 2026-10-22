/**
 * townGeometry.js — layout maths for the town map: road paths between doors,
 * where agents stand inside a building, and walking along a path.
 * All coordinates are in tiles (the backend map is 64 × 40 tiles).
 */

export function buildRoadGraph(map) {
  const roads = new Set(map.roads.map((r) => `${r.x},${r.y}`))
  const places = Object.fromEntries(map.places.map((p) => [p.id, p]))
  return { roads, places, cache: new Map() }
}

/** Shortest road path (list of tile centres) from one place's door to another's. */
export function roadPath(graph, fromId, toId) {
  const key = `${fromId}>${toId}`
  if (graph.cache.has(key)) return graph.cache.get(key)
  const a = graph.places[fromId]?.door
  const b = graph.places[toId]?.door
  if (!a || !b) return []
  const start = `${a.x},${a.y}`
  const goal = `${b.x},${b.y}`
  const prev = new Map([[start, null]])
  const queue = [start]
  while (queue.length) {
    const cur = queue.shift()
    if (cur === goal) break
    const [x, y] = cur.split(',').map(Number)
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const n = `${x + dx},${y + dy}`
      if (graph.roads.has(n) && !prev.has(n)) {
        prev.set(n, cur)
        queue.push(n)
      }
    }
  }
  let pts = []
  if (prev.has(goal)) {
    for (let c = goal; c; c = prev.get(c)) {
      const [x, y] = c.split(',').map(Number)
      pts.push({ x: x + 0.5, y: y + 0.5 })
    }
    pts.reverse()
    // keep only the corners so walking looks smooth
    pts = pts.filter((p, i) => {
      if (i === 0 || i === pts.length - 1) return true
      const a0 = pts[i - 1]
      const a1 = pts[i + 1]
      return !((a0.x === p.x && p.x === a1.x) || (a0.y === p.y && p.y === a1.y))
    })
  } else {
    pts = [{ x: a.x + 0.5, y: a.y + 0.5 }, { x: b.x + 0.5, y: b.y + 0.5 }]
  }
  graph.cache.set(key, pts)
  return pts
}

const OUTDOOR = new Set(['park', 'market', 'construction', 'auto_stand', 'fuel_station'])

/** Open-air places (market, park, fuel station…) have no walls to walk through. */
export const isOutdoor = (place) => OUTDOOR.has(place.id)

/**
 * From the road to the inside of a place: the point in the doorway, then the first spot
 * inside. (The road door tile itself is the last point of the road path.)
 */
export function doorway(place) {
  const r = place.rect
  const x = place.door.x + 0.5
  const north = place.door.y < r.y
  if (north) return [{ x, y: r.y + (isOutdoor(place) ? 0.2 : 0.55) }, { x, y: r.y + (isOutdoor(place) ? 1.3 : 1.95) }]
  return [{ x, y: r.y + r.h - (isOutdoor(place) ? 0.3 : 0.45) }, { x, y: r.y + r.h - 1.3 }]
}

// where people stand in the open-air places, so they don't hide the stalls and pumps
const BANDS = {
  market: { yMin: 2.55, yMax: 3.75 },
  fuel_station: { xMin: 2.7, yMin: 3.0 },
  auto_stand: { yMin: 1.5 },
  construction: { yMin: 1.45 },
}

/** Where the i-th of n agents stands inside a place (feet position, in tiles). */
export function slotIn(place, i, n) {
  const r = place.rect
  const out = isOutdoor(place)
  const gapX = 1.3
  const gapY = 1.15
  const b = BANDS[place.id] || {}
  const xMin = b.xMin ?? 0.95
  const xMax = r.w - 0.95
  const yMin = b.yMin ?? (out ? 0.9 : Math.min(1.95, r.h - 1.05))
  const yMax = b.yMax ?? r.h - (out ? 0.7 : 0.75)
  const cols = Math.max(1, Math.floor((xMax - xMin) / gapX) + 1)
  const rows = Math.max(1, Math.floor((yMax - yMin) / gapY) + 1)
  const cap = cols * rows
  const k = i % cap
  const col = k % cols
  const row = Math.floor(k / cols)
  const usedCols = Math.min(cols, Math.max(1, n))
  const x0 = r.x + (r.w - (usedCols - 1) * gapX) / 2
  const y0 = r.y + yMin
  const jitter = i >= cap ? 0.4 : 0
  return { x: x0 + col * gapX + jitter, y: y0 + row * gapY + jitter }
}

export function pathLength(pts) {
  let len = 0
  for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)
  return len
}

/** Point at fraction t (0..1) of the way along a polyline. */
export function pointAlong(pts, t) {
  if (pts.length === 0) return { x: 0, y: 0 }
  if (pts.length === 1 || t <= 0) return pts[0]
  if (t >= 1) return pts[pts.length - 1]
  let target = pathLength(pts) * t
  for (let i = 1; i < pts.length; i++) {
    const seg = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)
    if (target <= seg) {
      const f = seg ? target / seg : 0
      return { x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * f, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * f }
    }
    target -= seg
  }
  return pts[pts.length - 1]
}

export const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2)
