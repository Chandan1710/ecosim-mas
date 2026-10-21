/**
 * App — root layout shell for EcoSim-MAS dashboard (Module 11).
 *
 * Header with simulation controls + Live 2D World Scene.
 */

import React, { useState } from 'react'
import './index.css'
import ZoneScene from './ZoneScene'

export default function App() {
  const [runIdInput, setRunIdInput] = useState('')
  const [activeRunId, setActiveRunId] = useState(null)
  const [simStatus, setSimStatus] = useState('idle')
  const [currentTick, setCurrentTick] = useState(null)

  const handleConnect = (e) => {
    e.preventDefault()
    if (runIdInput.trim()) {
      setActiveRunId(runIdInput.trim())
    }
  }

  const handleTickUpdate = (data) => {
    if (data && data.tick !== undefined) {
      setCurrentTick(data.tick)
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__dot" aria-hidden="true" />
        <span className="app-header__wordmark">EcoSim-MAS</span>
        <span className="app-header__subtitle" style={{ marginLeft: '8px', color: '#6B6B68' }}>
          2D Simulation World
        </span>

        {/* Status indicator */}
        <div style={{
          marginLeft: '20px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          fontSize: '12px',
          color: simStatus === 'complete' ? '#4E8752' : (simStatus.startsWith('streaming') ? '#2F6FED' : '#6B6B68'),
          background: '#FFFFFF',
          border: '1px solid #E5E5E0',
          padding: '3px 10px',
          borderRadius: '16px',
        }}>
          <span style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            backgroundColor: simStatus === 'complete' ? '#4E8752' : (simStatus.startsWith('streaming') ? '#2F6FED' : '#B0B0A8'),
          }} />
          <span style={{ textTransform: 'capitalize' }}>
            {simStatus === 'idle' ? 'Ready' : simStatus}
          </span>
          {currentTick !== null && (
            <span style={{ fontWeight: 600, marginLeft: '4px' }}>
              (Tick {currentTick})
            </span>
          )}
        </div>

        {/* Connect Form */}
        <form onSubmit={handleConnect} style={{ marginLeft: 'auto', display: 'flex', gap: '8px', alignItems: 'center' }}>
          <input
            type="text"
            placeholder="Enter simulation run_id..."
            value={runIdInput}
            onChange={(e) => setRunIdInput(e.target.value)}
            style={{
              padding: '6px 10px',
              borderRadius: '6px',
              border: '1px solid var(--color-border)',
              fontFamily: 'inherit',
              fontSize: '12px',
              width: '280px',
              outline: 'none',
              background: '#FFFFFF',
            }}
          />
          <button
            type="submit"
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              border: 'none',
              background: 'var(--color-accent)',
              color: 'white',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 500,
              transition: 'opacity 0.2s',
            }}
          >
            Connect
          </button>
        </form>
      </header>

      <main className="app-canvas-wrap">
        <ZoneScene
          runId={activeRunId}
          onTickUpdate={handleTickUpdate}
          onStatusChange={setSimStatus}
        />
      </main>
    </div>
  )
}
