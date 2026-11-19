import { useEffect, useState, type FormEvent } from 'react'
import { listAll, post, request, type Product, type Warehouse } from './api'
import { Empty, formatDate, formatNumber, Notice, Status, Table } from './components'

type Policy = { product_id: number; warehouse_id: number; threshold: number; target: number }
type Recommendation = {
  id: number; product_id: number; warehouse_id: number; available: number; threshold: number
  suggested_quantity: number; approved_at: string | null; resolved_at: string | null
  notification_status: string; notification_attempts: number; delivered_at: string | null
}

export function Replenishment({ products, warehouses, token, version }: {
  products: Product[]; warehouses: Warehouse[]; token: string; version: number
}) {
  const [policies, setPolicies] = useState<Policy[]>([])
  const [drafts, setDrafts] = useState<Recommendation[]>([])
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [product, setProduct] = useState('')
  const [warehouse, setWarehouse] = useState('')
  const selected = policies.find(policy =>
    String(policy.product_id) === product && String(policy.warehouse_id) === warehouse)
  const productName = (id: number) => products.find(row => row.id === id)?.name ?? '#' + id
  const warehouseName = (id: number) => warehouses.find(row => row.id === id)?.name ?? '#' + id

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    void Promise.all([
      listAll<Policy>('/replenishment/policies', token, controller.signal),
      listAll<Recommendation>('/replenishment/recommendations', token, controller.signal),
    ]).then(([rules, rows]) => {
      if (!controller.signal.aborted) { setPolicies(rules); setDrafts(rows) }
    }).catch(error => {
      if (!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Unable to load replenishment.')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [token, refresh, version])

  async function change(path: string, options: RequestInit, message: string) {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await request(path, token, options)
      setNotice(message)
      setRefresh(value => value + 1)
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to save changes.')
    } finally { setBusy(false) }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    void change('/replenishment/policies/' + product + '/' + warehouse, post({
      threshold: Number(form.get('threshold')), target: Number(form.get('target')),
    }, 'PATCH'), 'Reorder policy saved.')
  }

  return <div className="replenishment">
    {error && <Notice error>{error}</Notice>}
    {notice && <Notice tone="success">{notice}</Notice>}
    {loading && <div role="status">Loading replenishment…</div>}
    <section className="surface form-panel">
      <h2>Reorder policy</h2>
      {products.length > 0 && warehouses.length > 0 ? <form className="form-grid policy-grid" onSubmit={save}>
        <label>Product<select value={product} onChange={event => setProduct(event.target.value)} required>
          <option value="">Choose a product</option>
          {products.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label>Warehouse<select value={warehouse} onChange={event => setWarehouse(event.target.value)} required>
          <option value="">Choose a warehouse</option>
          {warehouses.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <fieldset className="policy-fields" key={[product, warehouse, selected?.threshold, selected?.target].join(':')}>
          <label>Reorder threshold<input name="threshold" type="number" min={0} max={Number.MAX_SAFE_INTEGER - 1}
            step={1} defaultValue={selected?.threshold} required /></label>
          <label>Target available stock<input name="target" type="number" min={1} max={Number.MAX_SAFE_INTEGER}
            step={1} defaultValue={selected?.target} required /></label>
        </fieldset>
        <button className="primary fit" disabled={busy || loading}>Save policy</button>
      </form> : <Empty>Add a product and warehouse to configure a policy.</Empty>}
    </section>
    <section>
      <div className="panel-heading report-heading"><div>
        <h2>Recommendations and Telegram delivery</h2>
        <p>{drafts.filter(row => row.resolved_at === null).length} active low-stock situations</p>
      </div></div>
      <Table columns={['Product', 'Warehouse', 'Available', 'Threshold', 'Suggested units', 'Recommendation', 'Telegram', 'Action']}
        rows={drafts} empty={loading ? 'Loading recommendations…' : 'No replenishment recommendations yet.'}
        render={row => <tr key={row.id}>
          <td>{productName(row.product_id)}</td><td>{warehouseName(row.warehouse_id)}</td>
          <td>{formatNumber(row.available)}</td><td>{formatNumber(row.threshold)}</td>
          <td>{formatNumber(row.suggested_quantity)}</td>
          <td><Status value={row.resolved_at ? 'Recovered' : row.approved_at ? 'Approved' : 'Draft'} /></td>
          <td><Status value={row.notification_status.toUpperCase()} />
            <small>{row.notification_attempts} attempts{row.delivered_at ? ' · ' + formatDate(row.delivered_at) : ''}</small>
          </td>
          <td>{!row.resolved_at && !row.approved_at && <button className="secondary compact" disabled={busy}
            onClick={() => void change('/replenishment/recommendations/' + row.id + '/approve',
              { method: 'POST' }, 'Recommendation approved.')}>Approve</button>}</td>
        </tr>} />
    </section>
  </div>
}
