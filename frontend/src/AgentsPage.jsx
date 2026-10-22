/**
 * AgentsPage — profiles of everyone who lives in the town.
 *
 * Each person is a small card with their pixel character and a short summary. Click a card and
 * it opens in place to the full profile: it grows to the full row while the other cards slide
 * smoothly out of the way (a "FLIP" animation), and the page scrolls to keep it in view.
 */

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import './agents.css'
import { resetTownLearning, townAgents, townLearning } from './api'
import { appearanceFor, spriteFrame, SPRITE_H, SPRITE_W } from './townSprites'

const rs = (v) => `₹${Math.round(v || 0).toLocaleString('en-IN')}`
const TIER = { low: 'Lower income', mid: 'Middle income', high: 'Higher income' }
const PAY = {
  monthly: 'Monthly salary', daily: 'Daily wage', self: 'Self-employed', business: 'Runs a shop',
  pension: 'Pension', allowance: 'Family allowance',
}
const VEHICLE = { none: 'On foot', bicycle: 'Bicycle', scooter: 'Scooter', car: 'Car', auto: 'Auto-rickshaw' }
const LOAN = {
  home: 'Home loan', vehicle: 'Vehicle loan', personal: 'Personal loan', credit_card: 'Credit card',
  moneylender: 'Moneylender', education: 'Education loan',
}
const REDUCED = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

function payLine(a) {
  switch (a.pay_type) {
    case 'monthly': return `${rs(a.pay_rate)} a month`
    case 'pension': return `${rs(a.pay_rate)} a month`
    case 'allowance': return `${rs(a.pay_rate)} a month`
    case 'daily': return `${rs(a.pay_rate)} per working day`
    case 'self': return `about ${rs(a.pay_rate)} a day before fuel`
    default: return 'Shop profit, day to day'
  }
}

function Sprite({ agent, scale }) {
  const ref = useRef(null)
  useEffect(() => {
    const c = ref.current
    const g = c.getContext('2d')
    g.clearRect(0, 0, SPRITE_W, SPRITE_H)
    g.drawImage(spriteFrame(appearanceFor(agent), 'down', 0), 0, 0)
  }, [agent])
  return <canvas ref={ref} width={SPRITE_W} height={SPRITE_H} className="ag__canvas" style={{ width: SPRITE_W * scale, height: SPRITE_H * scale }} />
}

function Row({ k, v }) {
  if (v === null || v === undefined || v === '') return null
  return (
    <div className="ag__row"><dt>{k}</dt><dd>{v}</dd></div>
  )
}

function Section({ title, children, wide }) {
  return (
    <section className={`ag__sec ${wide ? 'ag__sec--wide' : ''}`}>
      <h3>{title}</h3>
      {children}
    </section>
  )
}

function Curve({ runs }) {
  if (!runs.length) return null
  const W = 150
  const H = 36
  const vals = runs.map((r) => r.mean_reward)
  const lo = Math.min(...vals, 0)
  const hi = Math.max(...vals, 0.0001)
  const x = (i) => (runs.length === 1 ? W / 2 : 4 + (i * (W - 8)) / (runs.length - 1))
  const y = (v) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8)
  return (
    <svg className="ag__curve" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Average daily reward per run: ${vals.map((v) => v.toFixed(2)).join(', ')}`}>
      <line x1="0" x2={W} y1={y(0)} y2={y(0)} className="ag__curve-zero" />
      {runs.length > 1 && <polyline points={vals.map((v, i) => `${x(i)},${y(v)}`).join(' ')} className="ag__curve-line" />}
      {vals.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="3" className="ag__curve-dot"><title>{`${runs[i].scenario}: ${v.toFixed(2)}`}</title></circle>)}
    </svg>
  )
}

function Learned({ info, onReset }) {
  if (!info) return <p className="ag__none">Loading what they have learned…</p>
  const { runs, lessons, trust, influences } = info
  if (!runs.length && !lessons.length) {
    return <p className="ag__none">Nothing yet. Run a simulation with residents set to Learn, and each one will remember what happened to them.</p>
  }
  const last = runs[runs.length - 1]
  return (
    <div className="ag__learn">
      <div className="ag__learn-top">
        <div>
          <span className="ag__learn-k">Average reward per day, by run</span>
          <Curve runs={runs} />
          <span className="ag__learn-note">{runs.length} run{runs.length === 1 ? '' : 's'}{last ? `; latest ${last.mean_reward >= 0 ? '+' : ''}${last.mean_reward.toFixed(2)} (${last.scenario})` : ''}</span>
        </div>
        <button type="button" className="ag__reset" onClick={onReset}>Forget everything</button>
      </div>
      {lessons.length > 0 && (
        <ul className="ag__lessons">
          {lessons.map((l, i) => (
            <li key={i}>
              <span className={`ag__lk ag__lk--${l.kind}`}>{l.kind === 'do' ? 'Do' : 'Avoid'}</span>
              <span className="ag__lt">{l.text}</span>
              <span className="ag__ls" title={`strength ${l.strength}, confirmed ${l.confirmed}×`}><i style={{ width: `${Math.round(l.strength * 100)}%` }} /></span>
            </li>
          ))}
        </ul>
      )}
      {info.lesson_count > lessons.length && <p className="ag__none">Showing the strongest of {info.lesson_count}.</p>}
      {trust.length > 0 && (
        <div className="ag__chips">
          {trust.map((t) => (
            <span key={t.name} className={`ag__chip ag__chip--static ${t.trust >= 0.5 ? 'is-good' : 'is-bad'}`}
              title={t.topic || ''}>{t.name}<span>{t.trust >= 0.5 ? 'trusts' : 'wary'} {Math.round(t.trust * 100)}%</span></span>
          ))}
        </div>
      )}
      {influences.some((i) => i.changed) && (
        <ul className="ag__infl">
          {influences.filter((i) => i.changed).slice(0, 3).map((i, k) => (
            <li key={k}>After talking with <b>{i.name}</b> on day {i.day}, changed plans ({i.change || 'new plan'})
              {i.reward !== null && i.reward !== undefined ? `; that day's reward ${i.reward >= 0 ? '+' : ''}${i.reward.toFixed(1)}` : ''}.</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Details({ a, onPick, learn, onReset }) {
  const loans = a.loans || []
  return (
    <div className="ag__body">
      <p className="ag__bio">{a.bio}</p>
      <div className="ag__secs">
        <Section title="Work and income">
          <dl>
            <Row k="Job" v={a.job_title} />
            <Row k="Workplace" v={a.workplace_name} />
            <Row k="Income type" v={PAY[a.pay_type]} />
            <Row k="Earns" v={payLine(a)} />
            <Row k="Income level" v={TIER[a.income_tier]} />
            <Row k="Follows the news" v={a.reads_news ? 'Yes' : 'Rarely'} />
          </dl>
        </Section>
        <Section title="Home and household">
          <dl>
            <Row k="Lives in" v={a.home_name} />
            <Row k="Housing" v={a.renter ? `Rents, ${rs(a.rent)} a month` : 'Owns the home'} />
            <Row k="Household" v={a.household_size === 1 ? 'Lives alone' : `${a.household_size} people`} />
            <Row k="School-going children" v={a.children || null} />
            <Row k="School fees" v={a.school_fee ? `${rs(a.school_fee)}, due on day ${a.school_fee_due_day}` : null} />
            <Row k="Utility bill" v={a.utility_bill ? `${rs(a.utility_bill)} a month` : null} />
            <Row k="Getting around" v={VEHICLE[a.vehicle] || a.vehicle} />
            <Row k="Family elsewhere" v={a.migrant_from ? `${a.migrant_from}; sends about ${rs(a.remittance_target)} a month` : null} />
          </dl>
        </Section>
        <Section title="Money at the start">
          <dl>
            <Row k="Cash" v={rs(a.money)} />
            <Row k="Credit score" v={a.credit_score} />
            <Row k="Food at home" v={`${(a.pantry_days || 0).toFixed(1)} days`} />
            {a.vehicle !== 'none' && a.vehicle !== 'bicycle' && <Row k="Fuel at home" v={`${(a.fuel_days || 0).toFixed(1)} days`} />}
            <Row k="Health" v={a.chronic_condition ? `${a.chronic_condition}; medicines about ${rs(a.medicine_monthly)} a month` : 'No ongoing condition'} />
          </dl>
          {loans.length > 0 ? (
            <ul className="ag__loans">
              {loans.map((l, i) => (
                <li key={i}>
                  <b>{LOAN[l.kind] || l.kind}</b>
                  <span>{rs(l.emi)} {l.frequency}, {rs(l.outstanding)} left</span>
                </li>
              ))}
            </ul>
          ) : <p className="ag__none">No loans.</p>}
        </Section>
        <Section title="Goals">
          <ul className="ag__goals">{(a.goals || []).map((g) => <li key={g}>{g}</li>)}</ul>
        </Section>
        <Section title="Knows">
          {(a.relations || []).length ? (
            <div className="ag__chips">
              {a.relations.map((r) => (
                <button type="button" key={r.id} className="ag__chip" onClick={() => onPick(r.id)}>
                  {r.name}<span>{r.relation}</span>
                </button>
              ))}
            </div>
          ) : <p className="ag__none">No close ties yet.</p>}
        </Section>
        <Section title="What I have learned" wide>
          <Learned info={learn} onReset={onReset} />
        </Section>
      </div>
    </div>
  )
}

export default function AgentsPage({ initialOpen = null }) {
  const [agents, setAgents] = useState(null)
  const [err, setErr] = useState('')
  const [openId, setOpenId] = useState(initialOpen)
  const [learn, setLearn] = useState(null)
  const refs = useRef(new Map())
  const before = useRef(null)

  useEffect(() => {
    townAgents().then(setAgents).catch((e) => setErr(
      /not found|404/i.test(e.message || '') ? 'The page opened, but the running backend is out of date and has no residents endpoint yet. Stop it (Ctrl+C) and run ./start.sh again, then reload this page.' : (e.message || 'Could not load the residents.')))
  }, [])

  const loadLearn = useCallback(() => {
    townLearning().then(setLearn).catch(() => setLearn({ available: false, agents: {} }))
  }, [])
  useEffect(() => { loadLearn() }, [loadLearn])
  const forget = (id) => {
    if (!window.confirm(`Forget everything ${id ? 'this resident has' : 'all residents have'} learned? This cannot be undone.`)) return
    resetTownLearning(id).then(loadLearn).catch((e) => setErr(e.message))
  }

  // remember where every card is, then change which one is open
  const select = useCallback((id) => {
    const m = new Map()
    refs.current.forEach((el, k) => m.set(k, el.getBoundingClientRect()))
    before.current = m
    setOpenId((cur) => (cur === id ? null : id))
  }, [])

  // after the layout changes: slide every card from where it was to where it is now
  useLayoutEffect(() => {
    const prev = before.current
    before.current = null
    if (!prev || REDUCED()) return
    refs.current.forEach((el, id) => {
      const a = prev.get(id)
      if (!a) return
      const b = el.getBoundingClientRect()
      const dx = a.left - b.left
      const dy = a.top - b.top
      const resized = Math.abs(a.width - b.width) > 1 || Math.abs(a.height - b.height) > 1
      if (!dx && !dy && !resized) return
      const from = { transform: `translate(${dx}px, ${dy}px)` }
      const to = { transform: 'translate(0, 0)' }
      if (resized) {
        from.width = `${a.width}px`
        from.height = `${a.height}px`
        to.width = `${b.width}px`
        to.height = `${b.height}px`
      }
      el.animate([from, to], { duration: 380, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)' })
    })
  }, [openId])

  // keep the opened profile in view
  useEffect(() => {
    if (!openId || !agents) return undefined
    const t = setTimeout(() => refs.current.get(openId)?.scrollIntoView({ behavior: REDUCED() ? 'auto' : 'smooth', block: 'start' }), 60)
    return () => clearTimeout(t)
  }, [openId, agents])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && openId) select(openId)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openId, select])

  return (
    <div className="agents">
      <div className="agents__inner">
        <h1 className="agents__title">Agent profiles</h1>
        <p className="agents__lede">
          The {agents ? agents.length : 20} residents of the town. Each is an AI agent with their own job, home, money, debts and goals.
          Select a profile to see everything about them.
        </p>
        {err && <p className="agents__err" role="alert">{err}</p>}
        {!agents && !err && <p className="agents__lede">Loading residents…</p>}
        {agents && (
          <div className="agents__grid">
            {agents.map((a) => {
              const open = openId === a.id
              return (
                <article
                  key={a.id}
                  ref={(el) => {
                    if (el) refs.current.set(a.id, el)
                    else refs.current.delete(a.id)
                  }}
                  className={`ag ${open ? 'is-open' : ''}`}
                >
                  <button type="button" className="ag__head" aria-expanded={open} onClick={() => select(a.id)}>
                    <span className="ag__portrait"><Sprite agent={a} scale={open ? 6 : 4} /></span>
                    <span className="ag__main">
                      <span className="ag__name">{a.name}</span>
                      <span className="ag__role">{a.age} · {a.job_title}</span>
                      <span className="ag__home">{a.home_name}</span>
                    </span>
                    <svg className="ag__chev" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
                  </button>
                  {!open && (
                    <div className="ag__brief">
                      <span className="ag__tag">{TIER[a.income_tier]}</span>
                      <span className="ag__tag">{rs(a.money)} cash</span>
                      {(a.loans || []).length > 0 && <span className="ag__tag">{a.loans.length} loan{a.loans.length > 1 ? 's' : ''}</span>}
                    </div>
                  )}
                  {open && <Details a={a} onPick={(id) => select(id)} learn={learn?.available === false ? { runs: [], lessons: [], trust: [], influences: [], lesson_count: 0 } : learn?.agents?.[a.id]}
                    onReset={() => forget(a.id)} />}
                </article>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
