/**
 * townScene.js — the town as pixel-art tiles, drawn once in code (no image files).
 *
 * buildScene(map) paints the whole 64 x 40 tile town onto one offscreen canvas at 16 px per
 * tile: grass and flowers, sand roads, a lake, trees, and every building as a cutaway
 * (walls on top, furniture inside) so you can watch people move around in it.
 * TownView then scales that canvas to the screen and draws the people on top.
 */

import { isOutdoor } from './townGeometry'

export const T = 16

/* ── tiny helpers ─────────────────────────────────────────────────────── */

function rng32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const strSeed = (s) => {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619)
  return h >>> 0
}

const shade = (hex, k) => {
  const n = parseInt(hex.slice(1), 16)
  const f = (v) => Math.max(0, Math.min(255, Math.round(v * k)))
  return `#${[f((n >> 16) & 255), f((n >> 8) & 255), f(n & 255)].map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

const INK = '#2B2330'
const WOOD = '#B07A42'
const WOOD_D = '#8A5A2E'
const WOOD_L = '#CF9A5B'

/* ── floors ───────────────────────────────────────────────────────────── */

function speckle(g, x, y, w, h, color, n, r) {
  g.fillStyle = color
  for (let i = 0; i < n; i++) g.fillRect(x + Math.floor(r() * w), y + Math.floor(r() * h), 1, 1)
}

function floor(g, x, y, w, h, kind, r) {
  const R = (c, a, b, cw, ch) => {
    g.fillStyle = c
    g.fillRect(a, b, cw, ch)
  }
  switch (kind) {
    case 'wood':
    case 'wood2': {
      const a = kind === 'wood' ? '#C99A62' : '#D4A86F'
      const b = kind === 'wood' ? '#C0915A' : '#CB9F66'
      for (let j = 0; j < h; j += 4) {
        R(((j / 4) | 0) % 2 ? a : b, x, y + j, w, 4)
        R(shade(a, 0.88), x, y + j + 3, w, 1)
        for (let i = ((j / 4) | 0) % 2 ? 5 : 11; i < w; i += 16) R(shade(a, 0.86), x + i, y + j, 1, 3)
      }
      break
    }
    case 'tile':
    case 'tileW': {
      const a = kind === 'tile' ? '#EFE3C8' : '#F3F5F3'
      const b = kind === 'tile' ? '#E4D5B3' : '#E2E7E5'
      for (let j = 0; j < h; j += 8) {
        for (let i = 0; i < w; i += 8) {
          R(((i + j) / 8) % 2 ? a : b, x + i, y + j, 8, 8)
        }
      }
      break
    }
    case 'concrete':
      R('#B6BABF', x, y, w, h)
      speckle(g, x, y, w, h, '#A4A9AF', (w * h) / 22, r)
      speckle(g, x, y, w, h, '#C6CACE', (w * h) / 40, r)
      for (let i = 16; i < w; i += 32) R('#A9AEB4', x + i, y, 1, h)
      break
    case 'carpet':
      R('#7C91B4', x, y, w, h)
      speckle(g, x, y, w, h, '#7288AD', (w * h) / 10, r)
      speckle(g, x, y, w, h, '#8CA0C0', (w * h) / 24, r)
      break
    case 'marble':
      R('#EEEAE2', x, y, w, h)
      for (let j = 0; j < h; j += 16) for (let i = 0; i < w; i += 16) {
        R('#E1DCD1', x + i + 15, y + j, 1, 16)
        R('#E1DCD1', x + i, y + j + 15, 16, 1)
      }
      speckle(g, x, y, w, h, '#DAD4C8', (w * h) / 40, r)
      break
    case 'asphalt':
      R('#6D717A', x, y, w, h)
      speckle(g, x, y, w, h, '#62666F', (w * h) / 14, r)
      speckle(g, x, y, w, h, '#7C808A', (w * h) / 30, r)
      break
    case 'cobble':
      R('#C7BDA5', x, y, w, h)
      for (let j = 0; j < h; j += 6) {
        for (let i = ((j / 6) | 0) % 2 ? 3 : 0; i < w; i += 8) {
          R('#D4CBB5', x + i, y + j, 6, 1)
          R('#B3A98F', x + i + 6, y + j, 1, 5)
          R('#B3A98F', x + i, y + j + 5, 7, 1)
        }
      }
      break
    case 'dirt':
      R('#BC9A6E', x, y, w, h)
      speckle(g, x, y, w, h, '#A98757', (w * h) / 9, r)
      speckle(g, x, y, w, h, '#CDAE84', (w * h) / 20, r)
      break
    default:
      R('#D8CBB0', x, y, w, h)
  }
}

/* ── furniture & props (x, y = pixel position of the tile's top-left) ─── */

const draw = {
  bed(g, x, y, col = '#5B8DD9') {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 1, 1, 14, 31)
    R('#7A5232', 2, 2, 12, 29)
    R('#F4F1EA', 3, 3, 10, 27)
    R('#FFFFFF', 4, 4, 8, 6)
    R('#D9D5E2', 4, 9, 8, 1)
    R(col, 3, 14, 10, 16)
    R(shade(col, 0.82), 3, 14, 10, 2)
    R(shade(col, 0.9), 3, 22, 10, 1)
  },
  wardrobe(g, x, y) {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 1, -7, 14, 23)
    R('#8A5A2E', 2, -6, 12, 21)
    R('#9C6A38', 2, -6, 12, 3)
    R('#7A4E28', 7, -3, 2, 18)
    R('#E3C27A', 6, 5, 1, 2)
    R('#E3C27A', 9, 5, 1, 2)
  },
  table(g, x, y, w = 2, col = WOOD_L) {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x + 1, y + 3, W - 2, 11)
    g.fillStyle = col
    g.fillRect(x + 2, y + 4, W - 4, 8)
    g.fillStyle = shade(col, 0.8)
    g.fillRect(x + 2, y + 11, W - 4, 2)
    g.fillStyle = '#FFFFFF'
    g.fillRect(x + 6, y + 6, 4, 3)
    g.fillStyle = '#D44A4A'
    g.fillRect(x + W - 9, y + 6, 3, 3)
  },
  chair(g, x, y, col = '#B04A3A') {
    g.fillStyle = INK
    g.fillRect(x + 4, y + 3, 8, 10)
    g.fillStyle = col
    g.fillRect(x + 5, y + 4, 6, 4)
    g.fillRect(x + 5, y + 9, 6, 3)
  },
  sofa(g, x, y, w = 2, col = '#B8584A') {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x + 1, y + 1, W - 2, 15)
    g.fillStyle = shade(col, 0.82)
    g.fillRect(x + 2, y + 2, W - 4, 6)
    g.fillStyle = col
    g.fillRect(x + 4, y + 8, W - 8, 6)
    g.fillRect(x + 2, y + 6, 3, 8)
    g.fillRect(x + W - 5, y + 6, 3, 8)
    g.fillStyle = shade(col, 1.15)
    g.fillRect(x + 4, y + 8, W - 8, 1)
  },
  tv(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 1, y + 1, 14, 11)
    g.fillStyle = '#2E4057'
    g.fillRect(x + 2, y + 2, 12, 8)
    g.fillStyle = '#6CC6E8'
    g.fillRect(x + 3, y + 3, 5, 3)
    g.fillStyle = '#8A5A2E'
    g.fillRect(x + 2, y + 12, 12, 3)
    g.fillStyle = INK
    g.fillRect(x + 2, y + 15, 12, 1)
  },
  bookshelf(g, x, y) {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 0, -7, 16, 23)
    R('#7A4E28', 1, -6, 14, 21)
    const cols = ['#D44A4A', '#4A7BD4', '#E8B74A', '#4AA66B', '#9A5FC4']
    for (let r = 0; r < 3; r++) {
      R('#5A3A1E', 1, -1 + r * 6, 14, 1)
      for (let i = 0; i < 6; i++) R(cols[(i + r * 2) % 5], 2 + i * 2, -5 + r * 6, 2, 4)
    }
  },
  fridge(g, x, y) {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 2, -7, 12, 23)
    R('#E9EEF0', 3, -6, 10, 21)
    R('#C9D3D8', 3, 1, 10, 1)
    R('#9AA7AE', 11, -4, 1, 4)
    R('#9AA7AE', 11, 3, 1, 5)
  },
  stove(g, x, y) {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 1, 0, 14, 15)
    R('#8E979E', 2, 1, 12, 13)
    R('#3A3F45', 4, 3, 3, 3)
    R('#3A3F45', 9, 3, 3, 3)
    R('#C9D0D5', 3, 9, 10, 4)
  },
  plant(g, x, y) {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 4, 8, 8, 8)
    R('#C46A3C', 5, 9, 6, 6)
    R('#2F8F4E', 3, 1, 10, 8)
    R('#43B05F', 5, 0, 6, 5)
    R('#2F8F4E', 6, 4, 4, 5)
  },
  rug(g, x, y, w, h, col = '#B8584A') {
    g.fillStyle = shade(col, 0.8)
    g.fillRect(x, y, w * T, h * T)
    g.fillStyle = col
    g.fillRect(x + 2, y + 2, w * T - 4, h * T - 4)
    g.fillStyle = shade(col, 1.25)
    g.fillRect(x + 4, y + 4, w * T - 8, 1)
    g.fillRect(x + 4, y + h * T - 5, w * T - 8, 1)
  },
  shelf(g, x, y, goods = ['#D44A4A', '#E8B74A', '#4AA66B']) {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 0, -7, 16, 23)
    R('#B58A55', 1, -6, 14, 21)
    for (let r = 0; r < 3; r++) {
      R('#8A5A2E', 1, 0 + r * 5 - 1, 14, 1)
      for (let i = 0; i < 4; i++) R(goods[(i + r) % goods.length], 2 + i * 3 + (r % 2), -5 + r * 5, 2, 4)
    }
  },
  counter(g, x, y, w = 2) {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x, y + 1, W, 15)
    g.fillStyle = '#E0B070'
    g.fillRect(x + 1, y + 2, W - 2, 5)
    g.fillStyle = '#8A5A2E'
    g.fillRect(x + 1, y + 7, W - 2, 8)
    g.fillStyle = '#A06B38'
    for (let i = 3; i < W - 3; i += 6) g.fillRect(x + i, y + 9, 4, 4)
    g.fillStyle = INK
    g.fillRect(x + W - 12, y - 4, 9, 7)
    g.fillStyle = '#C9D0D5'
    g.fillRect(x + W - 11, y - 3, 7, 3)
    g.fillStyle = '#4AA66B'
    g.fillRect(x + W - 10, y - 2, 4, 1)
  },
  crate(g, x, y, col = '#E36B2D') {
    g.fillStyle = INK
    g.fillRect(x + 1, y + 3, 14, 12)
    g.fillStyle = '#A97A45'
    g.fillRect(x + 2, y + 4, 12, 10)
    g.fillStyle = col
    g.fillRect(x + 3, y + 3, 10, 5)
    g.fillStyle = shade(col, 1.2)
    g.fillRect(x + 4, y + 3, 2, 2)
    g.fillRect(x + 9, y + 4, 2, 2)
  },
  desk(g, x, y, col = '#C9A66B') {
    g.fillStyle = INK
    g.fillRect(x + 1, y + 4, 14, 11)
    g.fillStyle = col
    g.fillRect(x + 2, y + 8, 12, 6)
    g.fillStyle = '#22262E'
    g.fillRect(x + 4, y + 1, 8, 7)
    g.fillStyle = '#4DA3E0'
    g.fillRect(x + 5, y + 2, 6, 5)
    g.fillStyle = '#E9EEF0'
    g.fillRect(x + 5, y + 10, 6, 2)
  },
  sewing(g, x, y, cloth = '#D4584A') {
    g.fillStyle = INK
    g.fillRect(x + 1, y + 3, 14, 12)
    g.fillStyle = '#A9AEB5'
    g.fillRect(x + 2, y + 4, 12, 10)
    g.fillStyle = '#6E757D'
    g.fillRect(x + 3, y + 5, 7, 4)
    g.fillStyle = cloth
    g.fillRect(x + 8, y + 9, 6, 4)
    g.fillStyle = '#E8B74A'
    g.fillRect(x + 4, y + 5, 2, 1)
  },
  clothRoll(g, x, y, col) {
    g.fillStyle = INK
    g.fillRect(x + 1, y + 5, 14, 9)
    g.fillStyle = col
    g.fillRect(x + 2, y + 6, 12, 7)
    g.fillStyle = shade(col, 1.2)
    g.fillRect(x + 2, y + 6, 12, 2)
    g.fillStyle = shade(col, 0.75)
    g.fillRect(x + 2, y + 11, 12, 2)
    g.fillStyle = '#F4F1E8'
    g.fillRect(x + 2, y + 6, 2, 7)
    g.fillStyle = '#C9B98A'
    g.fillRect(x + 3, y + 8, 1, 3)
  },
  hospitalBed(g, x, y) {
    const R = (c, a, b, w, h) => { g.fillStyle = c; g.fillRect(x + a, y + b, w, h) }
    R(INK, 1, 1, 14, 30)
    R('#D8DEE2', 2, 2, 12, 28)
    R('#FFFFFF', 3, 3, 10, 6)
    R('#F4F7F8', 3, 9, 10, 20)
    R('#6CB6D9', 3, 14, 10, 15)
    R('#5AA2C6', 3, 14, 10, 2)
  },
  blackboard(g, x, y, w = 3) {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x + 1, y + 2, W - 2, 12)
    g.fillStyle = '#8A5A2E'
    g.fillRect(x + 2, y + 3, W - 4, 10)
    g.fillStyle = '#2F5A46'
    g.fillRect(x + 3, y + 4, W - 6, 7)
    g.fillStyle = '#E9F2E6'
    g.fillRect(x + 5, y + 6, 8, 1)
    g.fillRect(x + 5, y + 8, 12, 1)
    g.fillRect(x + W - 12, y + 6, 6, 1)
  },
  studentDesk(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 2, y + 4, 12, 9)
    g.fillStyle = '#C79B61'
    g.fillRect(x + 3, y + 5, 10, 6)
    g.fillStyle = '#4A7BD4'
    g.fillRect(x + 5, y + 6, 4, 3)
    g.fillStyle = '#F4F1E8'
    g.fillRect(x + 9, y + 7, 3, 2)
  },
  tellerWindow(g, x, y, w = 3) {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x, y, W, 15)
    g.fillStyle = '#8A5A2E'
    g.fillRect(x + 1, y + 7, W - 2, 7)
    g.fillStyle = '#E0B070'
    g.fillRect(x + 1, y + 6, W - 2, 2)
    g.fillStyle = '#A9D8E8'
    g.fillRect(x + 1, y + 1, W - 2, 5)
    g.fillStyle = '#D5EEF6'
    for (let i = 3; i < W - 6; i += 14) g.fillRect(x + i, y + 2, 5, 1)
  },
  atm(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 2, y - 6, 12, 22)
    g.fillStyle = '#2F4B7C'
    g.fillRect(x + 3, y - 5, 10, 20)
    g.fillStyle = '#8FD0E8'
    g.fillRect(x + 4, y - 3, 8, 6)
    g.fillStyle = '#E9EEF0'
    g.fillRect(x + 5, y + 6, 6, 4)
  },
  bench(g, x, y, w = 1) {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x + 1, y + 5, W - 2, 9)
    g.fillStyle = '#C48A4E'
    g.fillRect(x + 2, y + 6, W - 4, 2)
    g.fillRect(x + 2, y + 9, W - 4, 2)
    g.fillStyle = '#7A4E28'
    g.fillRect(x + 3, y + 12, 2, 2)
    g.fillRect(x + W - 5, y + 12, 2, 2)
  },
  bush(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 2, y + 6, 12, 9)
    g.fillRect(x + 4, y + 4, 8, 3)
    g.fillStyle = '#3E9B4B'
    g.fillRect(x + 3, y + 7, 10, 7)
    g.fillRect(x + 5, y + 5, 6, 3)
    g.fillStyle = '#5DBB63'
    g.fillRect(x + 4, y + 7, 3, 2)
    g.fillRect(x + 8, y + 6, 2, 2)
  },
  tree(g, x, y, v = 0) {
    // trunk sits at the bottom of the tile, the crown reaches up a tile and a half
    const bx = x
    const by = y
    g.fillStyle = INK
    g.fillRect(bx + 6, by + 9, 4, 7)
    g.fillStyle = '#7A4B2A'
    g.fillRect(bx + 7, by + 9, 2, 6)
    const leaf = v ? '#3C8F55' : '#3E9B4B'
    const hi = v ? '#58B06B' : '#5DBB63'
    g.fillStyle = INK
    g.fillRect(bx + 1, by - 5, 14, 15)
    g.fillRect(bx + 3, by - 8, 10, 3)
    g.fillRect(bx, by - 2, 16, 8)
    g.fillStyle = leaf
    g.fillRect(bx + 2, by - 4, 12, 13)
    g.fillRect(bx + 4, by - 7, 8, 3)
    g.fillRect(bx + 1, by - 1, 14, 6)
    g.fillStyle = hi
    g.fillRect(bx + 4, by - 6, 5, 2)
    g.fillRect(bx + 3, by - 3, 4, 2)
    g.fillRect(bx + 9, by - 1, 3, 2)
    g.fillStyle = shade(leaf, 0.78)
    g.fillRect(bx + 3, by + 5, 10, 3)
    g.fillRect(bx + 10, by + 1, 3, 3)
  },
  pine(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 6, y + 10, 4, 6)
    g.fillStyle = '#6B4226'
    g.fillRect(x + 7, y + 10, 2, 5)
    const tiers = [[-8, 6], [-4, 10], [0, 14]]
    tiers.forEach(([dy, w]) => {
      g.fillStyle = INK
      g.fillRect(x + 8 - w / 2 - 1, y + dy + 1, w + 2, 9)
      g.fillStyle = '#2F7D4A'
      g.fillRect(x + 8 - w / 2, y + dy + 2, w, 7)
      g.fillStyle = '#459B5F'
      g.fillRect(x + 8 - w / 2 + 1, y + dy + 2, 2, 5)
    })
  },
  flowers(g, x, y, r) {
    const cols = ['#F5F1E4', '#F4D35E', '#F28FAD', '#C792EA']
    for (let i = 0; i < 4; i++) {
      const fx = x + 2 + Math.floor(r() * 11)
      const fy = y + 3 + Math.floor(r() * 10)
      const c = cols[Math.floor(r() * cols.length)]
      g.fillStyle = '#4C9A45'
      g.fillRect(fx, fy + 1, 1, 2)
      g.fillStyle = c
      g.fillRect(fx - 1, fy, 3, 1)
      g.fillRect(fx, fy - 1, 1, 3)
      g.fillStyle = '#F4D35E'
      g.fillRect(fx, fy, 1, 1)
    }
  },
  lamp(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 6, y - 6, 4, 22)
    g.fillRect(x + 4, y - 9, 8, 5)
    g.fillStyle = '#4A5160'
    g.fillRect(x + 7, y - 5, 2, 20)
    g.fillStyle = '#FFE9A0'
    g.fillRect(x + 5, y - 8, 6, 3)
  },
  stall(g, x, y, w, col, goods) {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x, y + 8, W, 14)
    g.fillStyle = '#9C6A38'
    g.fillRect(x + 1, y + 14, W - 2, 7)
    g.fillStyle = '#C48A4E'
    g.fillRect(x + 1, y + 11, W - 2, 3)
    for (let i = 0; i < w * 2; i++) {
      g.fillStyle = goods[i % goods.length]
      g.fillRect(x + 3 + i * 8, y + 9, 5, 3)
      g.fillStyle = shade(goods[i % goods.length], 1.2)
      g.fillRect(x + 4 + i * 8, y + 9, 2, 1)
    }
    g.fillStyle = INK
    g.fillRect(x, y - 6, W, 13)
    for (let i = 0; i < W; i += 6) {
      g.fillStyle = (i / 6) % 2 ? '#F4F1E8' : col
      g.fillRect(x + 1 + i, y - 5, Math.min(6, W - 1 - i), 10)
    }
    g.fillStyle = shade(col, 0.8)
    g.fillRect(x + 1, y + 3, W - 2, 2)
  },
  rickshaw(g, x, y, col = '#F2C230') {
    g.fillStyle = INK
    g.fillRect(x + 2, y + 3, 24, 16)
    g.fillStyle = '#2E3238'
    g.fillRect(x + 3, y + 4, 22, 5)
    g.fillStyle = col
    g.fillRect(x + 3, y + 9, 22, 7)
    g.fillStyle = '#9FD6EA'
    g.fillRect(x + 5, y + 10, 6, 3)
    g.fillStyle = shade(col, 0.82)
    g.fillRect(x + 3, y + 15, 22, 1)
    g.fillStyle = INK
    g.fillRect(x + 3, y + 16, 5, 4)
    g.fillRect(x + 20, y + 16, 5, 4)
    g.fillStyle = '#6B7079'
    g.fillRect(x + 4, y + 17, 3, 2)
    g.fillRect(x + 21, y + 17, 3, 2)
  },
  pump(g, x, y, col = '#D44A4A') {
    g.fillStyle = INK
    g.fillRect(x + 3, y - 4, 10, 19)
    g.fillStyle = col
    g.fillRect(x + 4, y - 3, 8, 17)
    g.fillStyle = '#9FD6EA'
    g.fillRect(x + 5, y - 1, 6, 4)
    g.fillStyle = '#2E3238'
    g.fillRect(x + 5, y + 5, 6, 2)
    g.fillStyle = '#F4F1E8'
    g.fillRect(x + 4, y + 11, 8, 2)
  },
  bricks(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 1, y + 5, 14, 10)
    const rows = [[3, 7], [7, 9], [11, 9]]
    rows.forEach(([dy], ri) => {
      for (let i = 0; i < 3; i++) {
        g.fillStyle = '#C0583A'
        g.fillRect(x + 2 + i * 4 + (ri % 2), y + 5 + ri * 3 + 1, 3, 2)
      }
    })
  },
  mixer(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 2, y + 1, 12, 14)
    g.fillStyle = '#E8863A'
    g.fillRect(x + 3, y + 2, 10, 8)
    g.fillStyle = '#B9632A'
    g.fillRect(x + 3, y + 8, 10, 2)
    g.fillStyle = '#6E757D'
    g.fillRect(x + 4, y + 11, 8, 3)
  },
  cone(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 5, y + 6, 6, 9)
    g.fillStyle = '#E8863A'
    g.fillRect(x + 6, y + 7, 4, 7)
    g.fillStyle = '#F4F1E8'
    g.fillRect(x + 6, y + 10, 4, 1)
    g.fillStyle = '#2E3238'
    g.fillRect(x + 4, y + 14, 8, 1)
  },
  clothesRack(g, x, y) {
    const cols = ['#D44A4A', '#4A7BD4', '#E8B74A', '#4AA66B', '#9A5FC4', '#F28FAD']
    g.fillStyle = INK
    g.fillRect(x + 1, y - 5, 14, 21)
    g.fillStyle = '#C9D0D5'
    g.fillRect(x + 2, y - 4, 12, 19)
    g.fillStyle = '#8E979E'
    g.fillRect(x + 2, y - 3, 12, 1)
    for (let i = 0; i < 5; i++) {
      g.fillStyle = cols[i % cols.length]
      g.fillRect(x + 3 + i * 2, y - 2, 2, 8)
      g.fillStyle = cols[(i + 2) % cols.length]
      g.fillRect(x + 3 + i * 2, y + 8, 2, 5)
    }
  },
  cinemaScreen(g, x, y, w) {
    const W = w * T
    g.fillStyle = INK
    g.fillRect(x, y, W, 12)
    g.fillStyle = '#1E2230'
    g.fillRect(x + 1, y + 1, W - 2, 10)
    g.fillStyle = '#6CC6E8'
    g.fillRect(x + 5, y + 3, W - 10, 5)
    g.fillStyle = '#E8B74A'
    g.fillRect(x + 8, y + 4, 5, 3)
  },
  window(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x, y, 10, 8)
    g.fillStyle = '#F4F1E8'
    g.fillRect(x + 1, y + 1, 8, 6)
    g.fillStyle = '#9FD6EA'
    g.fillRect(x + 2, y + 2, 3, 4)
    g.fillRect(x + 6, y + 2, 2, 4)
    g.fillStyle = '#D5EEF6'
    g.fillRect(x + 2, y + 2, 1, 2)
  },
  charpoy(g, x, y) {
    g.fillStyle = INK
    g.fillRect(x + 1, y + 2, 14, 28)
    g.fillStyle = '#9C6A38'
    g.fillRect(x + 2, y + 3, 12, 26)
    g.fillStyle = '#D8C089'
    g.fillRect(x + 4, y + 5, 8, 22)
    g.fillStyle = '#B79A5E'
    for (let i = 0; i < 22; i += 3) g.fillRect(x + 4, y + 6 + i, 8, 1)
    g.fillStyle = '#7C9FD0'
    g.fillRect(x + 5, y + 6, 6, 4)
  },
  sign(g, x, y, col) {
    g.fillStyle = INK
    g.fillRect(x + 6, y + 2, 4, 12)
    g.fillRect(x + 1, y - 6, 14, 9)
    g.fillStyle = col
    g.fillRect(x + 2, y - 5, 12, 7)
    g.fillStyle = '#F4F1E8'
    g.fillRect(x + 4, y - 3, 8, 1)
    g.fillRect(x + 4, y - 1, 6, 1)
  },
}

/* ── themes: what each building looks like ────────────────────────────── */

const THEME = {
  shanti_apts: { roof: '#6B7FB3', wall: '#E9E2D0', floor: 'wood2' },
  old_town: { roof: '#B5533C', wall: '#F0DFC0', floor: 'wood' },
  labour_colony: { roof: '#8A7B6C', wall: '#D9CDB8', floor: 'concrete' },
  lake_view: { roof: '#3F8F8A', wall: '#EEF1EA', floor: 'wood2' },
  kirana: { roof: '#3E9B4B', wall: '#F4E9C8', floor: 'tile' },
  supermarket: { roof: '#D6453D', wall: '#F2F0EA', floor: 'tileW' },
  pharmacy: { roof: '#2F9E78', wall: '#F2F6F2', floor: 'tileW' },
  cafe: { roof: '#8C5A3A', wall: '#F1DFC2', floor: 'wood' },
  restaurant: { roof: '#A8322F', wall: '#F1E4D0', floor: 'wood2' },
  mall: { roof: '#7B4FA3', wall: '#EDE8F4', floor: 'tileW' },
  tech_park: { roof: '#3C5F8F', wall: '#DCE4EE', floor: 'carpet' },
  factory: { roof: '#6D737B', wall: '#C9CED3', floor: 'concrete' },
  school: { roof: '#C2873A', wall: '#F4E6C0', floor: 'tile' },
  clinic: { roof: '#2F8FB5', wall: '#F2F8FA', floor: 'tileW' },
  bank: { roof: '#2F4B7C', wall: '#E8E6DE', floor: 'marble' },
}

/* ── a building: walls, floor, door, windows ──────────────────────────── */

function shell(g, p, th, r) {
  const { x, y, w, h } = p.rect
  const X = x * T
  const Y = y * T
  const W = w * T
  const H = h * T
  const dx = p.door.x - x
  const north = p.door.y < y
  floor(g, X, Y + T, W, H - T, th.floor, r)

  // top wall: roof edge, wall face, skirting
  g.fillStyle = th.roof
  g.fillRect(X, Y, W, 5)
  g.fillStyle = shade(th.roof, 0.78)
  g.fillRect(X, Y + 4, W, 1)
  g.fillStyle = shade(th.roof, 1.18)
  g.fillRect(X, Y, W, 1)
  g.fillStyle = th.wall
  g.fillRect(X, Y + 5, W, 11)
  g.fillStyle = shade(th.wall, 0.82)
  g.fillRect(X, Y + 14, W, 2)
  g.fillStyle = shade(th.wall, 0.92)
  for (let i = 0; i < W; i += 8) g.fillRect(X + i, Y + 5, 1, 9)

  // side and bottom walls
  g.fillStyle = shade(th.wall, 0.9)
  g.fillRect(X, Y + 16, 3, H - 16)
  g.fillRect(X + W - 3, Y + 16, 3, H - 16)
  g.fillRect(X, Y + H - 3, W, 3)
  g.fillStyle = shade(th.wall, 0.7)
  g.fillRect(X + 2, Y + 16, 1, H - 19)
  g.fillRect(X + W - 3, Y + 16, 1, H - 19)
  g.fillRect(X + 2, Y + H - 4, W - 4, 1)

  // windows along the top wall (never over the door)
  for (let tx = 1; tx < w - 1; tx += 2) {
    if (north && Math.abs(tx - dx) < 1.5) continue
    draw.window(g, X + tx * T + 3, Y + 6)
  }

  // outline
  g.fillStyle = INK
  g.fillRect(X, Y, W, 1)
  g.fillRect(X, Y, 1, H)
  g.fillRect(X + W - 1, Y, 1, H)
  g.fillRect(X, Y + H - 1, W, 1)

  // doorway
  if (north) {
    const dxp = X + dx * T
    floor(g, dxp + 1, Y + 5, 14, 11, th.floor, r)
    g.fillStyle = INK
    g.fillRect(dxp, Y, 16, 1)
    g.fillStyle = shade(th.roof, 0.9)
    g.fillRect(dxp + 1, Y + 1, 14, 4)
    g.fillStyle = INK
    g.fillRect(dxp, Y + 4, 1, 12)
    g.fillRect(dxp + 15, Y + 4, 1, 12)
    g.fillRect(dxp, Y + 4, 16, 1)
    g.fillStyle = '#B73A3A'
    g.fillRect(dxp + 3, Y + 12, 10, 3)
    g.fillStyle = '#8F2A2A'
    g.fillRect(dxp + 3, Y + 14, 10, 1)
  } else {
    const dxp = X + dx * T
    floor(g, dxp + 1, Y + H - 4, 14, 4, th.floor, r)
    g.fillStyle = INK
    g.fillRect(dxp, Y + H - 4, 1, 4)
    g.fillRect(dxp + 15, Y + H - 4, 1, 4)
    g.fillStyle = '#B73A3A'
    g.fillRect(dxp + 3, Y + H - 5, 10, 3)
  }
}

/* ── furnishing: what's inside each place ─────────────────────────────── */

function furnish(g, p, r) {
  const { x, y, w, h } = p.rect
  const X = x * T
  const Y = y * T
  const dx = p.door.x - x
  const at = (tx, ty) => [X + tx * T, Y + ty * T]
  const ok = (tx, span = 1) => !(dx >= tx && dx < tx + span) && !(dx === tx - 0 && span > 1)
  const place = (fn, tx, ty, span = 1, ...args) => {
    if (tx < 1 || tx + span > w - 1) return false
    if (!ok(tx, span)) return false
    const [px, py] = at(tx, ty)
    fn(g, px, py, ...args)
    return true
  }

  switch (p.kind === 'home' ? 'home' : p.id) {
    case 'home': {
      // a rug in the middle, then a row of furniture along the back wall
      if (h >= 6 && w >= 8) draw.rug(g, X + 3 * T, Y + 3 * T, w - 6, h - 4, ['#B8584A', '#C9923E', '#7A9E5B'][strSeed(p.id) % 3])
      const seq = p.id === 'labour_colony'
        ? ['charpoy', 'plant', 'charpoy', 'table', 'charpoy', 'plant']
        : ['bed', 'wardrobe', 'sofa', 'tv', 'table', 'fridge', 'stove', 'bookshelf', 'plant']
      const start = (strSeed(p.id) % 3)
      let tx = 1
      let i = start
      while (tx < w - 1 && i < start + 14) {
        const item = seq[i % seq.length]
        const span = item === 'sofa' || item === 'table' ? 2 : 1
        if (!ok(tx, span)) {
          tx += 1
          continue
        }
        if (tx + span > w - 1) break
        const [px, py] = at(tx, 1)
        if (item === 'bed') draw.bed(g, px, py, ['#5B8DD9', '#D4584A', '#4AA66B'][(tx + start) % 3])
        else if (item === 'charpoy') draw.charpoy(g, px, py)
        else if (item === 'wardrobe') draw.wardrobe(g, px, py + 2)
        else if (item === 'sofa') draw.sofa(g, px, py, 2, ['#B8584A', '#4A7BD4', '#7A9E5B'][(tx + start) % 3])
        else if (item === 'tv') draw.tv(g, px, py)
        else if (item === 'table') {
          draw.table(g, px, py + 2, 2)
        } else if (item === 'fridge') draw.fridge(g, px, py + 2)
        else if (item === 'stove') draw.stove(g, px, py + 2)
        else if (item === 'bookshelf') draw.bookshelf(g, px, py + 2)
        else draw.plant(g, px, py)
        tx += span
        i += 1
        if (item === 'bed' || item === 'charpoy') tx += 0
      }
      if (h >= 6) {
        draw.plant(g, X + T * 0.2 + 2, Y + (h - 1) * T - 12)
        draw.plant(g, X + (w - 1) * T - 2, Y + (h - 1) * T - 12)
      }
      break
    }
    case 'kirana': {
      const goods = [['#E36B2D', '#4AA66B', '#E8B74A'], ['#D44A4A', '#F4F1E8', '#4A7BD4']]
      for (let tx = 1; tx < w - 1; tx++) place(draw.shelf, tx, 1, 1, goods[tx % 2])
      place(draw.crate, 1, h - 2, 1, '#4AA66B')
      place(draw.crate, w - 2, h - 2, 1, '#E36B2D')
      break
    }
    case 'supermarket': {
      for (let tx = 1; tx < w - 1; tx++) place(draw.shelf, tx, 1, 1, [['#D44A4A', '#F4F1E8'], ['#E8B74A', '#4AA66B'], ['#4A7BD4', '#E36B2D']][tx % 3])
      place(draw.counter, 1, h - 2, 2)
      place(draw.crate, w - 2, h - 2, 1, '#E8B74A')
      place(draw.crate, w - 2, 3, 1, '#4AA66B')
      break
    }
    case 'pharmacy': {
      for (let tx = 1; tx < w - 1; tx++) place(draw.shelf, tx, 1, 1, [['#F4F1E8', '#4AA66B'], ['#6CB6D9', '#F4F1E8']][tx % 2])
      place(draw.counter, w - 3, h - 2, 2)
      place(draw.plant, 1, h - 2)
      break
    }
    case 'cafe': {
      place(draw.counter, 1, 1, 2)
      place(draw.shelf, w - 2, 1, 1, ['#C48A4E', '#F4F1E8'])
      place(draw.table, 1, h - 2, 1)
      place(draw.chair, w - 2, h - 2, 1, '#4A7BD4')
      place(draw.plant, w - 2, 3)
      break
    }
    case 'restaurant': {
      place(draw.counter, 1, 1, 2)
      place(draw.plant, w - 2, 1)
      place(draw.table, 1, 3, 2)
      place(draw.table, w - 3, 3, 2)
      place(draw.chair, 1, 4, 1)
      place(draw.chair, w - 2, 4, 1, '#4A7BD4')
      break
    }
    case 'mall': {
      ;[1, 2, 3, w - 2].forEach((tx) => place(draw.clothesRack, tx, 1, 1))
      place(draw.cinemaScreen, 6, 1, 3, 3)
      for (let tx = 1; tx < w - 1; tx += 3) place(draw.clothesRack, tx, h - 2, 1)
      place(draw.plant, w - 2, 3)
      place(draw.counter, 1, 3, 2)
      break
    }
    case 'tech_park': {
      for (let tx = 1; tx < w - 1; tx += 2) {
        place(draw.desk, tx, 1, 1)
        place(draw.chair, tx, 2, 1, '#3C5F8F')
      }
      for (let tx = 1; tx < w - 1; tx += 2) {
        place(draw.desk, tx, h - 3, 1)
        place(draw.chair, tx, h - 2, 1, '#3C5F8F')
      }
      place(draw.plant, w - 2, 3)
      place(draw.plant, 1, 3)
      break
    }
    case 'factory': {
      for (let tx = 1; tx < w - 1; tx += 2) {
        place(draw.sewing, tx, 1, 1, ['#D4584A', '#4A7BD4', '#E8B74A', '#4AA66B'][tx % 4])
        place(draw.sewing, tx, h - 2, 1, ['#E8B74A', '#9A5FC4', '#D4584A'][tx % 3])
      }
      place(draw.clothRoll, 1, 3, 1, '#D4584A')
      place(draw.clothRoll, w - 2, 3, 1, '#4A7BD4')
      place(draw.clothRoll, w - 2, 4, 1, '#E8B74A')
      break
    }
    case 'school': {
      place(draw.blackboard, 1, 1, 3, 3)
      for (let ty = 3; ty < h - 1; ty += 2) {
        for (let tx = 1; tx < w - 1; tx += 2) place(draw.studentDesk, tx, ty, 1)
      }
      break
    }
    case 'clinic': {
      place(draw.hospitalBed, 1, 1, 1)
      place(draw.hospitalBed, w - 2, 1, 1)
      place(draw.desk, 2, 1, 1, '#E9EEF0')
      place(draw.plant, w - 2, h - 2)
      break
    }
    case 'bank': {
      place(draw.tellerWindow, 1, 1, 3, 3)
      place(draw.atm, w - 2, 1, 1)
      place(draw.plant, 1, h - 1)
      break
    }
    default:
      break
  }
}

/* ── open-air places ──────────────────────────────────────────────────── */

function outdoor(g, p, r) {
  const { x, y, w, h } = p.rect
  const X = x * T
  const Y = y * T
  const W = w * T
  const H = h * T
  const dx = p.door.x - x
  const at = (tx, ty) => [X + tx * T, Y + ty * T]
  const fence = (col = '#B58A55') => {
    const gapX = X + dx * T
    g.fillStyle = INK
    ;[0, H - 4].forEach((oy) => {
      for (let i = 0; i < W; i += 1) {
        if (oy === 0 && i >= gapX - X && i < gapX - X + T) continue
        if (oy !== 0 && p.door.y > y && i >= gapX - X && i < gapX - X + T) continue
        g.fillRect(X + i, Y + oy + 1, 1, 1)
      }
    })
    g.fillStyle = col
    for (let i = 3; i < W - 3; i += 6) {
      if (i + 3 > gapX - X - 2 && i < gapX - X + T + 2) continue
      g.fillStyle = INK
      g.fillRect(X + i - 1, Y - 1, 4, 6)
      g.fillStyle = col
      g.fillRect(X + i, Y, 2, 4)
    }
  }

  switch (p.id) {
    case 'park': {
      floor(g, X, Y, W, H, 'dirt', r)
      g.fillStyle = '#8DCB63'
      g.fillRect(X, Y, W, H)
      speckle(g, X, Y, W, H, '#7BBA52', W * H / 16, r)
      speckle(g, X, Y, W, H, '#A8DC7F', W * H / 30, r)
      // sand path from the entrance round the pond
      g.fillStyle = '#E6D3A0'
      g.fillRect(X + dx * T + 2, Y, 12, H)
      g.fillRect(X + dx * T + 2, Y + T, W - dx * T - 8, 12)
      // pond
      g.fillStyle = INK
      g.fillRect(X + (w - 3.1) * T, Y + 3, 40, 28)
      g.fillStyle = '#5FA8D8'
      g.fillRect(X + (w - 3.1) * T + 1, Y + 4, 38, 26)
      g.fillStyle = '#86C4EA'
      g.fillRect(X + (w - 3.1) * T + 5, Y + 8, 10, 1)
      g.fillRect(X + (w - 3.1) * T + 18, Y + 18, 12, 1)
      draw.bench(g, ...at(0.6, 1.1), 1)
      draw.tree(g, ...at(0.1, 0.6), 1)
      draw.tree(g, ...at(w - 1.3, 0.6), 0)
      draw.flowers(g, ...at(0.2, 2.1), r)
      draw.flowers(g, ...at(w - 3.6, 2.1), r)
      break
    }
    case 'market': {
      floor(g, X, Y, W, H, 'cobble', r)
      fence('#B58A55')
      const stalls = [
        [1, 0.95, 3, '#D44A4A', ['#E36B2D', '#4AA66B', '#D44A4A']],
        [8, 0.95, 3, '#4AA66B', ['#E8B74A', '#9A5FC4', '#4AA66B']],
        [1, 4.3, 3, '#4A7BD4', ['#F4F1E8', '#E8B74A', '#E36B2D']],
        [8, 4.3, 3, '#E8B74A', ['#4AA66B', '#D44A4A', '#E8B74A']],
      ]
      stalls.forEach(([tx, ty, sw, col, goods]) => {
        if (tx <= dx && tx + sw > dx) return
        draw.stall(g, ...at(tx, ty), sw, col, goods)
      })
      draw.crate(g, ...at(4.3, 1.3), '#E36B2D')
      draw.crate(g, ...at(7.2, 1.3), '#4AA66B')
      draw.crate(g, ...at(4.2, 4.85), '#E8B74A')
      draw.crate(g, ...at(7.3, 4.85), '#D44A4A')
      break
    }
    case 'construction': {
      floor(g, X, Y, W, H, 'dirt', r)
      // hazard stripe along the front
      for (let i = 0; i < W; i += 8) {
        g.fillStyle = (i / 8) % 2 ? '#2E3238' : '#F2C230'
        g.fillRect(X + i, Y + H - 4, 8, 3)
      }
      g.fillStyle = INK
      g.fillRect(X, Y + H - 5, W, 1)
      draw.bricks(g, ...at(0.4, 0.1))
      draw.bricks(g, ...at(1.4, 0.1))
      draw.mixer(g, ...at(3.4, 0.1))
      draw.cone(g, ...at(5.1, 0.2))
      draw.cone(g, ...at(w - 3.1, 0.2))
      draw.bricks(g, ...at(w - 2.2, 0.1))
      draw.sign(g, ...at(w - 1.2, 0.1), '#F2C230')
      break
    }
    case 'auto_stand': {
      floor(g, X, Y, W, H, 'asphalt', r)
      g.fillStyle = '#F4F1E8'
      for (let i = 1; i < w - 1; i += 3) {
        g.fillRect(X + i * T, Y + 2, 1, 22)
      }
      g.fillRect(X + T, Y + 2, (w - 2) * T, 1)
      draw.rickshaw(g, ...at(1.1, 0.3), '#F2C230')
      draw.rickshaw(g, ...at(4.2, 0.3), '#4AA66B')
      draw.rickshaw(g, ...at(7.3, 0.3), '#F2C230')
      draw.sign(g, ...at(w - 1.1, 1.2), '#4AA66B')
      break
    }
    case 'fuel_station': {
      floor(g, X, Y, W, H, 'asphalt', r)
      // pumps under a canopy
      draw.pump(g, ...at(0.9, 1.4), '#D44A4A')
      draw.pump(g, ...at(3.1, 1.4), '#2F8F4E')
      g.fillStyle = INK
      g.fillRect(X + 2, Y + 1.8 * T, W - 4, 1)
      // kiosk
      g.fillStyle = INK
      g.fillRect(X + 3, Y + H - 2.6 * T, 2.2 * T, 2.4 * T)
      g.fillStyle = '#F4F1E8'
      g.fillRect(X + 4, Y + H - 2.6 * T + 1, 2.2 * T - 2, 2.4 * T - 2)
      g.fillStyle = '#D44A4A'
      g.fillRect(X + 4, Y + H - 2.6 * T + 1, 2.2 * T - 2, 5)
      draw.window(g, X + 9, Y + H - 2.6 * T + 8)
      g.fillStyle = '#F4F1E8'
      for (let i = 0; i < W; i += 8) g.fillRect(X + i, Y + H - 3, 4, 2)
      break
    }
    default:
      floor(g, X, Y, W, H, 'concrete', r)
  }
}

/* ── scenery ──────────────────────────────────────────────────────────── */

function roadMask(map) {
  const set = new Set(map.roads.map((q) => `${q.x},${q.y}`))
  // the little paths from the road to each door
  map.places.forEach((p) => {
    const north = p.door.y < p.rect.y
    const from = north ? p.door.y + 1 : p.rect.y + p.rect.h
    const to = north ? p.rect.y - 1 : p.door.y - 1
    for (let ty = from; ty <= to; ty++) set.add(`${p.door.x},${ty}`)
  })
  return set
}

function drawRoads(g, set, r) {
  const has = (x, y) => set.has(`${x},${y}`)
  set.forEach((key) => {
    const [x, y] = key.split(',').map(Number)
    const X = x * T
    const Y = y * T
    g.fillStyle = '#E8D6A4'
    g.fillRect(X, Y, T, T)
    speckle(g, X, Y, T, T, '#DCC890', 7, r)
    speckle(g, X, Y, T, T, '#CDB77C', 3, r)
    const n = has(x, y - 1)
    const s = has(x, y + 1)
    const w = has(x - 1, y)
    const e = has(x + 1, y)
    const edge = (rx, ry, rw, rh) => {
      g.fillStyle = '#C3AA6E'
      g.fillRect(X + rx, Y + ry, rw, rh)
    }
    const lip = (rx, ry, rw, rh) => {
      g.fillStyle = '#D6C08A'
      g.fillRect(X + rx, Y + ry, rw, rh)
    }
    if (!n) { lip(0, 1, T, 1); edge(0, 0, T, 1) }
    if (!s) { lip(0, T - 2, T, 1); edge(0, T - 1, T, 1) }
    if (!w) { lip(1, 0, 1, T); edge(0, 0, 1, T) }
    if (!e) { lip(T - 2, 0, 1, T); edge(T - 1, 0, 1, T) }
    if (n && w && !has(x - 1, y - 1)) edge(0, 0, 2, 2)
    if (n && e && !has(x + 1, y - 1)) edge(T - 2, 0, 2, 2)
    if (s && w && !has(x - 1, y + 1)) edge(0, T - 2, 2, 2)
    if (s && e && !has(x + 1, y + 1)) edge(T - 2, T - 2, 2, 2)
  })
}

function drawLake(g) {
  const cx = 54.4 * T
  const cy = 39.2 * T
  const rx = 6.6 * T
  const ry = 3.3 * T
  const top = 36.25 * T
  const x0 = Math.floor(cx - rx - 12)
  const x1 = Math.ceil(cx + rx + 12)
  for (let py = Math.floor(top); py < 40 * T; py++) {
    for (let px = x0; px < x1; px++) {
      const a = (px - cx) / rx
      const b = (py - cy) / ry
      const wob = 1 + 0.055 * Math.sin(px * 0.045 + 1) + 0.045 * Math.sin(py * 0.08 + px * 0.02)
      const d = Math.sqrt(a * a + b * b) / wob
      if (d < 1) {
        g.fillStyle = d > 0.9 ? '#3D84B8' : (px + py) % 11 === 0 ? '#76C1EA' : '#5BA8DC'
        g.fillRect(px, py, 1, 1)
      } else if (d < 1.07) {
        g.fillStyle = '#E3D09A'
        g.fillRect(px, py, 1, 1)
      } else if (d < 1.1) {
        g.fillStyle = '#C3AA6E'
        g.fillRect(px, py, 1, 1)
      }
    }
  }
  // lily pads and ripples
  const pads = [[51.2, 38.3], [57, 38.6], [54.2, 37.4], [49.8, 39.1], [58.5, 39.2]]
  pads.forEach(([lx, ly]) => {
    g.fillStyle = '#3E9B4B'
    g.fillRect(lx * T, ly * T, 6, 4)
    g.fillStyle = '#5DBB63'
    g.fillRect(lx * T + 1, ly * T, 3, 1)
    g.fillStyle = '#F28FAD'
    g.fillRect(lx * T + 3, ly * T + 1, 1, 1)
  })
  g.fillStyle = '#A8D8F2'
  ;[[52.4, 38.8, 10], [56, 37.9, 12], [53.6, 39.5, 8]].forEach(([lx, ly, lw]) => g.fillRect(lx * T, ly * T, lw, 1))
}

export function buildScene(map) {
  const W = map.width * T
  const H = map.height * T
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const g = canvas.getContext('2d')
  const r = rng32(7919)

  // grass
  for (let ty = 0; ty < map.height; ty++) {
    for (let tx = 0; tx < map.width; tx++) {
      g.fillStyle = (tx + ty) % 2 ? '#86C65E' : '#82C25A'
      g.fillRect(tx * T, ty * T, T, T)
      speckle(g, tx * T, ty * T, T, T, '#74B24F', 5, r)
      speckle(g, tx * T, ty * T, T, T, '#98D26E', 4, r)
      if (r() < 0.12) {
        const px = tx * T + 2 + Math.floor(r() * 11)
        const py = ty * T + 5 + Math.floor(r() * 8)
        g.fillStyle = '#5E9F3F'
        g.fillRect(px, py, 1, 3)
        g.fillRect(px + 2, py + 1, 1, 2)
        g.fillRect(px - 2, py + 1, 1, 2)
      }
    }
  }

  const roads = roadMask(map)
  drawLake(g)
  drawRoads(g, roads, r)

  // which tiles are free for scenery?
  const taken = new Set(roads)
  const sign = new Set()
  map.places.forEach((p) => {
    for (let ty = p.rect.y; ty < p.rect.y + p.rect.h; ty++) {
      for (let tx = p.rect.x; tx < p.rect.x + p.rect.w; tx++) taken.add(`${tx},${ty}`)
    }
    // the sign board hangs just below a building
    for (let tx = p.rect.x - 1; tx <= p.rect.x + p.rect.w; tx++) sign.add(`${tx},${p.rect.y + p.rect.h}`)
  })
  const inLake = (tx, ty) => {
    const a = (tx + 0.5 - 54.4) / 7.8
    const b = (ty + 0.5 - 39.2) / 4.6
    return a * a + b * b < 1
  }
  const free = (tx, ty) => tx >= 0 && ty >= 0 && tx < map.width && ty < map.height && !taken.has(`${tx},${ty}`) && !inLake(tx, ty)
  const nearPath = (tx, ty) => [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([a, b]) => roads.has(`${tx + a},${ty + b}`))

  // buildings, in a stable order
  map.places.forEach((p) => {
    const pr = rng32(strSeed(p.id))
    if (isOutdoor(p)) outdoor(g, p, pr)
    else {
      const th = THEME[p.id] || { roof: '#8A7B6C', wall: '#E3D9C6', floor: 'tile' }
      shell(g, p, th, pr)
      furnish(g, p, pr)
    }
  })

  // scenery, back to front so crowns overlap correctly
  const items = []
  for (let ty = 0; ty < map.height; ty++) {
    for (let tx = 0; tx < map.width; tx++) {
      if (!free(tx, ty) || sign.has(`${tx},${ty}`)) continue
      const q = r()
      const border = tx < 3 || tx > 60 || ty < 4 || ty > 35
      const above = free(tx, ty - 1) && !roads.has(`${tx},${ty - 1}`)
      if (nearPath(tx, ty)) {
        if (q < 0.1) items.push([ty, 'flowers', tx])
        else if (q < 0.2 && ty > 0 && !roads.has(`${tx},${ty - 1}`)) items.push([ty, 'bush', tx])
      } else if (border && above && q < 0.78) items.push([ty, q < 0.3 ? 'pine' : 'tree', tx])
      else if (above && q < 0.34) items.push([ty, q < 0.12 ? 'pine' : 'tree', tx])
      else if (q < 0.42) items.push([ty, 'flowers', tx])
      else if (q < 0.5) items.push([ty, 'bush', tx])
    }
  }
  items.sort((a, b) => a[0] - b[0])
  items.forEach(([ty, kind, tx], i) => {
    const X = tx * T
    const Y = ty * T
    if (kind === 'tree') draw.tree(g, X, Y, i % 2)
    else if (kind === 'pine') draw.pine(g, X, Y)
    else if (kind === 'bush') draw.bush(g, X, Y)
    else draw.flowers(g, X, Y, r)
  })

  // lamps at some crossings
  map.road_cols.forEach((cx, ci) => {
    map.road_rows.forEach((ry, ri) => {
      if ((ci + ri) % 2) return
      const tx = cx + 1
      const ty = ry + 1
      if (free(tx, ty)) draw.lamp(g, tx * T, ty * T)
    })
  })

  return { canvas, width: W, height: H }
}
