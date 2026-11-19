import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  ArrowDownToLine, ArrowRight, ArrowUpRight, Box, Boxes, ClipboardCheck, ClipboardList,
  Bell, History, LayoutDashboard, LogIn, LogOut, Package, Plus, RefreshCw, ShoppingCart, Warehouse as WarehouseIcon, X,
} from 'lucide-react'
import {
  ApiError, listAll, publicDemo, request, staticDemo, type Account, type Balance, type Discrepancy, type Movement,
  type Order, type Product, type Warehouse,
} from './api'
import { Empty, formatDate, formatNumber as n, label, Notice, signed, Status, Table } from './components'
import { Replenishment } from './Replenishment'
import { LoginForm, OrderForm, ProductForm, ReceiptForm } from './forms'

const navigation = [
  { name: 'Overview', icon: LayoutDashboard },
  { name: 'Products', icon: Package },
  { name: 'Inventory', icon: Boxes },
  { name: 'Create order', icon: ShoppingCart },
  { name: 'Orders', icon: ClipboardList },
  { name: 'Stock movements', icon: History },
  { name: 'Reconciliation', icon: ClipboardCheck },
  { name: 'Replenishment', icon: Bell },
] as const

type View = typeof navigation[number]['name']
type Snapshot = {
  products: Product[]; warehouses: Warehouse[]; balances: Balance[]; orders: Order[]
  movements: Movement[]; discrepancies: Discrepancy[]
}
type Editor = { kind: 'sign-in' | 'receipt' } | { kind: 'product'; product?: Product }

const descriptions: Record<View, string> = {
  Overview: 'Monitor stock levels, order activity, and inventory discrepancies.',
  Products: 'Browse and manage your warehouse catalog.',
  Inventory: 'Track on-hand, reserved, and available units by warehouse.',
  'Create order': 'Reserve stock from a single warehouse.',
  Orders: 'Review reservations and fulfill or cancel orders.',
  'Stock movements': 'Inspect receipts, reservations, cancellations, and fulfillment.',
  Reconciliation: 'Compare current balances with stock movement totals.',
  Replenishment: 'Configure stock thresholds, review drafts, and track Telegram delivery.',
}

function Modal({ title, close, children }: { title: string; close: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { ref.current?.showModal() }, [])
  return <dialog ref={ref} aria-labelledby="dialog-title" onCancel={event => { event.preventDefault(); close() }}>
    <div className="dialog-header"><h2 id="dialog-title">{title}</h2>
      <button className="icon-button" type="button" aria-label="Close dialog" onClick={close}><X size={20} /></button>
    </div>
    {children}
  </dialog>
}

export function App() {
  const [account, setAccount] = useState<Account>()
  const [login, setLogin] = useState(false)
  const [sessionNotice, setSessionNotice] = useState('')
  const [signingOut, setSigningOut] = useState(false)

  async function signOut() {
    if (!account || signingOut) return
    setSigningOut(true)
    try {
      await request('/auth/logout', account.access_token, { method: 'POST' })
      setAccount(undefined)
      setSessionNotice('Signed out.')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setAccount(undefined)
      setSessionNotice(error instanceof Error ? error.message : 'Unable to sign out.')
    } finally { setSigningOut(false) }
  }

  const operational = account?.role === 'admin' || account?.role === 'staff'
  return <Dashboard key={account?.access_token ?? 'public'} account={account} operational={operational}
    login={login} openLogin={() => setLogin(true)} closeLogin={() => setLogin(false)}
    signOut={signOut} signingOut={signingOut} sessionNotice={sessionNotice}
    signedIn={user => { setAccount(user); setLogin(false); setSessionNotice('') }}
    expire={() => { setAccount(undefined); setSessionNotice('Your session expired. Sign in to continue.') }} />
}

function Dashboard({ account, operational, login, openLogin, closeLogin, signedIn, signOut, signingOut,
  sessionNotice, expire }: {
  account?: Account; operational: boolean; login: boolean; openLogin: () => void; closeLogin: () => void
  signedIn: (account: Account) => void; signOut: () => void; signingOut: boolean
  sessionNotice: string; expire: () => void
}) {
  const [view, setView] = useState<View>('Overview')
  const [editor, setEditor] = useState<Editor>()
  const [snapshot, setSnapshot] = useState<Snapshot>()
  const [version, setVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState<number>()
  const token = account?.access_token
  const auditVisible = operational || publicDemo
  const admin = account?.role === 'admin'
  const refresh = () => setVersion(value => value + 1)
  const move = (target: View) => { setView(target); setNotice(''); setError('') }
  const done = (message: string) => { setEditor(undefined); setNotice(message); refresh() }
  const expireRef = useRef(expire)
  useEffect(() => { expireRef.current = expire }, [expire])

  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    async function load() {
      setLoading(true)
      setError('')
      try {
        const [products, warehouses, balances, orders, movements, discrepancies] = await Promise.all([
          listAll<Product>('/products', token, signal),
          listAll<Warehouse>('/warehouses', token, signal),
          listAll<Balance>('/inventory', token, signal),
          auditVisible ? listAll<Order>('/orders', token, signal) : [],
          auditVisible ? listAll<Movement>('/reports/stock-movements', token, signal) : [],
          auditVisible ? listAll<Discrepancy>('/reports/reconciliation', token, signal) : [],
        ])
        if (!signal.aborted) setSnapshot({ products, warehouses, balances, orders, movements, discrepancies })
      } catch (error) {
        if (signal.aborted) return
        if (token && error instanceof ApiError && error.status === 401) expireRef.current()
        else setError(error instanceof Error ? error.message : 'Could not load the dashboard.')
      } finally { if (!signal.aborted) setLoading(false) }
    }
    void load()
    return () => controller.abort()
  }, [token, auditVisible, version])

  async function transition(order: Order, action: 'fulfill' | 'cancel') {
    setBusy(order.id)
    setError('')
    setNotice('')
    try {
      await request('/orders/' + order.id + '/' + action, token, { method: 'POST' })
      done('Order #' + order.id + (action === 'fulfill' ? ' fulfilled.' : ' cancelled.'))
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) expire()
      else setError(error instanceof Error ? error.message : 'Unable to update order.')
    } finally { setBusy(undefined) }
  }

  const links = operational ? navigation.filter(link => admin || link.name !== 'Replenishment') : publicDemo
    ? navigation.filter(link => !['Create order', 'Replenishment'].includes(link.name)) : navigation.slice(0, 3)
  return <div className="layout">
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon"><Boxes size={25} /></div><span>StockFlow</span></div>
      <nav aria-label="Dashboard">
        {links.map(({ name, icon: Icon }) => <button type="button" key={name}
          aria-current={view === name ? 'page' : undefined} onClick={() => move(name)}>
          <Icon size={18} /><span>{name}</span>
        </button>)}
      </nav>
      <div className="sidebar-bottom"><WarehouseIcon size={18} /><span>Warehouse workspace</span></div>
    </aside>
    <main>
      <header className="topbar">
        <div className="breadcrumb"><span>Workspace</span><b>/</b>{view}</div>
        <div className="account">
          <span className="account-name">{account?.username ?? (publicDemo ? staticDemo ? 'Static demo' : 'Read-only demo' : 'Guest view')}</span>
          {account ? <>
            <Status value={account.role} />
            <button className="icon-button" type="button" aria-label="Sign out" title="Sign out"
              disabled={signingOut} onClick={signOut}><LogOut size={17} /></button>
          </> : !publicDemo && <button type="button" className="secondary" onClick={openLogin}><LogIn size={16} /> Sign in</button>}
        </div>
      </header>
      <div className="content">
        <div className="page-heading">
          <div><h1>{view === 'Overview' ? 'Warehouse overview' : view}</h1><p>{descriptions[view]}</p></div>
          <div className="page-actions">
            {!staticDemo && <button type="button" className="icon-button outline" aria-label="Refresh data" title="Refresh data"
              disabled={loading} onClick={refresh}><RefreshCw size={17} /></button>}
            {view === 'Overview' && operational && <button className="primary" onClick={() => move('Create order')}><Plus size={17} /> New order</button>}
            {view === 'Products' && admin && <button className="primary" onClick={() => setEditor({ kind: 'product' })}><Plus size={17} /> New product</button>}
            {view === 'Inventory' && operational && <button className="primary" onClick={() => setEditor({ kind: 'receipt' })}><ArrowDownToLine size={17} /> Receive stock</button>}
            {view === 'Orders' && operational && <button className="primary" onClick={() => move('Create order')}><Plus size={17} /> New order</button>}
          </div>
        </div>
        {publicDemo && view === 'Overview' && <Notice>{staticDemo ? 'Synthetic snapshot. Balances and order history are fixed for this demo.' : 'Synthetic warehouse data. Explore stock, order history, and reconciliation.'}</Notice>}
        {(notice || sessionNotice) && <Notice>{notice || sessionNotice}</Notice>}
        {error && <Notice error>{error}</Notice>}
        {loading && <div className="loading" role="status"><span /> {publicDemo && !staticDemo ? 'Loading demo data. A cold start can take about a minute.' : 'Loading warehouse data…'}</div>}
        {snapshot && view === 'Replenishment' && admin && token &&
          <Replenishment products={snapshot.products} warehouses={snapshot.warehouses} token={token} version={version} />}
        {snapshot && view !== 'Replenishment' && <Screens data={snapshot} view={view} move={move} admin={admin} operational={operational}
          token={token} busy={busy} transition={transition}
          editProduct={product => setEditor({ kind: 'product', product })}
          orderDone={message => { move('Orders'); done(message) }} />}
      </div>
    </main>
    {login && <Modal title="Sign in to StockFlow" close={closeLogin}><LoginForm signedIn={signedIn} close={closeLogin} /></Modal>}
    {editor?.kind === 'product' && token && <Modal title={editor.product ? 'Edit product' : 'New product'} close={() => setEditor(undefined)}>
      <ProductForm product={editor.product} token={token} done={done} close={() => setEditor(undefined)} />
    </Modal>}
    {editor?.kind === 'receipt' && snapshot && token && <Modal title="Receive stock" close={() => setEditor(undefined)}>
      <ReceiptForm products={snapshot.products} warehouses={snapshot.warehouses} token={token}
        done={done} close={() => setEditor(undefined)} />
    </Modal>}
  </div>
}

function Screens({ data, view, move, admin, operational, token, busy, transition, editProduct, orderDone }: {
  data: Snapshot; view: View; move: (view: View) => void; admin: boolean; operational: boolean; token?: string
  busy?: number; transition: (order: Order, action: 'fulfill' | 'cancel') => void
  editProduct: (product: Product) => void; orderDone: (message: string) => void
}) {
  const products = new Map(data.products.map(product => [product.id, product]))
  const warehouses = new Map(data.warehouses.map(warehouse => [warehouse.id, warehouse]))
  const productName = (id: number) => products.get(id)?.name ?? 'Product #' + id
  const warehouseName = (id: number) => warehouses.get(id)?.name ?? 'Warehouse #' + id

  switch (view) {
    case 'Overview':
      return <Overview data={data} operational={operational || publicDemo} move={move} productName={productName} warehouseName={warehouseName} />
    case 'Products':
      return <Table columns={['Product', 'SKU', 'Unit price', ...(admin ? ['Actions'] : [])]} rows={data.products}
        empty="No products yet." render={product => <tr key={product.id}>
          <td><strong>{product.name}</strong>{product.description && <small>{product.description}</small>}</td>
          <td className="mono">{product.sku}</td><td>{product.price}</td>
          {admin && <td><button className="secondary compact" onClick={() => editProduct(product)}>Edit</button></td>}
        </tr>} />
    case 'Inventory':
      return <Table columns={['Product', 'Warehouse', 'On hand', 'Reserved', 'Available']} rows={data.balances}
        empty="No stock balances yet." render={balance => <tr key={balance.product_id + ':' + balance.warehouse_id}>
          <td><strong>{productName(balance.product_id)}</strong></td><td>{warehouseName(balance.warehouse_id)}</td>
          <td>{n(balance.on_hand)}</td><td>{n(balance.reserved)}</td><td><strong>{n(balance.available)}</strong></td>
        </tr>} />
    case 'Create order':
      return token && <section className="surface form-panel">
        <h2>Order details</h2>
        {data.products.length && data.warehouses.length
          ? <OrderForm products={data.products} warehouses={data.warehouses} token={token} done={orderDone} />
          : <Empty>Set up a warehouse and product before creating an order.</Empty>}
      </section>
    case 'Orders':
      return <Table columns={['Order', 'Warehouse', 'Products', 'Status', ...(operational ? ['Actions'] : [])]} rows={[...data.orders].reverse()}
        empty="No orders yet." render={order => <tr key={order.id}>
          <td><strong>#{order.id} · {order.customer_reference}</strong><small>{formatDate(order.created_at)}</small></td>
          <td>{warehouseName(order.warehouse_id)}</td>
          <td>{order.items.map(item => <small key={item.product_id}>{n(item.quantity)} × {productName(item.product_id)} · {item.unit_price_snapshot} each</small>)}</td>
          <td><Status value={order.status} /></td>
          {operational && <td>{order.status === 'RESERVED' && <div className="row-actions">
            <button className="secondary compact" disabled={busy !== undefined} onClick={() => transition(order, 'fulfill')}>Fulfill</button>
            <button className="secondary compact danger" disabled={busy !== undefined} onClick={() => transition(order, 'cancel')}>Cancel</button>
          </div>}</td>}
        </tr>} />
    case 'Stock movements':
      return <Table columns={['Movement', 'Product', 'Warehouse', 'On-hand change', 'Reserved change', 'Order']}
        rows={data.movements} empty="No stock movements yet." render={movement => <tr key={movement.id}>
          <td><Status value={movement.movement_type} /><small>{formatDate(movement.created_at)}</small></td>
          <td>{productName(movement.product_id)}</td><td>{warehouseName(movement.warehouse_id)}</td>
          <td>{signed(movement.delta_on_hand)}</td><td>{signed(movement.delta_reserved)}</td>
          <td>{movement.order_id ? '#' + movement.order_id : '—'}</td>
        </tr>} />
    case 'Reconciliation':
      return <>
        <Notice>{data.discrepancies.length ? n(data.discrepancies.length) + ' stock discrepancies found.'
          : 'All inventory balances match the ledger.'}</Notice>
        <Table columns={['Product', 'Warehouse', 'Actual on hand', 'Expected on hand', 'Actual reserved', 'Expected reserved']}
          rows={data.discrepancies} empty="No discrepancies found." render={row => <tr key={row.product_id + ':' + row.warehouse_id}>
            <td>{productName(row.product_id)}</td><td>{warehouseName(row.warehouse_id)}</td>
            <td>{row.actual_on_hand === null ? 'Missing' : n(row.actual_on_hand)}</td><td>{n(row.expected_on_hand)}</td>
            <td>{row.actual_reserved === null ? 'Missing' : n(row.actual_reserved)}</td><td>{n(row.expected_reserved)}</td>
          </tr>} />
      </>
  }
}

function Overview({ data, operational, move, productName, warehouseName }: {
  data: Snapshot; operational: boolean; move: (view: View) => void
  productName: (id: number) => string; warehouseName: (id: number) => string
}) {
  const total = data.balances.reduce((sum, row) => sum + row.on_hand, 0)
  const reserved = data.balances.reduce((sum, row) => sum + row.reserved, 0)
  const lowStock = data.balances.filter(row => row.available <= 5).sort((a, b) => a.available - b.available)
  const cards = [
    { label: 'Total products', value: data.products.length, icon: Package, tone: 'green', to: 'Products' },
    { label: 'Available units', value: total - reserved, icon: Boxes, tone: 'mint', to: 'Inventory' },
    { label: 'Reserved units', value: reserved, icon: Box, tone: 'amber', to: 'Inventory' },
    { label: operational ? 'Open orders' : 'Warehouses',
      value: operational ? data.orders.filter(order => order.status === 'RESERVED').length : data.warehouses.length,
      icon: operational ? ClipboardList : WarehouseIcon, tone: 'blue', to: operational ? 'Orders' : 'Inventory' },
  ] as const
  return <>
    <div className="metrics">
      {cards.map(({ label, value, icon: Icon, tone, to }) => <button className="metric surface" key={label} onClick={() => move(to)}>
        <span className={'metric-icon ' + tone}><Icon size={19} /></span><ArrowUpRight className="metric-link" size={16} />
        <strong>{n(value)}</strong><span className="metric-label">{label}</span>
      </button>)}
    </div>
    <div className="overview-grid">
      <section className="surface overview-panel">
        <div className="panel-heading"><div><h2>Stock allocation</h2><p>Available and reserved units across warehouses</p></div>
          <button className="text-button" onClick={() => move('Inventory')}>Inventory <ArrowRight size={15} /></button></div>
        <div className="allocation-total"><strong>{n(total)}</strong><span>units on hand</span></div>
        <div className="stock-bar" role="img" aria-label={n(total - reserved) + ' available and ' + n(reserved) + ' reserved'}>
          {total > 0 && <><span style={{ width: ((total - reserved) / total * 100) + '%' }} />
            <span style={{ width: (reserved / total * 100) + '%' }} /></>}
        </div>
        <div className="legend"><span><i /> Available <strong>{n(total - reserved)}</strong></span>
          <span><i /> Reserved <strong>{n(reserved)}</strong></span></div>
      </section>
      <section className="surface overview-panel">
        <div className="panel-heading"><div><h2>Low stock</h2><p>Balances with 5 or fewer available units</p></div><span className="count">{n(lowStock.length)}</span></div>
        {lowStock.length ? <ul className="activity">{lowStock.slice(0, 4).map(row => <li key={row.product_id + ':' + row.warehouse_id}>
          <div><strong>{productName(row.product_id)}</strong><small>{warehouseName(row.warehouse_id)}</small></div>
          <span className="status status-reserved">{n(row.available)} left</span>
        </li>)}</ul> : <Empty>No low-stock balances.</Empty>}
      </section>
      {operational && <>
        <section className="surface overview-panel">
          <div className="panel-heading"><h2>Recent stock movements</h2>
            <button className="text-button" onClick={() => move('Stock movements')}>View ledger <ArrowRight size={15} /></button></div>
          {data.movements.length ? <ul className="activity">{data.movements.slice(0, 5).map(item => <li key={item.id}>
            <div><strong>{productName(item.product_id)}</strong><small>{label(item.movement_type)} · {formatDate(item.created_at)}</small></div>
            <span>{signed(item.delta_on_hand || item.delta_reserved)}</span>
          </li>)}</ul> : <Empty>No stock movements yet.</Empty>}
        </section>
        <section className="surface overview-panel">
          <div className="panel-heading"><h2>Order and stock checks</h2></div>
          <ul className="activity">
            <li><span>Fulfilled orders</span><strong>{n(data.orders.filter(order => order.status === 'FULFILLED').length)}</strong></li>
            <li><span>Cancelled orders</span><strong>{n(data.orders.filter(order => order.status === 'CANCELLED').length)}</strong></li>
            <li><button className="text-button" onClick={() => move('Reconciliation')}>Inventory discrepancies <ArrowRight size={15} /></button><strong>{n(data.discrepancies.length)}</strong></li>
          </ul>
        </section>
      </>}
    </div>
  </>
}
