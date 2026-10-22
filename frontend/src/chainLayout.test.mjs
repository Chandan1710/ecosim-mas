import assert from 'node:assert/strict'
import { layoutChain, addEffect, removeNode, setIncluded, descendants, ancestors } from './chainLayout.js'

const N = (id, deps = []) => ({ id, description: `n${id}`, depends_on: deps, included: true })

// a plain chain is one straight line: every node in lane 0, one per row
let L = layoutChain([N(1), N(2, [1]), N(3, [2]), N(4, [3])])
assert.equal(L.lanes, 1)
assert.deepEqual([1, 2, 3, 4].map((i) => L.pos.get(i)), [0, 1, 2, 3].map((r) => ({ row: r, lane: 0 })))
assert.ok(L.edges.every((e) => e.direct))

// a branch: node 1 has two effects; the second starts lane 1; the spine stays in lane 0
L = layoutChain([N(1), N(2, [1]), N(3, [1]), N(4, [2])])
assert.deepEqual(L.pos.get(2), { row: 1, lane: 0 })
assert.deepEqual(L.pos.get(3), { row: 1, lane: 1 })
assert.deepEqual(L.pos.get(4), { row: 2, lane: 0 })
assert.equal(L.lanes, 2)

// a merge returns to the left-most lane
L = layoutChain([N(1), N(2, [1]), N(3, [1]), N(4, [2, 3])])
assert.deepEqual(L.pos.get(4), { row: 2, lane: 0 })
assert.equal(L.edges.filter((e) => e.to === 4).length, 2)

// two nodes never share a cell
const wide = layoutChain([N(1), N(2, [1]), N(3, [1]), N(4, [1]), N(5, [2]), N(6, [3]), N(7, [4]), N(8, [5, 6, 7])])
const cells = [...wide.pos.values()].map((p) => `${p.row}/${p.lane}`)
assert.equal(new Set(cells).size, cells.length)

// an edge that skips a row is marked, so it can be routed through the gutter
L = layoutChain([N(1), N(2, [1]), N(3, [2]), N(4, [1, 3])])
assert.equal(L.edges.find((e) => e.from === 1 && e.to === 4).direct, false)

// reading numbers go top to bottom, left to right
L = layoutChain([N(1), N(2, [1]), N(3, [1])])
assert.deepEqual([1, 2, 3].map((i) => L.number.get(i)), [1, 2, 3])

// editing
let r = addEffect([N(1), N(2, [1])], 2)
assert.equal(r.id, 3); assert.deepEqual(r.nodes.at(-1).depends_on, [2]); assert.equal(r.nodes.at(-1).added, true)
let rm = removeNode([N(1), N(2, [1]), N(3, [2]), N(4, [2])], 2)
assert.deepEqual(rm.find((n) => n.id === 3).depends_on, [1]); assert.deepEqual(rm.find((n) => n.id === 4).depends_on, [1])
assert.equal(setIncluded([N(1)], 1, false)[0].included, false)
assert.deepEqual([...descendants([N(1), N(2, [1]), N(3, [2]), N(4)], 1)].sort(), [2, 3])
assert.deepEqual([...ancestors([N(1), N(2, [1]), N(3, [2])], 3)].sort(), [1, 2])

// a cycle (bad data) must not hang
layoutChain([N(1, [2]), N(2, [1])])
console.log('chainLayout: all good')
