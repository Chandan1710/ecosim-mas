/**
 * App — root shell for EcoSim-MAS.
 *
 * Three views:
 *   home   : start a town run from a ready-made shock, or open a saved run
 *   intake : describe your own scenario (Module 2) — it becomes the town's shock
 *   agents : profiles of everyone who lives in the town
 *   propagation: how each scenario spreads, as an editable chain of events (ready-made, yours, drafts)
 *   history: every saved run, with replay, PDF reports and the raw event log
 *   town   : the live / replayed town of generative agents (§7.6)
 *
 * The earlier 10-agent RL world (ZoneScene) remains in the codebase as the
 * baseline it is compared against; the app now opens the town.
 */

import React, { useState } from 'react'
import './index.css'
import IntakeFlow from './IntakeFlow'
import TownHome from './TownHome'
import TownView from './TownView'
import Sidebar from './Sidebar'
import AgentsPage from './AgentsPage'
import ThemeSwitch from './ThemeSwitch'
import Logo from './Logo'
import RunHistoryPage from './RunHistoryPage'
import PropagationPage from './PropagationPage'
import DashboardPage from './DashboardPage'
import ValidationPage from './ValidationPage'

// A link like /?run=<run_id> opens that run directly. Read once at module load
// (StrictMode runs initialisers twice in dev) and strip it from the URL.
function runFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search)
    const runId = params.get('run')
    if (!runId) return null
    window.history.replaceState(null, '', window.location.pathname)
    return runId
  } catch {
    return null
  }
}
const INITIAL_RUN = runFromUrl()

export default function App() {
  const [view, setView] = useState(INITIAL_RUN ? 'town' : 'home')
  const [runId, setRunId] = useState(INITIAL_RUN)
  const [days, setDays] = useState(7)
  const [agentFocus, setAgentFocus] = useState(null) // a resident to open when the profiles page shows
  const [resume, setResume] = useState(null) // a saved scenario reopened in the chain studio
  const seed = 7 // the same 20 residents every time, so runs are comparable

  const open = (id) => {
    setRunId(id)
    setView('town')
  }

  // the logo always leads home; if you are already there it scrolls back to the top
  const goHome = () => {
    if (view === 'home') document.querySelector('.home')?.scrollTo({ top: 0, behavior: 'smooth' })
    else setView('home')
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <button type="button" className="app-header__home" onClick={goHome} title="Home">
          <Logo />
        </button>
        <div className="app-header__right">
          {view === 'intake' && (
            <button type="button" className="app-header__btn" onClick={() => { setView(resume ? 'propagation' : 'home'); setResume(null) }}>
              {resume ? 'Back to scenarios' : 'Back to runs'}
            </button>
          )}
          <ThemeSwitch />
        </div>
      </header>

      <div className="app-body">
        {view !== 'town' && (
          <Sidebar
            active={view === 'intake' && resume ? 'propagation' : ['dashboard', 'agents', 'history', 'propagation', 'validation'].includes(view) ? view : 'home'}
            onNavigate={(id) => { setResume(null); setAgentFocus(null); setView(id) }}
          />
        )}
        <main className="app-canvas-wrap">
          {view === 'home' && (
            <TownHome onOpen={open} onDescribe={() => { setResume(null); setView('intake') }} onViewAll={() => setView('history')} days={days} setDays={setDays} seed={seed} />
          )}
          {view === 'dashboard' && (
            <DashboardPage
              lastRunId={runId} onOpenRun={open} onHome={() => setView('home')}
              onOpenAgent={(id) => { setAgentFocus(id); setView('agents') }}
              onOpenValidation={(id) => { try { sessionStorage.setItem('ecosim-val-run', id) } catch { /* private window */ } setView('validation') }}
              onOpenScenario={(key) => { try { sessionStorage.setItem('ecosim-prop', key) } catch { /* private window */ } setView('propagation') }}
            />
          )}
          {view === 'validation' && (
            <ValidationPage onOpenDashboard={(id) => { try { sessionStorage.setItem('ecosim-dash-run', id) } catch { /* private window */ } setView('dashboard') }} />
          )}
          {view === 'agents' && <AgentsPage key={agentFocus || 'all'} initialOpen={agentFocus} />}
          {view === 'history' && <RunHistoryPage onOpen={open} />}
          {view === 'propagation' && (
            <PropagationPage
              onOpenRun={open} days={days} seed={Number(seed) || 7}
              onEdit={(rec) => { setResume(rec); setView('intake') }}
              onDescribe={() => { setResume(null); setView('intake') }}
            />
          )}
          {view === 'intake' && (
            <IntakeFlow
              key={resume ? resume.key : 'new'} resume={resume} runOptions={{ days, seed: Number(seed) || 7 }}
              onStarted={(r) => { setResume(null); open(r.runId) }} onOpenRun={open}
              onExit={() => { setResume(null); setView('propagation') }}
            />
          )}
          {view === 'town' && runId && <TownView key={runId} runId={runId} onExit={() => setView('home')} />}
        </main>
      </div>
    </div>
  )
}
