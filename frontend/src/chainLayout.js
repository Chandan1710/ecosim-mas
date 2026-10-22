/**
 * chainLayout — where each event of a chain sits on the flowchart.
 *
 * Rows go top to bottom in cause-before-effect order (a node sits one row below its deepest cause).
 * Lanes go left to right. The first line of events stays in lane 0, so a plain chain is one straight
 * vertical line; when an event has a second effect, that effect starts a branch in the next lane, and an
 * event that follows from several branches returns to the left-most of their lanes.
 *
 * Pure functions, no DOM, so they can be tested on their own (node chainLayout.test.mjs).
 */

export function depthsOf(nodes) {
  const by = new Map(nodes.map((n) => [n.id, n]))
  const depth = new Map()
  const visiting = new Set()
  const d = (id) => {
    if (depth.has(id)) return depth.get(id)
    if (visiting.has(id)) return 0 // a cycle (the server removes these); never recurse forever
    visiting.add(id)
    const parents = (by.get(id)?.depends_on || []).filter((p) => by.has(p) && p !== id)
    const v = parents.length ? 1 + Math.max(...parents.map(d)) : 0
    visiting.delete(id)
    depth.set(id, v)
    return v
  }
  nodes.forEach((n) => d(n.id))
  return depth
}

export function layoutChain(nodes) {
  const depth = depthsOf(nodes)
  const order = [...nodes].sort((a, b) => depth.get(a.id) - depth.get(b.id) || a.id - b.id)
  const pos = new Map() // id -> { row, lane }
  const taken = new Map() // row -> Set(lane)
  const free = (row, lane) => !(taken.get(row) || new Set()).has(lane)
  const claim = (row, lane) => {
    if (!taken.has(row)) taken.set(row, new Set())
    taken.get(row).add(lane)
  }
  // lanes are assigned in order so that earlier events (and the first branch) keep the left-most lanes
  order.forEach((n) => {
    const row = depth.get(n.id)
    const parents = (n.depends_on || []).filter((p) => pos.has(p) && p !== n.id)
    const parentLanes = parents.map((p) => pos.get(p).lane)
    let want = 0
    if (parents.length === 1) want = parentLanes[0]
    else if (parents.length > 1) want = Math.min(...parentLanes) // a merge rejoins the leftmost branch
    else want = 0
    let lane = want
    while (!free(row, lane)) lane += 1
    claim(row, lane)
    pos.set(n.id, { row, lane })
  })
  const rows = []
  order.forEach((n) => {
    const { row } = pos.get(n.id)
    ;(rows[row] = rows[row] || []).push(n.id)
  })
  rows.forEach((r) => r && r.sort((a, b) => pos.get(a).lane - pos.get(b).lane))
  const lanes = nodes.length ? 1 + Math.max(...[...pos.values()].map((p) => p.lane)) : 1
  // reading order: top to bottom, left to right
  const number = new Map()
  let k = 0
  rows.forEach((r) => (r || []).forEach((id) => number.set(id, ++k)))
  const edges = []
  nodes.forEach((n) => {
    ;(n.depends_on || []).forEach((p) => {
      if (!pos.has(p) || p === n.id) return
      edges.push({ from: p, to: n.id, direct: pos.get(p).row === pos.get(n.id).row - 1 })
    })
  })
  return { pos, rows, lanes, number, edges, depth }
}

/** every node that follows (directly or not) from `id` */
export function descendants(nodes, id) {
  const kids = new Map()
  nodes.forEach((n) => (n.depends_on || []).forEach((p) => kids.set(p, [...(kids.get(p) || []), n.id])))
  const out = new Set()
  const walk = (x) => (kids.get(x) || []).forEach((c) => !out.has(c) && (out.add(c), walk(c)))
  walk(id)
  return out
}

export function ancestors(nodes, id) {
  const by = new Map(nodes.map((n) => [n.id, n]))
  const out = new Set()
  const walk = (x) => ((by.get(x)?.depends_on || []).forEach((p) => !out.has(p) && by.has(p) && (out.add(p), walk(p))))
  walk(id)
  return out
}

/** the editing operations, all pure: they return a new node list */
export const nextId = (nodes) => 1 + Math.max(0, ...nodes.map((n) => n.id))

export function addEffect(nodes, parentId, patch = {}) {
  const id = nextId(nodes)
  const node = {
    id, description: '', category: 'other', magnitude: 'moderate', confidence: 0.6,
    depends_on: parentId == null ? [] : [parentId], note: '', included: true, added: true, ...patch,
  }
  return { nodes: [...nodes, node], id }
}

export function removeNode(nodes, id) {
  const gone = nodes.find((n) => n.id === id)
  if (!gone) return nodes
  const parents = gone.depends_on || []
  return nodes
    .filter((n) => n.id !== id)
    .map((n) => {
      if (!(n.depends_on || []).includes(id)) return n
      const deps = [...new Set([...n.depends_on.filter((d) => d !== id), ...parents])]
      return { ...n, depends_on: deps }
    })
}

export const setIncluded = (nodes, id, included) => nodes.map((n) => (n.id === id ? { ...n, included } : n))
export const patchNode = (nodes, id, patch) => nodes.map((n) => (n.id === id ? { ...n, ...patch } : n))
export const keptCount = (nodes) => nodes.filter((n) => n.included).length
