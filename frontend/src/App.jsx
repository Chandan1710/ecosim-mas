/**
 * App — root layout shell for EcoSim-MAS dashboard.
 *
 * Module 11a: static environment only.
 * The 3D canvas occupies the full viewport below a minimal header.
 */

import './index.css'
import ZoneScene from './ZoneScene'

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__dot" aria-hidden="true" />
        <span className="app-header__wordmark">EcoSim-MAS</span>
        <span className="app-header__subtitle">Multi-Agent Economic Simulation</span>
      </header>

      <main className="app-canvas-wrap">
        <ZoneScene />
      </main>
    </div>
  )
}
