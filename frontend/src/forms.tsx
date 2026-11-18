import { useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { post, request, type Account, type Order, type Product, type Warehouse } from './api'
import { Notice } from './components'

type Done = (message: string) => void

function Form({ children, action, submit, onCancel }: {
  children: ReactNode; action: (form: FormData) => Promise<void>; submit: string; onCancel?: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const fields = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try { await action(fields) } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to complete the request.')
    } finally { setBusy(false) }
  }
  return <form onSubmit={send}>
    {error && <Notice error>{error}</Notice>}
    <fieldset disabled={busy} className="form-grid">
      {children}
      <div className="form-actions">
        {onCancel && <button className="secondary" type="button" onClick={onCancel}>Cancel</button>}
        <button className="primary" type="submit">{busy ? 'Working…' : submit}</button>
      </div>
    </fieldset>
  </form>
}

const field = (data: FormData, name: string) => String(data.get(name) ?? '')

export function LoginForm({ signedIn, close }: { signedIn: (account: Account) => void; close: () => void }) {
  return <Form submit="Sign in" onCancel={close} action={async data => {
    signedIn(await request<Account>('/auth/login', undefined, post({
      username: field(data, 'username'), password: field(data, 'password'),
    })))
  }}>
    <label>Username<input name="username" autoComplete="username" minLength={3} maxLength={64} required /></label>
    <label>Password<input name="password" type="password" autoComplete="current-password" maxLength={128} required /></label>
  </Form>
}

export function ProductForm({ product, token, done, close }: {
  product?: Product; token: string; done: Done; close: () => void
}) {
  return <Form submit={product ? 'Save changes' : 'Add product'} onCancel={close} action={async data => {
    await request<Product>(product ? '/products/' + product.id : '/products', token, post({
      sku: field(data, 'sku'), name: field(data, 'name'), price: field(data, 'price'),
      description: field(data, 'description').trim() || null,
    }, product ? 'PATCH' : 'POST'))
    done(product ? 'Product updated.' : 'Product added.')
  }}>
    <label>SKU<input name="sku" defaultValue={product?.sku} maxLength={64} required /></label>
    <label>Product name<input name="name" defaultValue={product?.name} maxLength={200} required /></label>
    <label>Unit price<input name="price" type="number" min="0" max="9999999999.99" step="0.01"
      defaultValue={product?.price} required /></label>
    <label>Description<textarea name="description" defaultValue={product?.description ?? ''} maxLength={2000} /></label>
  </Form>
}

function ProductSelect({ products, name, caption }: { products: Product[]; name: string; caption: string }) {
  const id = useId()
  return <div className="field">
    <label htmlFor={id}>{caption}</label>
    <select id={id} name={name} required defaultValue="">
      <option value="" disabled>Select a product</option>
      {products.map(product => <option key={product.id} value={product.id}>{product.name} ({product.sku})</option>)}
    </select>
  </div>
}

function WarehouseSelect({ warehouses }: { warehouses: Warehouse[] }) {
  const id = useId()
  return <div className="field">
    <label htmlFor={id}>Warehouse</label>
    <select id={id} name="warehouse" required defaultValue="">
      <option value="" disabled>Select a warehouse</option>
      {warehouses.map(warehouse => <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>)}
    </select>
  </div>
}

type StockFormProps = {
  products: Product[]; warehouses: Warehouse[]; token: string; done: Done
}

export function ReceiptForm({ products, warehouses, token, done, close }: StockFormProps & { close: () => void }) {
  return <Form submit="Record receipt" onCancel={close} action={async data => {
    await request('/inventory/receipts', token, post({
      product_id: Number(data.get('product')), warehouse_id: Number(data.get('warehouse')),
      quantity: Number(data.get('quantity')),
    }))
    done('Stock receipt recorded.')
  }}>
    <ProductSelect products={products} name="product" caption="Product" />
    <WarehouseSelect warehouses={warehouses} />
    <label>Quantity<input name="quantity" type="number" min="1" max={Number.MAX_SAFE_INTEGER} step="1" required /></label>
  </Form>
}

export function OrderForm({ products, warehouses, token, done }: StockFormProps) {
  const [lines, setLines] = useState([0])
  const nextLine = useRef(1)
  const attempt = useRef<{ body: string; key: string } | null>(null)
  return <Form submit="Reserve stock" action={async data => {
    const items = lines.map(line => ({
      product_id: Number(data.get('product-' + line)), quantity: Number(data.get('quantity-' + line)),
    }))
    if (new Set(items.map(item => item.product_id)).size !== items.length) {
      throw new Error('Choose each product only once.')
    }
    const body = JSON.stringify({
      customer_reference: field(data, 'customer').trim(),
      warehouse_id: Number(data.get('warehouse')),
      items: items.sort((left, right) => left.product_id - right.product_id),
    })
    if (attempt.current?.body !== body) attempt.current = { body, key: crypto.randomUUID() }
    const order = await request<Order>('/orders', token, {
      method: 'POST', body, headers: { 'Idempotency-Key': attempt.current.key },
    })
    done('Order #' + order.id + ' reserved.')
  }}>
    <label>Customer reference<input name="customer" required maxLength={200} /></label>
    <WarehouseSelect warehouses={warehouses} />
    <div className="order-lines">
      {lines.map((line, index) => <div className="order-line" key={line}>
        <ProductSelect products={products} name={'product-' + line} caption={'Product ' + (index + 1)} />
        <label>Quantity {index + 1}<input name={'quantity-' + line} type="number" min="1"
          max={Number.MAX_SAFE_INTEGER} step="1" defaultValue="1" required /></label>
        <button type="button" className="icon-button" aria-label={'Remove product ' + (index + 1)}
          disabled={lines.length === 1} onClick={() => setLines(lines.filter(item => item !== line))}><Trash2 size={16} /></button>
      </div>)}
    </div>
    <button type="button" className="secondary fit" disabled={lines.length >= Math.min(100, products.length)}
      onClick={() => setLines([...lines, nextLine.current++])}><Plus size={16} /> Add line</button>
  </Form>
}
