/**
 * AgentLayer — places 10 persona agents in the 3D scene (Module 11b).
 *
 * Static placeholder layout: agents are spread across zone anchor
 * positions with small XZ offsets so they don't perfectly overlap.
 * Real zone routing from the WebSocket comes in 11c.
 *
 * All 10 persona names come from backend/fixtures/personas.json.
 * Displayed in the same order the backend assigns agent_ids.
 */

import AgentMesh from './AgentMesh'

// 10 personas from backend/fixtures/personas.json (same order, same names)
const PERSONAS = [
  'Frugal Senior',
  'Aggressive Student',
  'Cautious Professional',
  'Impulse Spender',
  'Optimistic Entrepreneur',
  'Struggling Worker',
  'Balanced Family',
  'Wealthy Retiree',
  'Tech-Savvy Investor',
  'Conservative Saver',
]

// Zone anchor positions from ZoneScene.jsx (kept in sync manually for now)
const ZONE_ANCHORS = {
  home:       [-14,  0, -8],
  workplace:  [  0,  0, -14],
  mall:       [ 14,  0, -4],
  cafe:       [ 10,  0, 10],
  theater:    [ -6,  0, 12],
  grocery:    [-16,  0,  6],
}

// Spread 10 agents across zones — static initial layout.
// Small XZ offsets prevent overlap when multiple agents share an anchor.
// OFFSET grid: 5 positions per zone (2 rows × 2 columns + 1 centre)
const OFFSETS = [
  [ 0.0,  0.0],  // centre
  [-1.1,  1.1],  // back-left
  [ 1.1,  1.1],  // back-right
  [-1.1, -1.1],  // front-left
  [ 1.1, -1.1],  // front-right
]

// Assign agents to zones round-robin
const ZONE_KEYS = Object.keys(ZONE_ANCHORS)  // 6 zones

const AGENT_PLACEMENTS = PERSONAS.map((name, i) => {
  const zoneKey  = ZONE_KEYS[i % ZONE_KEYS.length]
  const anchor   = ZONE_ANCHORS[zoneKey]
  const offset   = OFFSETS[i % OFFSETS.length]
  return {
    name,
    position: [
      anchor[0] + offset[0],
      anchor[1],          // Y stays 0 (ground)
      anchor[2] + offset[1],
    ],
  }
})

export default function AgentLayer() {
  return (
    <>
      {AGENT_PLACEMENTS.map(({ name, position }) => (
        <AgentMesh
          key={name}
          position={position}
          name={name}
          clipName="Idle"
        />
      ))}
    </>
  )
}
