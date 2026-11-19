import { useState } from 'react'
import { ArrowDown, ArrowRight, ArrowUpRight, BellRing, Box, GitMerge } from 'lucide-react'
import { formatNumber, Status } from './components'

const benchmark = 'https://github.com/Adn2805/Stockflow/blob/7f18869dc20071e9a62e3178ce2f96291be4d621/benchmarks/results/concurrency.json'

const demos = [
  { title: 'Transaction-safe orders', description: 'Reserve scarce stock without overselling.', icon: GitMerge },
  { title: 'Automated replenishment', description: 'Turn low stock into a draft for approval.', icon: Box },
  { title: 'Reliable Telegram alerts', description: 'Queue alerts durably and retry failed deliveries.', icon: BellRing },
] as const

export function EngineeringOverview() {
  const [demo, setDemo] = useState(0)
  return <section className="engineering" aria-labelledby="engineering-heading">
    <div className="engineering-hero">
      <h1 id="engineering-heading">Warehouse operations under load</h1>
      <p>See how StockFlow protects inventory when orders compete, flags shortages, and delivers alerts after stock changes commit.</p>
      <a href="#warehouse-data">Explore warehouse data <ArrowDown size={16} aria-hidden="true" /></a>
    </div>
    <div className="engineering-nav" role="group" aria-label="Engineering demonstrations">
      {demos.map(({ title, description, icon: Icon }, index) => <button type="button" key={title}
        className="surface engineering-choice" aria-pressed={demo === index} onClick={() => setDemo(index)}>
        <Icon size={20} aria-hidden="true" />
        <span><strong>{title}</strong><small>{description}</small></span>
        <ArrowRight size={16} aria-hidden="true" />
      </button>)}
    </div>
    <section className="surface engineering-panel" aria-label={demos[demo].title}>
      {demo === 0 ? <Concurrency /> : demo === 1 ? <Reorder /> : <Telegram />}
    </section>
  </section>
}

function Concurrency() {
  const [attempts, setAttempts] = useState(500)
  const accepted = Math.min(attempts, 100)
  return <>
    <div className="panel-heading engineering-panel-heading">
      <div><h2>500 competing orders. 100 units in stock.</h2>
        <p>Recorded PostgreSQL benchmark. In each of two runs, 100 orders were accepted, 400 were rejected for insufficient stock, and zero units were oversold.</p></div>
      <a className="text-button" href={benchmark}>Raw benchmark results <ArrowUpRight size={15} aria-hidden="true" /></a>
    </div>
    <p className="simulation-note">Browser simulation. Move the slider to step through one-unit requests. It sends no API requests and runs no database transactions.</p>
    <div className="simulation-controls">
      <label>Requests replayed · {attempts} of 500
        <input aria-label="Requests replayed" aria-valuetext={`${attempts} of 500 requests`} type="range" min={0} max={500} value={attempts}
          onChange={event => setAttempts(Number(event.target.value))} />
      </label>
      <button type="button" className="secondary" onClick={() => setAttempts(attempts === 500 ? 0 : 500)}>
        {attempts === 500 ? 'Reset replay' : 'Replay all 500'}
      </button>
    </div>
    <dl className="simulation-results" aria-live="polite">
      <div><dt>Accepted</dt><dd>{accepted}</dd></div>
      <div><dt>Rejected</dt><dd>{attempts - accepted}</dd></div>
      <div><dt>Units oversold</dt><dd>0</dd></div>
    </dl>
  </>
}

function Reorder() {
  const [available, setAvailable] = useState('42')
  const [threshold, setThreshold] = useState('100')
  const [target, setTarget] = useState('150')
  const values = [available, threshold, target]
  const valid = values.every(value => value !== '' && Number.isSafeInteger(Number(value)) && Number(value) >= 0)
    && Number(target) > Number(threshold)
  const low = Number(available) < Number(threshold)
  const quantity = Number(target) - Number(available)
  return <>
    <div className="panel-heading"><div><h2>From low stock to a draft recommendation</h2>
      <p>Browser simulation. Adjust sample quantities for Packing Tape at Central warehouse. These inputs never change any warehouse data.</p>
    </div></div>
    <div className="reorder-sample">
      <label>Available units<input type="number" min={0} step={1} value={available} onChange={event => setAvailable(event.target.value)} /></label>
      <label>Reorder threshold<input type="number" min={0} step={1} value={threshold} onChange={event => setThreshold(event.target.value)} /></label>
      <label>Target available stock<input type="number" min={Number(threshold) + 1} step={1} value={target}
        onChange={event => setTarget(event.target.value)} /></label>
    </div>
    <p className="simulation-feedback" role="status">{!valid
      ? 'Enter non-negative whole numbers and set the target above the threshold.'
      : low ? `Draft recommendation: ${formatNumber(quantity)} units (${formatNumber(Number(target))} target − ${formatNumber(Number(available))} available). Manager approval is required.`
        : 'No recommendation. Available stock is at or above the reorder threshold.'}</p>
  </>
}

const alertSteps = [
  { title: 'Detect low stock', status: 'Draft', detail: 'An order leaves 42 units available. The 100-unit threshold is breached, so the stock transaction records a draft and queues one alert.' },
  { title: 'Process the outbox', status: 'Pending', detail: 'After commit, a worker claims the alert. Temporary Telegram failures are retried, and repeat stock changes share the same alert while the shortage stays open.' },
  { title: 'Record delivery', status: 'Sent', detail: 'When Telegram accepts the message, the worker records delivery. The dashboard shows the status and attempt count.' },
] as const

function Telegram() {
  const [step, setStep] = useState(0)
  return <>
    <div className="panel-heading"><div><h2>From stock change to Telegram delivery</h2>
      <p>One synthetic alert, shown in three steps. Real Telegram delivery was verified locally. This demo sends no messages.</p>
    </div></div>
    <div className="alert-steps" role="group" aria-label="Notification workflow">
      {alertSteps.map(({ title }, index) => <button type="button" key={title}
        className={index === step ? 'primary' : 'secondary'} aria-pressed={index === step}
        onClick={() => setStep(index)}>{title}</button>)}
    </div>
    <div className="simulation-feedback" role="status"><Status value={alertSteps[step].status} /> {alertSteps[step].detail}</div>
    {step === 2 && <p className="sample-message">Packing Tape · Central warehouse · 42 available · threshold 100 · suggested reorder 108 units</p>}
  </>
}
