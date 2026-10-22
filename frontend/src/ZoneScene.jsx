/**
 * ZoneScene — 2D Canvas world scene for EcoSim-MAS (Module 11, §9.1–9.2)
 *
 * Renders six zone tiles at fixed coordinates and 10 agent sprites,
 * driven by live WebSocket tick data from GET /ws/simulate/{run_id}.
 */

import React, { useEffect, useRef, useState } from 'react'

const TILE_SHEET_URL = '/sprites/tiles/Spritesheet/roguelikeSheet_transparent.png'
const CHAR_SHEET_URL = '/sprites/agent_source/Spritesheet/roguelikeChar_transparent.png'

// 10 personas from backend/fixtures/personas.json (order matches backend indexing)
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

// Persona slug generator matching backend: name.lower().replace(' ', '_')
function personaSlug(name) {
  return name.toLowerCase().replace(/ /g, '_')
}

// Normalize backend zone strings ("Café" -> "cafe") so they match ZONES keys.
// Lowercase + strip diacritics. Returns '' for empty input.
function normalizeZone(raw) {
  return (raw || '')
    .toString()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
}

// Needs-state bar styling (§9.3) — flat fills, no gradients (§9.4)
const NEED_BARS = [
  { key: 'budget_anxiety',         label: 'Budget anxiety',         color: '#A8574F' },
  { key: 'essential_pressure',     label: 'Essential pressure',     color: '#B8913F' },
  { key: 'discretionary_appetite', label: 'Discretionary appetite', color: '#5C7FA3' },
]
const DISCRETIONARY_ZONES = ['mall', 'cafe', 'theater']

// ── Zone definitions & Sprite Coordinates (§9.1, §9.2) ─────────────────────
// 17px grid interval: sx = col * 17, sy = row * 17
const ZONES = {
  home: {
    id: 'home',
    label: 'Home',
    row: 2,
    col: 40,
    x: 210,
    y: 150,
    color: '#8B9E7E',
    bgColor: 'rgba(139, 158, 126, 0.14)',
    borderColor: 'rgba(139, 158, 126, 0.5)',
  },
  workplace: {
    id: 'workplace',
    label: 'Workplace',
    row: 5,
    col: 44,
    x: 520,
    y: 90,
    color: '#7B8FA6',
    bgColor: 'rgba(123, 143, 166, 0.14)',
    borderColor: 'rgba(123, 143, 166, 0.5)',
  },
  mall: {
    id: 'mall',
    label: 'Mall',
    row: 3,
    col: 42,
    x: 820,
    y: 230,
    color: '#C4956A',
    bgColor: 'rgba(196, 149, 106, 0.14)',
    borderColor: 'rgba(196, 149, 106, 0.5)',
  },
  cafe: {
    id: 'cafe',
    label: 'Café',
    row: 4,
    col: 42,
    x: 720,
    y: 490,
    color: '#A67B5B',
    bgColor: 'rgba(166, 123, 91, 0.14)',
    borderColor: 'rgba(166, 123, 91, 0.5)',
  },
  theater: {
    id: 'theater',
    label: 'Theater',
    row: 3,
    col: 37,
    x: 410,
    y: 520,
    color: '#6A7B9E',
    bgColor: 'rgba(106, 123, 158, 0.14)',
    borderColor: 'rgba(106, 123, 158, 0.5)',
  },
  grocery: {
    id: 'grocery',
    label: 'Grocery',
    row: 2,
    col: 46,
    x: 180,
    y: 410,
    color: '#7E9E8B',
    bgColor: 'rgba(126, 158, 139, 0.14)',
    borderColor: 'rgba(126, 158, 139, 0.5)',
  },
}

// Agent sprite coordinate: row 5, col 0 in character sheet
const AGENT_SPRITE = { row: 5, col: 0 }

// Slots inside a zone: a two-column grid. Slot s -> column s % 2, row floor(s / 2).
// Slots are handed out by OCCUPANCY (first free slot in the zone), not by persona
// index, so a crowded zone fills neatly top-to-bottom instead of piling labels up.
const SLOT_COLS = [-62, 62]
const SLOT_ROW_Y0 = 34
const SLOT_ROW_GAP = 38
function slotOffset(slotIndex) {
  return {
    x: SLOT_COLS[slotIndex % 2],
    y: SLOT_ROW_Y0 + SLOT_ROW_GAP * Math.floor(slotIndex / 2),
  }
}

// Action type visual styling (§9.1, §9.2)
const ACTION_STYLES = {
  0: { label: 'SPEND', color: '#2F6FED', name: 'Spend' },    // Action 0: Spend -> accent blue
  1: { label: 'SAVE',  color: '#4E8752', name: 'Save' },     // Action 1: Save -> muted green
  2: { label: 'DEFAULT', color: '#C94A4A', name: 'Default' }, // Action 2: Default -> muted red/grey
}

// Initial zone placement round-robin for static placeholder layout
const ZONE_KEYS = Object.keys(ZONES)

function getInitialAgents() {
  const usedSlots = {}
  return PERSONAS.map((name, index) => {
    const aid = personaSlug(name)
    const initialZoneKey = ZONE_KEYS[index % ZONE_KEYS.length]
    const zone = ZONES[initialZoneKey]
    const slotIndex = (usedSlots[initialZoneKey] = (usedSlots[initialZoneKey] ?? -1) + 1)
    const slot = slotOffset(slotIndex)
    const startX = zone.x + slot.x
    const startY = zone.y + slot.y

    return {
      id: aid,
      name,
      index,
      zoneKey: initialZoneKey,
      slotZone: initialZoneKey, // zone whose slot this agent occupies (stays set when frozen)
      slot: slotIndex,
      currentX: startX,
      currentY: startY,
      targetX: startX,
      targetY: startY,
      actionType: null,
      isTerminated: false,
      needs: {
        budget_anxiety: 0.5,
        essential_pressure: 0.5,
        discretionary_appetite: 0.5,
      },
      // smoothed copy of needs used for drawing the bars
      displayNeeds: {
        budget_anxiety: 0.5,
        essential_pressure: 0.5,
        discretionary_appetite: 0.5,
      },
    }
  })
}

export default function ZoneScene({ runId, onTickUpdate, onStatusChange }) {
  const canvasRef = useRef(null)
  const agentsRef = useRef(getInitialAgents())
  const imagesRef = useRef({ tiles: null, chars: null })
  const [imagesLoaded, setImagesLoaded] = useState(false)
  const animFrameIdRef = useRef(null)
  // Latest-callback refs: App passes new function instances on every render, and
  // listing them as effect deps tore down and reopened the WebSocket on every
  // status change (socket closed before the first tick arrived). The WebSocket
  // effect below now depends on runId only.
  const onTickUpdateRef = useRef(onTickUpdate)
  const onStatusChangeRef = useRef(onStatusChange)
  useEffect(() => {
    onTickUpdateRef.current = onTickUpdate
    onStatusChangeRef.current = onStatusChange
  })
  // Co-location display state for the CURRENT tick only (§7.5):
  //   pairs:   drawable pairs [{a, b, zoneKey, label, showPill}]. A per-pair nudge
  //            pill is shown only when a zone has exactly 1 pair (more would overlap).
  //   summary: {zoneKey: pairCount} for zones with 2+ pairs -> one summary pill.
  //            Zones with >6 pairs get the summary pill only (no lines).
  const pairsRef = useRef({ pairs: [], summary: {} })

  // Load Spritesheets
  useEffect(() => {
    let loadedCount = 0
    const checkLoaded = () => {
      loadedCount++
      if (loadedCount === 2) {
        setImagesLoaded(true)
      }
    }

    const tileImg = new Image()
    tileImg.src = TILE_SHEET_URL
    tileImg.onload = () => {
      imagesRef.current.tiles = tileImg
      checkLoaded()
    }

    const charImg = new Image()
    charImg.src = CHAR_SHEET_URL
    charImg.onload = () => {
      imagesRef.current.chars = charImg
      checkLoaded()
    }
  }, [])

  // WebSocket Connection
  useEffect(() => {
    if (!runId) {
      onStatusChangeRef.current?.('idle')
      return
    }

    onStatusChangeRef.current?.('connecting')

    const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${wsProtocol}://${window.location.host}/ws/simulate/${runId}`
    const ws = new WebSocket(wsUrl)
    let completed = false // set once the server says simulation_complete

    ws.onopen = () => {
      onStatusChangeRef.current?.('connected')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.status === 'simulation_complete') {
          completed = true
          onStatusChangeRef.current?.('complete')
          ws.close()
          return
        }

        onTickUpdateRef.current?.(data)

        onStatusChangeRef.current?.(`streaming tick ${data.tick}`)

        // Update agent targets and action states
        const zoneAssignments = data.zone || {}
        const agentActions = data.agent_actions || {}
        const needsState = data.needs_state || {}

        const movers = []
        agentsRef.current.forEach((agent) => {
          const aid = agent.id

          // If agent has terminated, it stays frozen in place (§9.1, §9.2)
          if (agent.isTerminated) return

          // Action update
          if (agentActions[aid] !== undefined) {
            const act = agentActions[aid].action_type
            agent.actionType = act
            if (act === 2) {
              agent.isTerminated = true // Default -> freeze in place
            }
          }

          // Needs state update
          if (needsState[aid]) {
            agent.needs = needsState[aid]
          }

          // Zone assignment update (normalize to lowercase)
          const assignedZone = normalizeZone(zoneAssignments[aid])
          if (assignedZone && !ZONES[assignedZone]) {
            console.warn(`[ZoneScene] Unknown zone "${zoneAssignments[aid]}" for agent ${aid}`)
          }
          // An agent that defaulted this tick freezes where it stands (no move).
          if (assignedZone && ZONES[assignedZone] && !agent.isTerminated) {
            movers.push({ agent, zoneKey: assignedZone })
          }
        })

        // Slot allocation by occupancy (sticky: an agent that stays in its zone keeps
        // its slot; one that leaves frees it; arrivals take the lowest free slot).
        // Frozen agents keep their slot forever, so nobody is placed on top of them.
        const taken = {}
        agentsRef.current.forEach((a) => {
          if (a.slotZone != null) (taken[a.slotZone] = taken[a.slotZone] || new Set()).add(a.slot)
        })
        movers.forEach(({ agent, zoneKey }) => {
          if (agent.slotZone === zoneKey) return
          taken[agent.slotZone]?.delete(agent.slot)
          agent.slotZone = null
        })
        movers.forEach(({ agent, zoneKey }) => {
          agent.zoneKey = zoneKey
          if (agent.slotZone === zoneKey) return
          const used = (taken[zoneKey] = taken[zoneKey] || new Set())
          let slotIndex = 0
          while (used.has(slotIndex)) slotIndex++
          used.add(slotIndex)
          agent.slotZone = zoneKey
          agent.slot = slotIndex
          const zone = ZONES[zoneKey]
          const off = slotOffset(slotIndex)
          agent.targetX = zone.x + off.x
          agent.targetY = zone.y + off.y
        })
        // ── Co-located pairs for THIS tick only (§7.5) ───────────────────
        const agentById = {}
        agentsRef.current.forEach((a) => { agentById[a.id] = a })
        const perZone = {}
        ;(data.co_located_pairs || []).forEach((pair) => {
          const a = agentById[pair.agent_a]
          const b = agentById[pair.agent_b]
          const zk = normalizeZone(pair.zone)
          // Only draw pairs where both agents are active and actually standing in
          // that zone; frozen (defaulted) agents stay where they were, so a line to
          // them would stretch across the map and mislead.
          if (!a || !b || a.isTerminated || b.isTerminated) return
          if (a.zoneKey !== zk || b.zoneKey !== zk) return
          const labelFor = (peerId, nudge) => {
            if (!nudge) return null
            const peerAct = agentActions[peerId]?.action_type
            const need = peerAct === 0 && DISCRETIONARY_ZONES.includes(zk) ? 'app' : 'anx'
            return `${nudge > 0 ? '+' : '\u2212'}${Math.abs(nudge).toFixed(2)} ${need}`
          }
          const l1 = labelFor(pair.agent_a, pair.nudge_a_on_b)
          const l2 = labelFor(pair.agent_b, pair.nudge_b_on_a)
          const parts = [l1, l2].filter(Boolean)
          const label = parts.length === 2 && parts[0] === parts[1]
            ? `${parts[0]} \u00d72`
            : parts.join(' | ')
          ;(perZone[zk] = perZone[zk] || []).push({ a, b, zoneKey: zk, label })
        })
        const pairs = []
        const summary = {}
        Object.entries(perZone).forEach(([zk, list]) => {
          if (list.length > 1) summary[zk] = list.length
          if (list.length > 6) return // too dense for lines: summary pill only
          list.forEach((pr) => pairs.push({ ...pr, showPill: list.length === 1 }))
        })
        pairsRef.current = { pairs, summary }
      } catch (err) {
        console.error('Error parsing simulation WebSocket message:', err)
      }
    }

    ws.onerror = (err) => {
      console.error('Simulation WebSocket error:', err)
      onStatusChangeRef.current?.('error')
    }

    ws.onclose = () => {
      // Don't overwrite 'complete' with 'disconnected' on a normal end of run
      if (!completed) onStatusChangeRef.current?.('disconnected')
    }

    return () => {
      ws.close()
    }
  }, [runId])

  // Canvas Render Loop
  useEffect(() => {
    let lastTime = performance.now()

    const render = (now) => {
      const dt = Math.min((now - lastTime) / 1000, 0.1) // clamp delta time
      lastTime = now

      const canvas = canvasRef.current
      if (!canvas) {
        animFrameIdRef.current = requestAnimationFrame(render)
        return
      }

      const ctx = canvas.getContext('2d')
      const width = canvas.width
      const height = canvas.height

      // Crisp pixel art settings
      ctx.imageSmoothingEnabled = false

      // ── 1. Clear & Background ──────────────────────────────────────────
      ctx.fillStyle = '#FAFAF8' // --color-bg
      ctx.fillRect(0, 0, width, height)

      // Subtle ground grid dots (flat, minimal)
      ctx.fillStyle = '#E5E5E0'
      const gridStep = 40
      for (let gx = 20; gx < width; gx += gridStep) {
        for (let gy = 20; gy < height; gy += gridStep) {
          ctx.fillRect(gx, gy, 2, 2)
        }
      }

      const tilesImg = imagesRef.current.tiles
      const charsImg = imagesRef.current.chars

      // ── 2. Draw Zone Buildings ─────────────────────────────────────────
      Object.values(ZONES).forEach((zone) => {
        const { x, y, label, row, col, bgColor, borderColor, color } = zone

        // Zone area background card
        const cardW = 170
        const cardH = 244
        const cardX = x - cardW / 2
        const cardY = y - 36

        ctx.fillStyle = bgColor
        ctx.strokeStyle = borderColor
        ctx.lineWidth = 1

        // Rounded rect for zone card
        drawRoundedRect(ctx, cardX, cardY, cardW, cardH, 8)
        ctx.fill()
        ctx.stroke()

        // Draw 16x16 building tile scaled 3x (48x48px)
        const tileScale = 3
        const tileDrawSize = 16 * tileScale
        const tileDrawX = x - tileDrawSize / 2
        const tileDrawY = y - tileDrawSize / 2

        if (tilesImg) {
          const sx = col * 17
          const sy = row * 17
          ctx.drawImage(
            tilesImg,
            sx, sy, 16, 16,
            tileDrawX, tileDrawY, tileDrawSize, tileDrawSize
          )
        }

        // Zone Name Label Pill
        ctx.font = '600 11px Inter, system-ui, sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'

        const textMetrics = ctx.measureText(label.toUpperCase())
        const pillW = textMetrics.width + 14
        const pillH = 18
        const pillX = x - pillW / 2
        const pillY = y - tileDrawSize / 2 - 16

        ctx.fillStyle = '#FFFFFF'
        ctx.strokeStyle = '#E5E5E0'
        ctx.lineWidth = 1
        drawRoundedRect(ctx, pillX, pillY, pillW, pillH, 4)
        ctx.fill()
        ctx.stroke()

        ctx.fillStyle = color
        ctx.fillText(label.toUpperCase(), x, pillY + pillH / 2)
      })

      // ── 2b. Co-location lines (§7.5) — drawn under the sprites ──────────
      const { pairs: livePairs, summary: summaryZones } = pairsRef.current
      ctx.save()
      ctx.strokeStyle = 'rgba(90, 90, 84, 0.45)'
      ctx.lineWidth = 1
      ctx.setLineDash([4, 3])
      livePairs.forEach(({ a, b }) => {
        ctx.beginPath()
        ctx.moveTo(Math.round(a.currentX), Math.round(a.currentY))
        ctx.lineTo(Math.round(b.currentX), Math.round(b.currentY))
        ctx.stroke()
      })
      ctx.restore()

      // ── 3. Update & Draw Agents ────────────────────────────────────────
      const agents = agentsRef.current

      // Sort by Y for natural depth overlap
      const sortedAgents = [...agents].sort((a, b) => a.currentY - b.currentY)

      sortedAgents.forEach((agent) => {
        // Tween position toward target over ~1s
        if (!agent.isTerminated) {
          const dx = agent.targetX - agent.currentX
          const dy = agent.targetY - agent.currentY
          const dist = Math.sqrt(dx * dx + dy * dy)

          if (dist > 0.5) {
            agent.currentX += dx * Math.min(1, 3.2 * dt)
            agent.currentY += dy * Math.min(1, 3.2 * dt)
          } else {
            agent.currentX = agent.targetX
            agent.currentY = agent.targetY
          }
        }

        const ax = Math.round(agent.currentX)
        const ay = Math.round(agent.currentY)

        // Draw shadow under agent
        ctx.fillStyle = 'rgba(0, 0, 0, 0.12)'
        ctx.beginPath()
        ctx.ellipse(ax, ay + 14, 10, 4, 0, 0, Math.PI * 2)
        ctx.fill()

        // Draw Character Sprite (2.25x scale = 36x36px)
        const charScale = 2.25
        const charDrawSize = 16 * charScale
        const charX = ax - charDrawSize / 2
        const charY = ay - charDrawSize / 2

        if (charsImg) {
          const sx = AGENT_SPRITE.col * 17
          const sy = AGENT_SPRITE.row * 17
          ctx.drawImage(
            charsImg,
            sx, sy, 16, 16,
            charX, charY, charDrawSize, charDrawSize
          )
        }

        // Action corner badge (§9.1, §9.2)
        if (agent.actionType !== null && ACTION_STYLES[agent.actionType]) {
          const badgeStyle = ACTION_STYLES[agent.actionType]
          const badgeX = ax + 10
          const badgeY = ay - 12
          const badgeRadius = 4.5

          // Outer ring
          ctx.fillStyle = '#FFFFFF'
          ctx.beginPath()
          ctx.arc(badgeX, badgeY, badgeRadius + 1.5, 0, Math.PI * 2)
          ctx.fill()

          // Inner colored badge
          ctx.fillStyle = badgeStyle.color
          ctx.beginPath()
          ctx.arc(badgeX, badgeY, badgeRadius, 0, Math.PI * 2)
          ctx.fill()
        }

        // Floating Persona Name Label
        ctx.font = '500 10px Inter, system-ui, sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'

        const nameMetrics = ctx.measureText(agent.name)
        const labelW = nameMetrics.width + 10
        const labelH = 16
        const labelX = ax - labelW / 2
        const labelY = ay - 28

        ctx.fillStyle = 'rgba(255, 255, 255, 0.92)'
        ctx.strokeStyle = agent.actionType === 0 ? '#2F6FED' : (agent.actionType === 1 ? '#4E8752' : (agent.actionType === 2 ? '#C94A4A' : '#D0D0C8'))
        ctx.lineWidth = 1
        drawRoundedRect(ctx, labelX, labelY, labelW, labelH, 4)
        ctx.fill()
        ctx.stroke()

        ctx.fillStyle = '#1A1A18'
        ctx.fillText(agent.name, ax, labelY + labelH / 2)

        // Needs bars (§9.3): three thin flat bars to the right of the sprite.
        // Displayed values ease toward the latest tick values instead of snapping.
        const barW = 24
        const barH = 3
        const barGap = 2
        const barX = ax + 20
        const barY0 = ay - 6
        ctx.save()
        if (agent.isTerminated) ctx.globalAlpha = 0.45
        NEED_BARS.forEach((nb, i) => {
          const target = Math.max(0, Math.min(1, agent.needs?.[nb.key] ?? 0))
          const cur = agent.displayNeeds[nb.key]
          agent.displayNeeds[nb.key] = cur + (target - cur) * Math.min(1, 4 * dt)
          const by = barY0 + i * (barH + barGap)
          ctx.fillStyle = '#E5E5E0'
          ctx.fillRect(barX, by, barW, barH)
          ctx.fillStyle = nb.color
          ctx.fillRect(barX, by, Math.max(0, barW * agent.displayNeeds[nb.key]), barH)
        })
        ctx.restore()
      })

      // ── 3b. Co-location pills (§7.5) — drawn above the sprites ──────────
      livePairs.forEach(({ a, b, label, showPill }) => {
        if (!label || !showPill) return
        const mx = (a.currentX + b.currentX) / 2
        const my = (a.currentY + b.currentY) / 2
        drawPill(ctx, label, mx, my, '#5A5A54')
      })
      Object.entries(summaryZones).forEach(([zk, count]) => {
        const z = ZONES[zk]
        if (!z) return
        drawPill(ctx, `${count} peer pairs`, z.x, z.y - 62, '#5A5A54')
      })

      // ── 3c. Needs legend (bottom-left) ───────────────────────────────────
      ctx.save()
      ctx.font = '500 10px Inter, system-ui, sans-serif'
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      const legendX = 16
      const legendY = height - 14 - (NEED_BARS.length - 1) * 16
      NEED_BARS.forEach((nb, i) => {
        const ly = legendY + i * 16
        ctx.fillStyle = nb.color
        ctx.fillRect(legendX, ly - 2, 18, 4)
        ctx.fillStyle = '#6B6B68'
        ctx.fillText(nb.label, legendX + 26, ly)
      })
      ctx.restore()

      animFrameIdRef.current = requestAnimationFrame(render)
    }

    animFrameIdRef.current = requestAnimationFrame(render)

    return () => {
      if (animFrameIdRef.current) {
        cancelAnimationFrame(animFrameIdRef.current)
      }
    }
  }, [imagesLoaded])

  return (
    <div style={{
      width: '100%',
      height: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#EFF0F2',
      position: 'relative',
      overflow: 'hidden',
    }}>
      <canvas
        ref={canvasRef}
        width={1020}
        height={800}
        style={{
          maxWidth: '100%',
          maxHeight: '100%',
          borderRadius: '8px',
          border: '1px solid #E5E5E0',
          background: '#FAFAF8',
        }}
      />
    </div>
  )
}

// Utility: draw rounded rectangle
function drawRoundedRect(ctx, x, y, width, height, radius) {
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.lineTo(x + width - radius, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius)
  ctx.lineTo(x + width, y + height - radius)
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height)
  ctx.lineTo(x + radius, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius)
  ctx.lineTo(x, y + radius)
  ctx.quadraticCurveTo(x, y, x + radius, y)
  ctx.closePath()
}

// Utility: small flat pill with centered text
function drawPill(ctx, text, cx, cy, textColor) {
  ctx.save()
  ctx.font = '600 9px Inter, system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const w = ctx.measureText(text).width + 10
  const h = 14
  ctx.fillStyle = 'rgba(255, 255, 255, 0.95)'
  ctx.strokeStyle = '#D0D0C8'
  ctx.lineWidth = 1
  drawRoundedRect(ctx, cx - w / 2, cy - h / 2, w, h, 4)
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = textColor
  ctx.fillText(text, cx, cy)
  ctx.restore()
}
