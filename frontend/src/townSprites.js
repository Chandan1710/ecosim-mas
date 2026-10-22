/**
 * townSprites.js — pixel-art people for the town, drawn in code (no image files).
 *
 * Every agent gets a small 4-direction, 4-frame walking sprite (18 x 24 px, like the
 * classic top-down RPG look). What they wear comes from their job; hair, skin and
 * colours come from their id, so the same person always looks the same.
 *
 *   appearanceFor(agent)            -> a plain object describing the look
 *   spriteFrame(look, dir, frame)   -> a cached <canvas>; dir: down|up|left|right, frame 0..3
 *
 * Frames: 0 standing, 1 left foot forward, 2 standing, 3 right foot forward.
 */

export const SPRITE_W = 18
export const SPRITE_H = 24

const OUTLINE = '#2B2330'
const SKINS = ['#F2CBA2', '#E2AC7F', '#CB8F61', '#AC7146', '#84532F']
const HAIRS = ['#1C1818', '#2A1D18', '#3C281C', '#51351F', '#1C1818', '#2A1D18']
const GREY = '#BDBDBD'

function hash(str) {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

const pickFrom = (arr, h, salt) => arr[Math.floor(((h >>> salt) % 997) / 997 * arr.length)]

// what each job wears: [top colours], bottom, hat, detail
const OUTFITS = {
  software_engineer: { top: ['#3E7CB1', '#4F8A8B', '#5C6BC0'], bottom: '#2F3A4F', detail: 'lanyard' },
  support_associate: { top: ['#8E6BBF', '#C75D8A', '#3FA7A0'], bottom: '#38405A', detail: 'lanyard' },
  garment_tailor: { top: ['#D98C3D', '#7FB069', '#C9B94E'], bottom: '#5A4A3F', detail: 'tape' },
  construction_labourer: { top: ['#E8863A'], sleeve: '#7C8794', bottom: '#4A5560', hat: ['#F2C230', 'helmet'], detail: 'vest' },
  auto_driver: { top: ['#B7A66A'], bottom: '#9C8B55', hat: ['#B7A66A', 'cap'] },
  delivery_rider: { top: ['#E0533D'], bottom: '#2F3340', hat: ['#E0533D', 'cap'] },
  kirana_owner: { top: ['#F2EEDD'], bottom: '#8C7B62', detail: 'apron', apron: '#B07A42' },
  cafe_owner: { top: ['#F4F1E8'], bottom: '#3B3B3B', detail: 'apron', apron: '#2F7D5B' },
  vegetable_vendor: { top: ['#6FA05B', '#C98A3E'], bottom: '#7A6A52', hat: ['#F4F1E8', 'topi'] },
  teacher: { top: ['#3B6EA5', '#8A5A9E', '#2F7D74'], bottom: '#2E3345', saree: ['#9B3D5A', '#2F7D74', '#B8862F'] },
  nurse: { top: ['#EAF4F4'], bottom: '#7DB8C4', hat: ['#FFFFFF', 'nursecap'] },
  bank_clerk: { top: ['#F3F3F3'], bottom: '#4A5163', detail: 'tie' },
  security_guard: { top: ['#34415A'], bottom: '#2A3347', hat: ['#34415A', 'cap'] },
  domestic_worker: { top: ['#7A8F4F'], bottom: '#4B4B55', saree: ['#6F7FB0', '#A0522D', '#5E8C61'] },
  retired_clerk: { top: ['#EFE6D2'], bottom: '#E9E1CE', glasses: true, grey: true },
  college_student: { top: ['#E4572E', '#29B6A8', '#F2A93B', '#6C8EE6'], bottom: '#3D4B73', detail: 'bag' },
}

export function appearanceFor(agent) {
  const h = hash(agent.id || agent.name || 'x')
  const female = agent.gender === 'female'
  const job = OUTFITS[agent.job_key] || OUTFITS.college_student
  const old = (agent.age || 30) >= 58
  const mid = (agent.age || 30) >= 40
  const look = {
    key: '',
    skin: pickFrom(SKINS.slice(1), h, 3),
    hair: old || job.grey ? GREY : pickFrom(HAIRS, h, 7),
    top: pickFrom(job.top, h, 11),
    sleeve: job.sleeve || null,
    bottom: job.bottom,
    shoes: '#2B2330',
    female,
    hairStyle: female ? (mid ? 'bun' : 'long') : (old ? 'bald' : 'short'),
    hat: job.hat || null,
    detail: job.detail || null,
    apron: job.apron || null,
    glasses: Boolean(job.glasses) || (h % 9 === 0),
    moustache: !female && (h % 4 === 0) && (agent.age || 30) > 30,
    saree: female && job.saree ? pickFrom(job.saree, h, 5) : null,
    sareeEdge: '#F2C230',
  }
  if (look.hat && look.hat[1] === 'helmet') look.hairStyle = 'short'
  if (look.hat && look.hat[1] === 'nursecap') look.hairStyle = 'bun'
  look.key = JSON.stringify(look)
  return look
}

/* ── pixel painting ───────────────────────────────────────────────────── */

const make = (w, h) => {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  return c
}

const shade = (hex, k) => {
  const n = parseInt(hex.slice(1), 16)
  const f = (v) => Math.max(0, Math.min(255, Math.round(v * k)))
  return `#${[f((n >> 16) & 255), f((n >> 8) & 255), f(n & 255)].map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

function paint(ctx, look, dir, frame) {
  const P = (c, x, y, w = 1, h = 1) => {
    ctx.fillStyle = c
    ctx.fillRect(x, y, w, h)
  }
  const step = frame === 1 ? 1 : frame === 3 ? 2 : 0 // which foot is forward
  const skinD = shade(look.skin, 0.8)
  const topD = shade(look.top, 0.82)
  const sleeve = look.sleeve || look.top
  const side = dir === 'left'
  const back = dir === 'up'
  const L = look.saree
  const bodyCol = L || look.top

  /* legs / skirt */
  if (side) {
    const front = step === 1 ? 4 : step === 3 ? 7 : 6
    const rear = step === 1 ? 9 : step === 3 ? 7 : 8
    if (!L) {
      P(look.bottom, rear, 16, 2, 4)
      P(shade(look.bottom, 0.8), rear, 16, 1, 4)
      P(look.shoes, rear, 20, 3, 2)
      P(look.bottom, front, 16, 2, 4)
      P(look.shoes, front - 1, 20, 3, 2)
    } else {
      P(bodyCol, 5, 15, 6, 6)
      P(look.sareeEdge, 5, 20, 6, 1)
      P(look.shoes, rear, 21, 2, 1)
      P(look.shoes, front - 1, 21, 3, 1)
    }
  } else if (!L) {
    const lUp = step === 1 ? 1 : 0
    const rUp = step === 3 ? 1 : 0
    P(look.bottom, 4, 16, 8, 1)
    P(look.bottom, 4, 17 - lUp, 3, 3)
    P(look.bottom, 9, 17 - rUp, 3, 3)
    P(look.shoes, 4, 20 - lUp, 3, 2)
    P(look.shoes, 9, 20 - rUp, 3, 2)
  } else {
    P(bodyCol, 4, 15, 8, 6)
    P(shade(bodyCol, 0.85), 4, 15, 1, 6)
    P(look.sareeEdge, 4, 20, 8, 1)
    P(look.shoes, 5, 21, 2, 1)
    P(look.shoes, 9, 21, 2, 1)
  }

  /* torso and arms */
  if (side) {
    P(bodyCol, 5, 10, 6, 6)
    P(topD, 5, 15, 6, 1)
    const armX = step === 1 ? 5 : step === 3 ? 9 : 7
    P(sleeve, armX, 10, 2, 4)
    P(shade(sleeve, 0.8), armX, 10, 1, 4)
    P(look.skin, armX, 14, 2, 1)
    if (L) P(look.sareeEdge, 10, 10, 1, 8)
  } else {
    P(bodyCol, 4, 10, 8, 6)
    P(topD, 4, 15, 8, 1)
    if (L) {
      P(look.sareeEdge, 4, 10, 2, 6) // pallu over one shoulder
      P(shade(L, 0.8), 6, 12, 1, 4)
    }
    const aL = step === 3 ? 1 : 0
    const aR = step === 1 ? 1 : 0
    P(sleeve, 3, 10 + aL, 1, 4)
    P(sleeve, 12, 10 + aR, 1, 4)
    P(look.skin, 3, 14 + aL, 1, 1)
    P(look.skin, 12, 14 + aR, 1, 1)
  }

  /* detail on the torso */
  if (!back && !side) {
    if (look.detail === 'lanyard') {
      P('#E9F3F8', 7, 10, 1, 4)
      P('#F2C230', 7, 13, 2, 2)
    }
    if (look.detail === 'tie') {
      P('#D4C9C0', 5, 10, 6, 1)
      P('#B73A3A', 7, 10, 2, 5)
    }
    if (look.detail === 'tape') {
      P('#F2C230', 5, 10, 1, 4)
      P('#F2C230', 10, 10, 1, 4)
    }
    if (look.detail === 'vest') {
      P('#F4F1E8', 4, 12, 8, 1)
      P('#F4F1E8', 4, 14, 8, 1)
    }
    if (look.detail === 'apron' && look.apron) {
      P(look.apron, 5, 11, 6, 6)
      P(shade(look.apron, 0.8), 5, 11, 6, 1)
    }
  }
  if (look.detail === 'bag' && !side) {
    if (back) P('#374A6E', 5, 10, 6, 6)
    else {
      P('#374A6E', 4, 10, 1, 4)
      P('#374A6E', 11, 10, 1, 4)
    }
  }
  if (look.detail === 'bag' && side) P('#374A6E', 9, 10, 2, 5)
  if (look.detail === 'vest' && side) P('#F4F1E8', 5, 12, 6, 1)
  if (look.detail === 'apron' && side && look.apron) P(look.apron, 5, 12, 3, 5)

  /* head */
  const hx = side ? 4 : 4
  const hw = side ? 7 : 8
  P(look.skin, hx, 3, hw, 7)
  P(skinD, 7, 10, 2, 1) // neck
  if (!back && !side) {
    P(OUTLINE, 6, 6, 1, 2)
    P(OUTLINE, 9, 6, 1, 2)
    P(skinD, 7, 9, 2, 1)
    if (look.moustache) P(shade(look.hair, 0.9), 6, 8, 4, 1)
    if (look.glasses) {
      P('#3A3A44', 5, 6, 3, 1)
      P('#3A3A44', 8, 6, 3, 1)
      P('#3A3A44', 5, 7, 1, 1)
      P('#3A3A44', 10, 7, 1, 1)
    }
  }
  if (side) {
    P(OUTLINE, 5, 6, 1, 2)
    P(look.skin, 3, 7, 1, 2) // nose
    P(skinD, 3, 8, 1, 1)
    if (look.moustache) P(shade(look.hair, 0.9), 4, 8, 2, 1)
    if (look.glasses) {
      P('#3A3A44', 4, 6, 3, 1)
      P('#3A3A44', 3, 6, 1, 1)
    }
  }

  /* hair */
  const hair = look.hair
  const hairD = shade(hair, 0.8)
  const style = look.hairStyle
  if (back) {
    if (style !== 'bald') {
      P(hair, 4, 1, 8, style === 'long' ? 11 : 8)
      P(hairD, 4, 1, 8, 1)
    } else {
      P(hair, 4, 1, 8, 3)
      P(hair, 4, 4, 1, 3)
      P(hair, 11, 4, 1, 3)
      P(look.skin, 5, 4, 6, 4)
    }
    if (style === 'bun') P(hair, 6, 0, 4, 2)
  } else if (side) {
    if (style === 'bald') {
      P(hair, 4, 1, 7, 2)
      P(hair, 8, 3, 3, 3)
    } else {
      P(hair, 4, 1, 7, 3)
      P(hair, 8, 3, 3, style === 'long' ? 9 : 5)
      P(hair, 4, 3, 1, 1)
      P(hairD, 4, 1, 7, 1)
    }
    if (style === 'bun') P(hair, 8, 0, 3, 2)
  } else {
    if (style === 'bald') {
      P(hair, 4, 1, 8, 2)
      P(hair, 4, 3, 1, 3)
      P(hair, 11, 3, 1, 3)
      P(look.skin, 5, 1, 6, 1)
    } else {
      P(hair, 4, 1, 8, 3)
      P(hair, 4, 4, 2, 2)
      P(hair, 10, 4, 2, 2)
      P(hairD, 4, 1, 8, 1)
      if (style === 'long') {
        P(hair, 4, 6, 1, 6)
        P(hair, 11, 6, 1, 6)
      }
    }
    if (style === 'bun') P(hair, 6, 0, 4, 2)
  }

  /* hats */
  if (look.hat) {
    const [col, kind] = look.hat
    const colD = shade(col, 0.8)
    if (kind === 'cap' || kind === 'helmet') {
      const top = kind === 'helmet' ? 0 : 1
      P(col, 4, top, 8, 4 - top)
      P(colD, 4, 3, 8, 1)
      if (dir === 'down') P(colD, 3, 4, 10, 1)
      if (dir === 'left') P(colD, 2, 4, 5, 1)
      if (kind === 'helmet') P('#FFFFFF', 7, 1, 2, 1)
    }
    if (kind === 'topi') {
      P(col, 5, 1, 6, 3)
      P(colD, 5, 3, 6, 1)
    }
    if (kind === 'nursecap') {
      P(col, 5, 0, 6, 3)
      if (dir === 'down') {
        P('#D44A4A', 7, 1, 2, 1)
      }
    }
  }
}

const cache = new Map()

/** One frame of a person, as a canvas with a dark 1px outline. dir: down | up | left | right. */
export function spriteFrame(look, dir, frame) {
  const key = `${look.key}|${dir}|${frame}`
  if (cache.has(key)) return cache.get(key)
  let out
  if (dir === 'right') {
    const l = spriteFrame(look, 'left', frame)
    out = make(SPRITE_W, SPRITE_H)
    const c = out.getContext('2d')
    c.translate(SPRITE_W, 0)
    c.scale(-1, 1)
    c.drawImage(l, 0, 0)
  } else {
    const raw = make(SPRITE_W, SPRITE_H)
    const rc = raw.getContext('2d')
    rc.translate(1, 1)
    paint(rc, look, dir, frame)

    // silhouette in the outline colour, stamped to the 4 sides, with the person on top
    const sil = make(SPRITE_W, SPRITE_H)
    const sc = sil.getContext('2d')
    sc.drawImage(raw, 0, 0)
    sc.globalCompositeOperation = 'source-in'
    sc.fillStyle = OUTLINE
    sc.fillRect(0, 0, SPRITE_W, SPRITE_H)

    out = make(SPRITE_W, SPRITE_H)
    const oc = out.getContext('2d')
    ;[[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => oc.drawImage(sil, dx, dy))
    oc.drawImage(raw, 0, 0)
  }
  cache.set(key, out)
  return out
}
