/**
 * Sidebar — a slim icon rail on the left of the home area. Move the cursor onto it (or tab
 * into it) and it slides open to show labels; move away and it folds back. It floats over the
 * page when open, so the content never jumps.
 *
 * To add a feature: add one entry to NAV (id, label, icon) and handle its id in App.jsx.
 */

import React from 'react'
import './sidebar.css'

const Icon = ({ children }) => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)

export const NAV = [
  {
    id: 'home',
    label: 'Home',
    icon: <Icon><path d="M3.5 9.2 10 3.8l6.5 5.4" /><path d="M5 8.2V16h3.8v-4.2h2.4V16H15V8.2" /></Icon>,
  },
  {
    id: 'dashboard',
    label: 'Dashboard',
    icon: <Icon><rect x="3" y="3" width="6" height="7.2" rx="1.3" /><rect x="11" y="3" width="6" height="4" rx="1.3" /><rect x="3" y="12.2" width="6" height="4.8" rx="1.3" /><rect x="11" y="9.2" width="6" height="7.8" rx="1.3" /></Icon>,
  },
  {
    id: 'agents',
    label: 'Agent profiles',
    icon: <Icon><circle cx="7.5" cy="7" r="2.6" /><path d="M2.8 16c0-2.6 2.1-4.5 4.7-4.5s4.7 1.9 4.7 4.5" /><circle cx="14" cy="7.8" r="2" /><path d="M13.6 11.7c2 .1 3.6 1.5 3.6 3.8" /></Icon>,
  },
  {
    id: 'propagation',
    label: 'Event propagation',
    icon: <Icon><circle cx="10" cy="4" r="1.7" /><circle cx="5" cy="11" r="1.7" /><circle cx="15" cy="11" r="1.7" /><circle cx="10" cy="16.2" r="1.3" /><path d="M10 5.7v2.4M8.9 8.3 6 9.6M11.1 8.3 14 9.6M5.6 12.6 9 15M14.4 12.6 11 15" /></Icon>,
  },
  {
    id: 'validation',
    label: 'Validation',
    icon: <Icon><circle cx="10" cy="10" r="7" /><path d="m6.8 10.2 2.2 2.2 4.2-4.6" /></Icon>,
  },
  {
    id: 'history',
    label: 'Recent runs',
    icon: <Icon><path d="M3.6 10a6.4 6.4 0 1 0 1.9-4.5" /><path d="M3.4 3.8v3h3" /><path d="M10 6.6V10l2.4 1.6" /></Icon>,
  },
]

export default function Sidebar({ active, onNavigate }) {
  return (
    <nav className="sb" aria-label="Main">
      <div className="sb__panel">
        <ul className="sb__list">
          {NAV.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={`sb__item ${active === item.id ? 'is-active' : ''}`}
                onClick={() => onNavigate(item.id)}
                aria-current={active === item.id ? 'page' : undefined}
                title={item.label}
              >
                <span className="sb__icon">{item.icon}</span>
                <span className="sb__label">{item.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  )
}
