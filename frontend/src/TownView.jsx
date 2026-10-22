/**
 * TownView — the live town of generative agents (ARCHITECTURE §7.6).
 *
 * One WebSocket gives the run's events: everything so far, then live ones.
 * A small player paces them so you can watch: agents plan their day (thought
 * bubbles), walk the roads to where they chose to go, talk (speech bubbles)
 * and live with the consequences. Finished runs replay the same way, at the
 * speed you pick, without calling the LLM again.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './town.css'
import { getTownRun, reportUrl, stopTownRun, townSocketUrl } from './api'
import { buildRoadGraph, doorway, pathLength, pointAlong, roadPath, slotIn } from './townGeometry'
import { buildScene, T } from './townScene'
import { appearanceFor, spriteFrame, SPRITE_H, SPRITE_W } from './townSprites'

const PHASE_LABEL = { morning: 'Morning', afternoon: 'Afternoon', evening: 'Evening' }
const STATUS_COLOR = { ok: '#4E8752', strain: '#E0A030', crisis: '#D9503F' }
// colour the whole town is multiplied by, per time of day (white = daylight)
const TINT = {
  planning: [255, 238, 218], morning: [255, 250, 240], afternoon: [255, 255, 255],
  evening: [238, 184, 156], night: [128, 140, 196], done: [255, 255, 255],
}
const SHORT = {
  shanti_apts: 'Shanti Nagar Flats', old_town: 'Old Town Houses', labour_colony: 'Labour Colony', lake_view: 'Lake View',
  kirana: 'Ravi Kirana', supermarket: 'FreshMart', market: 'Sabzi Market', pharmacy: 'Pharmacy', fuel_station: 'Fuel Station',
  cafe: 'Corner Café', restaurant: 'Spice Garden', mall: 'Mall & Cinema', tech_park: 'TechPark', factory: 'Garment Factory',
  construction: 'Metro Site', school: 'School & College', clinic: 'Clinic', auto_stand: 'Auto Stand', bank: 'Co-op Bank', park: 'Lake Park',
}
const WALK_MAX_MS = 2800 // the longest anyone takes to get anywhere, however far
const MS_PER_TILE = 150
const MAX_FEED = 400

const rs = (v) => `₹${Math.round(v || 0).toLocaleString('en-IN')}`
const firstName = (name) => (name || '').split(' ')[0]
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const clip = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || '')

// same rules as the PDF reports (backend town/analysis.py)
function statusOf(a) {
  const s = a.snap
  if (!s) return 'ok'
  if (s.defaulted || s.days_hungry >= 2 || (a.wasEmployed && !s.employed)) return 'crisis'
  const drop = a.startMoney > 0 ? (a.startMoney - s.money) / a.startMoney : 0
  if (a.borrowedFromMoneylender || a.skippedBill || s.khata_due > 0 || s.days_hungry >= 1 || drop > 0.4) return 'strain'
  return 'ok'
}

export default function TownView({ runId, onExit }) {
  const canvasRef = useRef(null)
  const wrapRef = useRef(null)
  const sim = useRef({ map: null, graph: null, agents: {}, placeName: {} })
  const queue = useRef([])
  const wake = useRef(null)
  const speedRef = useRef(1)
  const skipRef = useRef(false)
  const modeRef = useRef('live')
  const selectedRef = useRef(null)
  const scaleRef = useRef({ tile: 14, ox: 0, oy: 0, scale: 1 })
  const hoverRef = useRef(null)
  const tintRef = useRef(TINT.planning.slice())

  const [meta, setMeta] = useState(null) // from run_start
  const [runInfo, setRunInfo] = useState(null) // from the API (status, stories)
  const [clock, setClock] = useState({ day: 0, weekday: '', phase: '', planning: null })
  const [prices, setPrices] = useState(null)
  const [town, setTown] = useState(null)
  const [feed, setFeed] = useState([])
  const [bubbles, setBubbles] = useState([])
  const [selected, setSelected] = useState(null)
  const [version, setVersion] = useState(0)
  const [conn, setConn] = useState('connecting') // connecting | live | replay | ended | error
  const [speed, setSpeed] = useState(1)
  const [finished, setFinished] = useState(null) // { stopped }
  const [endOpen, setEndOpen] = useState(true) // the results pop-up can be closed
  const [banner, setBanner] = useState(null)
  const [error, setError] = useState('')
  const [counts, setCounts] = useState({ llm: 0, routine: 0, fallback: 0, talks: 0, reflections: 0 })

  speedRef.current = speed
  selectedRef.current = selected

  const bump = () => setVersion((v) => v + 1)
  const pushFeed = (item) => setFeed((f) => [{ ...item, key: `${Date.now()}-${Math.random()}` }, ...f].slice(0, MAX_FEED))
  const name = (id) => sim.current.agents[id]?.name || id

  const showBubble = useCallback((agentId, text, kind, ms) => {
    const id = `${agentId}-${Date.now()}-${Math.random()}`
    // at most 3 on screen; a conversation outranks a passing thought
    setBubbles((b) => {
      let next = [...b.filter((x) => x.agentId !== agentId), { id, agentId, text, kind }]
      while (next.length > 3) {
        const drop = next.findIndex((x) => x.kind === 'thought' && x.id !== id)
        next.splice(drop >= 0 ? drop : 0, 1)
      }
      return next
    })
    setTimeout(() => setBubbles((b) => b.filter((x) => x.id !== id)), ms)
  }, [])

  /* ── slots: who stands where inside each building ───────────────────── */
  const reslot = useCallback(() => {
    const { agents, graph } = sim.current
    if (!graph) return
    const byPlace = {}
    Object.values(agents).forEach((a) => (byPlace[a.dest] = byPlace[a.dest] || []).push(a))
    Object.entries(byPlace).forEach(([pid, list]) => {
      list.sort((x, y) => x.id.localeCompare(y.id))
      list.forEach((a, i) => {
        a.slot = slotIn(graph.places[pid], i, list.length)
        if (a.path) a.path[a.path.length - 1] = a.slot
      })
    })
  }, [])

  /* ── applying one event to the town ─────────────────────────────────── */
  const apply = useCallback((ev, fast) => {
    const S = sim.current
    switch (ev.type) {
      case 'run_start': {
        // a (re)connected stream starts from the beginning: reset everything derived from it
        setCounts({ llm: 0, routine: 0, fallback: 0, talks: 0, reflections: 0 })
        setFeed([])
        setTown(null)
        setFinished(null)
        setEndOpen(true)
        S.map = ev.map
        S.graph = buildRoadGraph(ev.map)
        S.placeName = Object.fromEntries(ev.map.places.map((p) => [p.id, p.name]))
        S.scene = buildScene(ev.map)
        S.agents = {}
        ev.agents.forEach((p) => {
          S.agents[p.id] = {
            ...p, profile: p, snap: null, plan: null, thought: '', mode: '', log: [], dest: p.home,
            pos: null, slot: null, path: null, startMoney: 0, wasEmployed: p.employed,
            look: appearanceFor(p), dir: 'down', movedAt: 0,
          }
        })
        reslot()
        Object.values(S.agents).forEach((a) => (a.pos = { ...a.slot }))
        setMeta({ title: ev.title, days: ev.days, shock: ev.shock, onset: ev.shock_onset_day, full: ev.shock_full_day,
          providers: ev.providers, brain: ev.brain, headlines: ev.headlines })
        bump()
        break
      }
      case 'day_start': {
        setClock({ day: ev.day, weekday: ev.weekday, phase: 'planning', planning: 0 })
        S.closed = ev.closed ? new Set(ev.closed) : null // places shut today (calendar, lockdown, disaster)
        setPrices({ ...ev.prices, fuel_price: ev.fuel_price })
        if (!fast) setBanner({ day: ev.day, weekday: ev.weekday, news: ev.news })
        pushFeed({ type: 'day', day: ev.day, weekday: ev.weekday, news: ev.news })
        Object.values(S.agents).forEach((a) => {
          a.dest = a.profile.home
          a.path = null
        })
        reslot()
        Object.values(S.agents).forEach((a) => (a.pos = { ...a.slot })) // overnight, everyone is home
        break
      }
      case 'decision': {
        const a = S.agents[ev.agent]
        if (!a) break
        a.plan = ev.plan
        a.thought = ev.thought
        a.mode = ev.mode
        a.learned = ev.learned || []
        if (ev.mode !== 'routine' && ev.plan?.money?.skip?.length) a.skippedBill = true
        setClock((c) => ({ ...c, planning: (c.planning || 0) + 1 }))
        setCounts((c) => ({ ...c, [ev.mode === 'mock' ? 'fallback' : ev.mode]: (c[ev.mode === 'mock' ? 'fallback' : ev.mode] || 0) + 1 }))
        if (ev.mode !== 'routine') {
          a.log.unshift({ day: ev.day, type: 'thought', text: ev.thought })
          pushFeed({ type: 'thought', day: ev.day, agent: ev.agent, text: ev.thought, mode: ev.mode, provider: ev.provider,
            learned: (ev.learned || []).length })
          if (!fast) showBubble(ev.agent, clip(ev.thought, 90), 'thought', 3600 / speedRef.current + 600)
        }
        if (selectedRef.current === ev.agent) bump()
        break
      }
      case 'move': {
        const a = S.agents[ev.agent]
        if (!a || !S.graph) break
        setClock((c) => ({ ...c, phase: ev.phase }))
        a.from = ev.from
        a.dest = ev.to
        if (fast) {
          a.path = null
        } else {
          const road = roadPath(S.graph, ev.from, ev.to)
          const out = doorway(S.graph.places[ev.from] || S.graph.places[ev.to]).slice().reverse()
          const into = doorway(S.graph.places[ev.to])
          a.path = [{ ...a.pos }, ...(ev.from === ev.to ? [] : out), ...road, ...(ev.from === ev.to ? [] : into), null]
          a.walkStart = performance.now()
          // people walk at a steady pace; very long trips are sped up so everyone arrives together
          const len = pathLength(a.path.filter(Boolean)) + 3
          a.walkMs = Math.min(WALK_MAX_MS, Math.max(900, len * MS_PER_TILE)) / speedRef.current
          S.maxWalk = Math.max(S.maxWalk || 0, a.walkMs)
        }
        S.moved = true
        S.walkPending = S.walkPending || !fast
        break
      }
      case 'action': {
        const a = S.agents[ev.agent]
        if (!a) break
        setClock((c) => (ev.phase && c.phase !== ev.phase ? { ...c, phase: ev.phase } : c))
        a.log.unshift({ day: ev.day, type: ev.ok ? 'action' : 'problem', text: ev.text, importance: ev.importance })
        if (ev.ok && ev.kind === 'money' && /moneylender/i.test(ev.text) && /borrowed/i.test(ev.text)) a.borrowedFromMoneylender = true
        if (ev.importance >= 6 || (!ev.ok && ev.importance >= 5)) {
          pushFeed({ type: ev.ok ? 'event' : 'problem', day: ev.day, agent: ev.agent, text: ev.text })
        }
        if (selectedRef.current === ev.agent) bump()
        break
      }
      case 'conversation': {
        setCounts((c) => ({ ...c, talks: c.talks + 1 }))
        const lines = (ev.dialogue || []).filter((l) => l && l.text)
        pushFeed({ type: 'talk', day: ev.day, a: ev.a, b: ev.b, place: S.placeName[ev.place] || ev.place, lines })
        ;[ev.a, ev.b].forEach((id) => {
          const ag = S.agents[id]
          if (ag) ag.log.unshift({ day: ev.day, type: 'talk', text: `Talked with ${name(id === ev.a ? ev.b : ev.a)}: ${(ev.learned || {})[id] || ''}` })
        })
        if (!fast) {
          const la = lines.find((l) => l.speaker === ev.a) || lines[0]
          const lb = lines.find((l) => l.speaker === ev.b) || lines[1]
          if (la) showBubble(ev.a, clip(la.text, 100), 'speech', 3600 / speedRef.current + 600)
          if (lb) setTimeout(() => showBubble(ev.b, clip(lb.text, 100), 'speech', 3200 / speedRef.current + 600), 700 / speedRef.current)
        }
        break
      }
      case 'reflection': {
        setCounts((c) => ({ ...c, reflections: c.reflections + 1 }))
        const a = S.agents[ev.agent]
        if (a) a.log.unshift({ day: ev.day, type: 'reflection', text: (ev.insights || []).join(' ') })
        pushFeed({ type: 'reflection', day: ev.day, agent: ev.agent, insights: ev.insights || [] })
        if (!fast) showBubble(ev.agent, clip(`Realised: ${(ev.insights || [])[0] || ''}`, 120), 'thought', 4200 / speedRef.current + 600)
        break
      }
      case 'day_end': {
        Object.entries(ev.agents || {}).forEach(([id, snap]) => {
          const a = S.agents[id]
          if (!a) return
          if (!a.snap) a.startMoney = snap.money
          a.snap = snap
          a.status = statusOf(a)
          if (ev.rewards?.[id]) {
            a.reward = ev.rewards[id]
            a.rewardSum = (a.rewardSum || 0) + ev.rewards[id].total
          }
        })
        setTown(ev.town)
        setClock((c) => ({ ...c, phase: 'night' }))
        bump()
        break
      }
      case 'lessons':
        Object.entries(ev.agents || {}).forEach(([id, ls]) => { if (S.agents[id]) S.agents[id].lessons = ls })
        bump()
        break
      case 'run_end':
        setFinished({ stopped: false, learning: ev.learning })
        setClock((c) => ({ ...c, phase: 'done' }))
        break
      default:
        break
    }
  }, [reslot, showBubble])

  const delayFor = (ev) => {
    switch (ev.type) {
      case 'day_start': return 1500
      case 'decision': return ev.mode === 'routine' ? 0 : 320
      case 'action': return ev.importance >= 6 ? 450 : 25
      case 'conversation': return 2800
      case 'reflection': return 1800
      case 'day_end': return 900
      default: return 0
    }
  }

  /* ── the player: paces queued events ────────────────────────────────── */
  useEffect(() => {
    let alive = true
    let ws = null
    let ended = false

    const push = (ev) => {
      queue.current.push(ev)
      if (wake.current) {
        wake.current()
        wake.current = null
      }
    }

    const loop = async () => {
      while (alive) {
        if (!queue.current.length) {
          if (ended) {
            setConn('ended')
            return
          }
          await new Promise((r) => (wake.current = r))
          continue
        }
        const ev = queue.current.shift()
        if (ev.type === 'stream_end') {
          ended = true
          if (ev.status && ev.status !== 'done') setFinished((f) => f || { stopped: true, status: ev.status })
          continue
        }
        if (ev.type === 'error') {
          setError(ev.message || 'Stream error')
          continue
        }
        // joining a live run late: catch up instantly instead of replaying the backlog slowly
        const fast = skipRef.current || (modeRef.current === 'live' && queue.current.length > 150)
        if (ev.type !== 'move' && sim.current.moved) {
          sim.current.moved = false
          reslot()
          const walk = sim.current.walkPending
          sim.current.walkPending = false
          if (walk && !fast) await sleep((sim.current.maxWalk || 1000) + 120)
          sim.current.maxWalk = 0
        }
        apply(ev, fast)
        if (ev.type === 'move') continue
        const d = fast ? 0 : delayFor(ev) / speedRef.current
        if (d > 0) await sleep(d)
        if (ev.type === 'day_start') setBanner(null)
      }
    }

    getTownRun(runId)
      .then((info) => {
        if (!alive) return
        setRunInfo(info)
        modeRef.current = info.status === 'running' ? 'live' : 'replay'
        setConn(modeRef.current)
        ws = new WebSocket(townSocketUrl(runId))
        ws.onmessage = (m) => {
          try {
            push(JSON.parse(m.data))
          } catch {
            /* ignore malformed */
          }
        }
        ws.onerror = () => setError('Lost the connection to the backend.')
        ws.onclose = () => push({ type: 'stream_end' })
        loop()
      })
      .catch((e) => {
        setError(e.message)
        setConn('error')
      })

    return () => {
      alive = false
      if (ws) ws.close()
      if (wake.current) wake.current()
      queue.current = []
    }
  }, [runId, apply, reslot])

  // once finished, keep asking until the LLM-written stories for the reports are ready
  useEffect(() => {
    if (!finished) return undefined
    let alive = true
    let tries = 0
    const poll = async () => {
      try {
        const info = await getTownRun(runId)
        if (!alive) return
        setRunInfo(info)
        if (info.status === 'running' || (info.stories === 'writing' && tries < 40)) {
          tries += 1
          setTimeout(poll, 3000)
        }
      } catch {
        /* reports still work without stories */
      }
    }
    poll()
    return () => {
      alive = false
    }
  }, [finished, runId])

  /* ── drawing ────────────────────────────────────────────────────────── */
  useEffect(() => {
    let raf
    const draw = () => {
      raf = requestAnimationFrame(draw)
      const canvas = canvasRef.current
      const wrap = wrapRef.current
      const S = sim.current
      if (!canvas || !wrap || !S.map || !S.scene) return
      const W = wrap.clientWidth
      const H = wrap.clientHeight
      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
        canvas.width = Math.round(W * dpr)
        canvas.height = Math.round(H * dpr)
        canvas.style.width = `${W}px`
        canvas.style.height = `${H}px`
      }
      const NW = S.scene.width
      const NH = S.scene.height
      const scale = Math.max(0.3, Math.min((W - 8) / NW, (H - 8) / NH))
      const tile = T * scale
      const ox = Math.round(((W - NW * scale) / 2) * dpr) / dpr
      const oy = Math.round(((H - NH * scale) / 2) * dpr) / dpr
      scaleRef.current = { tile, ox, oy, scale }
      const ctx = canvas.getContext('2d')
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.imageSmoothingEnabled = false
      ctx.fillStyle = '#3F7A38'
      ctx.fillRect(0, 0, W, H)
      ctx.drawImage(S.scene.canvas, ox, oy, NW * scale, NH * scale)

      const now = performance.now()
      const weekday = S.weekday
      const isClosed = (p) => (S.closed ? S.closed.has(p.id) : Boolean(weekday && (p.closed_days || []).includes(weekday)))

      // closed places are greyed out
      S.map.places.forEach((p) => {
        if (isClosed(p)) {
          ctx.fillStyle = 'rgba(34, 38, 66, 0.34)'
          ctx.fillRect(ox + p.rect.x * tile, oy + p.rect.y * tile, p.rect.w * tile, p.rect.h * tile)
        }
      })

      // move everyone
      const list = Object.values(S.agents)
      list.forEach((a) => {
        if (!a.slot) return
        const before = a.pos ? { x: a.pos.x, y: a.pos.y } : null
        if (a.path) {
          if (a.path[a.path.length - 1] === null) a.path[a.path.length - 1] = a.slot
          const t = Math.min(1, (now - a.walkStart) / a.walkMs)
          a.pos = pointAlong(a.path, t)
          if (t >= 1) a.path = null
        } else if (a.pos) {
          a.pos = { x: a.pos.x + (a.slot.x - a.pos.x) * 0.2, y: a.pos.y + (a.slot.y - a.pos.y) * 0.2 }
        } else {
          a.pos = { ...a.slot }
        }
        if (before) {
          const dx = a.pos.x - before.x
          const dy = a.pos.y - before.y
          if (Math.hypot(dx, dy) > 0.004) {
            a.dir = Math.abs(dx) > Math.abs(dy) * 1.2 ? (dx < 0 ? 'left' : 'right') : (dy < 0 ? 'up' : 'down')
            a.movedAt = now
          }
        }
        if (now - a.movedAt > 500) a.dir = 'down'
      })

      // building names on little signboards just below each building
      const fs = Math.max(8, Math.min(11, tile * 0.56))
      ctx.font = `500 ${fs}px Inter, system-ui, sans-serif`
      ctx.textBaseline = 'middle'
      ctx.textAlign = 'center'
      S.map.places.forEach((p) => {
        const closed = isClosed(p)
        const label = SHORT[p.id] || p.name
        const text = closed ? `${label} · closed` : label
        const tw = ctx.measureText(text).width
        const pw = tw + 10
        const ph = fs + 4
        let cx = ox + (p.rect.x + p.rect.w / 2) * tile
        const south = p.door.y > p.rect.y
        const doorX = ox + (p.door.x + 0.5) * tile
        if (south && Math.abs(doorX - cx) < pw / 2 + 6) cx = doorX + (cx <= doorX ? -1 : 1) * (pw / 2 + 12)
        const top = oy + (p.rect.y + p.rect.h) * tile + 1
        ctx.fillStyle = '#FBF6E6'
        ctx.strokeStyle = '#2B2330'
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.roundRect(cx - pw / 2, top, pw, ph, 3)
        ctx.fill()
        ctx.stroke()
        ctx.fillStyle = closed ? '#B5483A' : '#2B2330'
        ctx.fillText(text, cx, top + ph / 2 + 0.5)
      })

      // people, back to front
      const sel = selectedRef.current
      const hov = hoverRef.current
      list.sort((p, q) => (p.pos?.y || 0) - (q.pos?.y || 0)).forEach((a) => {
        if (!a.pos || !a.look) return
        const fx = ox + a.pos.x * tile
        const fy = oy + (a.pos.y * T + 5) * scale
        const walking = now - a.movedAt < 160
        const frame = walking ? Math.floor(now / 130) % 4 : 0
        const status = a.status || 'ok'
        ctx.beginPath()
        ctx.ellipse(fx, fy - scale, 5.5 * scale, 2.4 * scale, 0, 0, Math.PI * 2)
        if (status === 'ok') {
          ctx.fillStyle = 'rgba(20, 40, 20, 0.26)'
          ctx.fill()
        } else {
          ctx.fillStyle = `${STATUS_COLOR[status]}55`
          ctx.fill()
          ctx.lineWidth = Math.max(1, 1.2 * scale)
          ctx.strokeStyle = STATUS_COLOR[status]
          ctx.stroke()
        }
        ctx.drawImage(spriteFrame(a.look, a.dir, frame), fx - (SPRITE_W / 2) * scale, fy - (SPRITE_H - 1) * scale, SPRITE_W * scale, SPRITE_H * scale)
      })

      // time of day: the whole town is tinted, easing between phases
      const target = TINT[S.phase] || TINT.afternoon
      const cur = tintRef.current
      for (let i = 0; i < 3; i++) cur[i] += (target[i] - cur[i]) * 0.05
      if (cur.some((v) => v < 251)) {
        ctx.save()
        ctx.globalCompositeOperation = 'multiply'
        ctx.fillStyle = `rgb(${cur.map(Math.round).join(',')})`
        ctx.fillRect(ox, oy, NW * scale, NH * scale)
        ctx.restore()
      }

      // who is selected / hovered
      ;[hov && hov !== sel ? hov : null, sel].forEach((id) => {
        const a = id && S.agents[id]
        if (!a || !a.pos) return
        const fx = ox + a.pos.x * tile
        const fy = oy + (a.pos.y * T + 5) * scale
        if (id === sel) {
          const bob = Math.sin(now / 160) * 1.5 * scale
          const ay = fy - (SPRITE_H + 4) * scale + bob
          ctx.fillStyle = '#FFFFFF'
          ctx.strokeStyle = '#2B2330'
          ctx.lineWidth = Math.max(1.2, scale)
          ctx.beginPath()
          ctx.moveTo(fx - 4 * scale, ay)
          ctx.lineTo(fx + 4 * scale, ay)
          ctx.lineTo(fx, ay + 5 * scale)
          ctx.closePath()
          ctx.fill()
          ctx.stroke()
        }
        const nm = firstName(a.name)
        const w = ctx.measureText(nm).width + 10
        ctx.fillStyle = '#2B2330'
        ctx.beginPath()
        ctx.roundRect(fx - w / 2, fy + 3 * scale, w, fs + 4, 3)
        ctx.fill()
        ctx.fillStyle = '#FFFFFF'
        ctx.fillText(nm, fx, fy + 3 * scale + (fs + 4) / 2 + 0.5)
      })
      ctx.textAlign = 'start'

      // keep speech/thought bubbles pinned above their agents
      const placed = []
      wrap.querySelectorAll('[data-agent]').forEach((el) => {
        const a = S.agents[el.dataset.agent]
        if (!a || !a.pos) return
        const bw = el.offsetWidth
        const bh = el.offsetHeight
        const left = Math.min(Math.max(ox + a.pos.x * tile - bw / 2, 6), W - bw - 6)   // keep inside the map
        let top = oy + (a.pos.y * T + 5 - SPRITE_H) * scale - 8 - bh
        // don't cover another bubble: stack above it (or below, if there is no room above)
        for (let guard = 0; guard < 4; guard++) {
          const hit = placed.find((p) => left < p.left + p.w && p.left < left + bw && top < p.top + p.h && p.top < top + bh)
          if (!hit) break
          top = hit.top - bh - 6 >= 6 ? hit.top - bh - 6 : hit.top + hit.h + 6
        }
        top = Math.max(6, top)
        placed.push({ left, top, w: bw, h: bh })
        el.style.transform = `translate(${left}px, ${top}px)`
      })
    }
    draw()
    return () => cancelAnimationFrame(raf)
  }, [])

  useEffect(() => {
    sim.current.weekday = clock.weekday
  }, [clock.weekday])

  useEffect(() => {
    sim.current.phase = clock.phase
  }, [clock.phase])

  // nearest person to a mouse position (their body, not their feet)
  const personAt = (e) => {
    const rect = canvasRef.current.getBoundingClientRect()
    const { tile, ox, oy } = scaleRef.current
    const x = (e.clientX - rect.left - ox) / tile
    const y = (e.clientY - rect.top - oy) / tile
    let best = null
    let bestD = 1.0
    Object.values(sim.current.agents).forEach((a) => {
      if (!a.pos) return
      const d = Math.hypot(a.pos.x - x, a.pos.y - 0.25 - y)
      if (d < bestD) {
        best = a.id
        bestD = d
      }
    })
    return best
  }
  const onCanvasClick = (e) => setSelected(personAt(e))
  const onCanvasMove = (e) => {
    const id = personAt(e)
    hoverRef.current = id
    canvasRef.current.style.cursor = id ? 'pointer' : 'default'
  }

  const stop = async () => {
    try {
      await stopTownRun(runId)
    } catch (e) {
      setError(e.message)
    }
  }

  const agents = sim.current.agents
  const sel = selected ? agents[selected] : null
  const done = Boolean(finished)
  const reportsReady = done && runInfo && runInfo.status !== 'running'
  const storiesNote = runInfo?.stories === 'writing' ? 'Writing each agent’s story for the reports…' : ''
  const phaseText = clock.phase === 'planning'
    ? `Agents are planning their day · ${clock.planning || 0} of ${Object.keys(agents).length}`
    : clock.phase === 'night' ? 'Night · bills and the day’s books'
      : clock.phase === 'done' ? 'Run complete' : PHASE_LABEL[clock.phase] || ''

  return (
    <div className="town">
      <div className="town-bar">
        <button type="button" className="town-btn town-btn--ghost" onClick={onExit}>← Runs</button>
        <div className="town-bar__title" title={meta?.title}>{meta?.title || 'Loading run…'}</div>
        <span className={`town-pill town-pill--${conn}`}>
          <i />
          {conn === 'live' ? 'Live' : conn === 'replay' ? 'Replay' : conn === 'ended' ? (finished?.stopped ? 'Stopped' : 'Finished') : conn === 'error' ? 'Error' : 'Connecting'}
        </span>
        {clock.day > 0 && (
          <span className="town-bar__clock">
            Day <b>{clock.day}</b> of {meta?.days} · {clock.weekday} · {phaseText}
          </span>
        )}
        <div className="town-bar__spacer" />
        <div className="town-seg" role="group" aria-label="Playback speed">
          {[1, 2, 4].map((s) => (
            <button type="button" key={s} className={speed === s ? 'is-on' : ''} onClick={() => setSpeed(s)}>{s}×</button>
          ))}
        </div>
        {conn === 'replay' && !done && (
          <button type="button" className="town-btn town-btn--ghost" onClick={() => { skipRef.current = true }}>Skip to end</button>
        )}
        {done && conn === 'ended' && !endOpen && (
          <button type="button" className="town-btn town-btn--ghost" onClick={() => setEndOpen(true)}>Results</button>
        )}
        {conn === 'live' && !done && runInfo?.status === 'running' && (
          <button type="button" className="town-btn town-btn--ghost" onClick={stop}>Stop run</button>
        )}
        <a className={`town-btn ${reportsReady ? 'town-btn--ink' : 'is-disabled'}`} href={reportsReady ? reportUrl(runId, 'summary') : undefined}>Summary PDF</a>
        <a className={`town-btn ${reportsReady ? 'town-btn--ghost' : 'is-disabled town-btn--ghost'}`} href={reportsReady ? reportUrl(runId, 'agents') : undefined}>Agent report PDF</a>
      </div>

      <div className="town-body">
        <div className="town-map" ref={wrapRef}>
          <canvas ref={canvasRef} onClick={onCanvasClick} onMouseMove={onCanvasMove} onMouseLeave={() => { hoverRef.current = null }} />
          {bubbles.map((b) => (
            <div key={b.id} className={`town-bubble town-bubble--${b.kind}`} data-agent={b.agentId}
              style={{ transform: 'translate(-9999px, 0)' }}>
              <span className="town-bubble__who">{firstName(name(b.agentId))}</span>
              {b.text}
            </div>
          ))}
          {banner && (
            <div className="town-banner" key={banner.day}>
              <div className="town-banner__day">Day {banner.day} · {banner.weekday}</div>
              {(banner.news || []).map((n) => <div className="town-banner__news" key={n}>{n}</div>)}
            </div>
          )}
          {error && <div className="town-error" role="alert">{error}</div>}
          {done && conn === 'ended' && endOpen && (
            <EndCard town={town} counts={counts} finished={finished} runId={runId} ready={reportsReady} note={storiesNote} onClose={() => setEndOpen(false)} />
          )}
        </div>

        <aside className="town-side">
          {sel ? (
            <Inspector a={sel} placeName={sim.current.placeName} onClose={() => setSelected(null)} version={version} />
          ) : (
            <Feed feed={feed} name={name} onPick={setSelected} meta={meta} />
          )}
        </aside>
      </div>

      <StatStrip prices={prices} town={town} counts={counts} total={Object.keys(agents).length} agents={agents} version={version} />
    </div>
  )
}

/* ── side panel: the feed ─────────────────────────────────────────────── */
function Feed({ feed, name, onPick, meta }) {
  const [filter, setFilter] = useState('all')
  const items = feed.filter((f) => filter === 'all' || (filter === 'thoughts' && f.type === 'thought')
    || (filter === 'talk' && f.type === 'talk') || (filter === 'events' && ['problem', 'event', 'reflection', 'day'].includes(f.type)))
  const Who = ({ id }) => <button type="button" className="town-who" onClick={() => onPick(id)}>{name(id)}</button>
  return (
    <div className="town-feed">
      <div className="town-side__head">
        <span className="town-side__h">What’s happening</span>
        <div className="town-seg town-seg--small">
          {[['all', 'All'], ['thoughts', 'Thoughts'], ['talk', 'Talk'], ['events', 'Events']].map(([k, l]) => (
            <button type="button" key={k} className={filter === k ? 'is-on' : ''} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
      </div>
      {meta && feed.length < 3 && (
        <p className="town-hint">Each person here is an LLM agent with their own money, bills, memories and goals. Click anyone on the map to see what they know and why they act.</p>
      )}
      <ol className="town-feed__list">
        {items.map((f) => (
          <li key={f.key} className={`town-item town-item--${f.type}`}>
            {f.type === 'day' && (
              <>
                <div className="town-item__day">Day {f.day} · {f.weekday}</div>
                {(f.news || []).map((n) => <div key={n} className="town-item__news">News: {n}</div>)}
              </>
            )}
            {f.type === 'thought' && (
              <>
                <div className="town-item__meta"><Who id={f.agent} /> <span className={`town-tag town-tag--${f.mode}`}>{f.mode === 'llm' ? 'LLM' : f.mode}</span>
                  {f.learned > 0 && <span className="town-tag town-tag--learned" title="This plan drew on lessons from earlier months">remembers</span>}</div>
                <div className="town-item__quote">“{f.text}”</div>
              </>
            )}
            {f.type === 'talk' && (
              <>
                <div className="town-item__meta"><Who id={f.a} /> &amp; <Who id={f.b} /> <span className="town-item__where">at {f.place}</span></div>
                {f.lines.slice(0, 4).map((l, i) => (
                  <div key={i} className="town-item__line"><b>{firstName(name(l.speaker))}:</b> {l.text}</div>
                ))}
              </>
            )}
            {(f.type === 'problem' || f.type === 'event') && (
              <div className="town-item__meta"><Who id={f.agent} /> <span className={f.type === 'problem' ? 'town-item__bad' : ''}>{f.text}</span></div>
            )}
            {f.type === 'reflection' && (
              <>
                <div className="town-item__meta"><Who id={f.agent} /> <span className="town-tag">reflects</span></div>
                {f.insights.map((s, i) => <div key={i} className="town-item__quote">{s}</div>)}
              </>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

/* ── side panel: one agent ────────────────────────────────────────────── */
function Inspector({ a, placeName, onClose }) {
  const s = a.snap || a.profile
  const status = a.status || 'ok'
  const plan = a.plan
  const label = { ok: 'Coping', strain: 'Under strain', crisis: 'In crisis' }[status]
  const debt = a.snap ? a.snap.debt : (a.profile.loans || []).reduce((t, l) => t + (l.outstanding || 0), 0)
  return (
    <div className="town-insp">
      <div className="town-side__head">
        <span className="town-side__h">Agent</span>
        <button type="button" className="town-btn town-btn--ghost town-btn--sm" onClick={onClose}>Back to feed</button>
      </div>
      <div className="town-insp__name">{a.name}</div>
      <div className="town-insp__sub">{a.profile.age} · {a.profile.job_title}</div>
      <div className="town-insp__sub">
        {a.profile.household_size === 1 ? 'Lives alone' : `Household of ${a.profile.household_size}`}
        {a.profile.children ? ` · ${a.profile.children} child${a.profile.children > 1 ? 'ren' : ''} in school` : ''}
        {' · '}{placeName[a.profile.home]}
      </div>
      <span className={`town-status town-status--${status}`}>{label}</span>

      <dl className="town-insp__nums">
        <div><dt>Cash</dt><dd>{rs(s.money)}</dd></div>
        <div><dt>Food at home</dt><dd>{(s.pantry_days ?? 0).toFixed(1)} days</dd></div>
        <div><dt>Debt</dt><dd>{rs(debt)}</dd></div>
        <div><dt>Credit score</dt><dd>{s.credit_score}</dd></div>
        {a.profile.vehicle && a.profile.vehicle !== 'none' && <div><dt>Fuel</dt><dd>{(s.fuel_days ?? 0).toFixed(1)} days</dd></div>}
        {s.khata_due > 0 && <div><dt>Shop credit</dt><dd>{rs(s.khata_due)}</dd></div>}
      </dl>

      {a.reward && (
        <div className="town-insp__reward">
          <span>Today's reward</span>
          <b className={a.reward.total < -0.3 ? 'is-bad' : a.reward.total > 0.1 ? 'is-good' : ''}>{a.reward.total > 0 ? '+' : ''}{a.reward.total.toFixed(1)}</b>
          <em>{Object.entries(a.reward.parts || {}).map(([k, v]) => `${k} ${v > 0 ? '+' : ''}${v.toFixed(1)}`).join(' · ') || 'an ordinary day'}</em>
        </div>
      )}
      {a.thought && (
        <>
          <div className="town-insp__h">Thinking <span className={`town-tag town-tag--${a.mode}`}>{a.mode === 'llm' ? 'LLM' : a.mode}</span></div>
          <p className="town-insp__thought">“{a.thought}”</p>
        </>
      )}
      {plan && (
        <>
          <div className="town-insp__h">Plan for today</div>
          <ol className="town-insp__plan">
            {['morning', 'afternoon', 'evening'].map((ph) => plan[ph] && (
              <li key={ph}><span>{PHASE_LABEL[ph]}</span>{placeName[plan[ph].place] || plan[ph].place} · {plan[ph].do}{plan[ph].spend ? ` · ${rs(plan[ph].spend)}` : ''}</li>
            ))}
          </ol>
        </>
      )}
      {a.learned?.length > 0 && (
        <>
          <div className="town-insp__h">Drawing on past experience</div>
          <ul className="town-insp__goals">{a.learned.map((t, i) => <li key={i}>{t}</li>)}</ul>
        </>
      )}
      {a.lessons?.length > 0 && (
        <>
          <div className="town-insp__h">Learned this month</div>
          <ul className="town-insp__goals">{a.lessons.map((l, i) => <li key={i}>{l.text}</li>)}</ul>
        </>
      )}
      <div className="town-insp__h">Goals</div>
      <ul className="town-insp__goals">{(a.profile.goals || []).map((g) => <li key={g}>{g}</li>)}</ul>
      <div className="town-insp__h">Recent memory</div>
      <ol className="town-insp__log">
        {a.log.slice(0, 14).map((l, i) => (
          <li key={i} className={`town-log town-log--${l.type}`}><span>Day {l.day}</span>{l.text}</li>
        ))}
        {a.log.length === 0 && <li className="town-log"><span /> Nothing yet.</li>}
      </ol>
    </div>
  )
}

/* ── bottom strip ─────────────────────────────────────────────────────── */
function StatStrip({ prices, town, counts, total, agents }) {
  const tally = useMemo(() => {
    const t = { ok: 0, strain: 0, crisis: 0 }
    Object.values(agents).forEach((a) => (t[a.status || 'ok'] += 1))
    return t
  }, [agents, town]) // eslint-disable-line react-hooks/exhaustive-deps
  const idx = (v) => (v ? `×${v.toFixed(2)}` : '—')
  return (
    <div className="town-strip">
      <Stat k="Groceries" v={idx(prices?.groceries)} warn={prices?.groceries > 1.05} />
      <Stat k="Petrol" v={prices ? `₹${Math.round(prices.fuel_price)}/L` : '—'} warn={prices?.fuel > 1.05} />
      <Stat k="Eating out" v={idx(prices?.eating_out)} />
      <span className="town-strip__sep" />
      <Stat k="Coping" v={total ? tally.ok : '—'} dot="ok" />
      <Stat k="Under strain" v={total ? tally.strain : '—'} dot="strain" />
      <Stat k="In crisis" v={total ? tally.crisis : '—'} dot="crisis" />
      <span className="town-strip__sep" />
      <Stat k="Low on food" v={town ? town.low_food : '—'} />
      <Stat k="Moneylender" v={town ? town.moneylender_borrowers : '—'} />
      <Stat k="Defaults" v={town ? town.defaulted : '—'} />
      <Stat k="Without work" v={town ? town.unemployed : '—'} />
      <span className="town-strip__sep" />
      <Stat k="LLM plans" v={counts.llm} />
      <Stat k="Routine days" v={counts.routine} />
      <Stat k="Conversations" v={counts.talks} />
    </div>
  )
}

function Stat({ k, v, warn, dot }) {
  return (
    <span className="town-stat">
      {dot && <i className={`town-dot town-dot--${dot}`} />}
      <span className="town-stat__k">{k}</span>
      <b className={warn ? 'is-warn' : ''}>{v}</b>
    </span>
  )
}

function EndCard({ town, counts, finished, runId, ready, note, onClose }) {
  return (
    <div className="town-end">
      <button type="button" className="town-end__x" onClick={onClose} aria-label="Close">
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      </button>
      <div className="town-end__eyebrow">{finished?.stopped ? 'Run stopped' : 'Run complete'}</div>
      <div className="town-end__title">{finished?.stopped ? 'The run was stopped early.' : 'The month is over. Here’s the record.'}</div>
      {town && (
        <div className="town-end__nums">
          <div><b>{town.moneylender_borrowers}</b><span>borrowing from the moneylender</span></div>
          <div><b>{town.defaulted}</b><span>defaulted</span></div>
          <div><b>{town.unemployed}</b><span>without work</span></div>
          <div><b>{counts.llm}</b><span>plans written by the LLM</span></div>
        </div>
      )}
      <div className="town-end__actions">
        <a className={`town-btn ${ready ? 'town-btn--ink' : 'is-disabled'}`} href={ready ? reportUrl(runId, 'summary') : undefined}>Download summary (PDF)</a>
        <a className={`town-btn town-btn--ghost ${ready ? '' : 'is-disabled'}`} href={ready ? reportUrl(runId, 'agents') : undefined}>Download agent report (PDF)</a>
      </div>
      {finished?.learning && finished.learning.mode !== 'off' && (
        <p className="town-end__learn">
          <b>{finished.learning.mode === 'learn' ? `${finished.learning.lessons_new || 0} new lessons learned.` : 'Used earlier lessons; remembered nothing new.'}</b>
          {' '}Average reward per resident-day {finished.learning.mean_reward >= 0 ? '+' : ''}{finished.learning.mean_reward}
          {finished.learning.previous_mean_reward !== undefined ? ` (earlier runs: ${finished.learning.previous_mean_reward >= 0 ? '+' : ''}${finished.learning.previous_mean_reward})` : ''}.
          See each person's lessons under Agent profiles.
        </p>
      )}
      {note && <p className="town-end__note">{note}</p>}
    </div>
  )
}
