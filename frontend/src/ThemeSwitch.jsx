/**
 * ThemeSwitch — light / dark toggle for the top bar.
 *
 * The choice is stored in localStorage and applied as data-theme on <html> (index.html sets it
 * before the first paint so there is no flash). With no saved choice it follows the system.
 * Switching cross-fades the whole page (View Transitions where supported, a colour transition otherwise).
 */

import React, { useEffect, useState } from 'react'
import { flushSync } from 'react-dom'

const KEY = 'ecosim-theme'

function initial() {
  try {
    const saved = window.localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* storage unavailable */ }
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const Sun = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
    <circle cx="8" cy="8" r="2.8" />
    <path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" />
  </svg>
)
const Moon = () => (
  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true">
    <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z" />
  </svg>
)

const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function ThemeSwitch() {
  const [theme, setTheme] = useState(initial)

  const choose = (next) => {
    if (next === theme) return
    const root = document.documentElement
    const apply = () => {
      root.dataset.theme = next
      flushSync(() => setTheme(next))
    }
    if (reduced()) {
      apply()
    } else if (document.startViewTransition) {
      document.startViewTransition(apply)
    } else {
      root.classList.add('theme-fade')
      apply()
      setTimeout(() => root.classList.remove('theme-fade'), 450)
    }
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { window.localStorage.setItem(KEY, theme) } catch { /* ignore */ }
  }, [theme])

  return (
    <div className="theme-switch" role="group" aria-label="Colour theme">
      <span className="theme-switch__thumb" style={{ transform: `translateX(${theme === 'dark' ? 30 : 0}px)` }} />
      <button type="button" aria-pressed={theme === 'light'} aria-label="Light mode" title="Light mode" onClick={() => choose('light')}><Sun /></button>
      <button type="button" aria-pressed={theme === 'dark'} aria-label="Dark mode" title="Dark mode" onClick={() => choose('dark')}><Moon /></button>
    </div>
  )
}
