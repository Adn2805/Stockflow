export type Role = 'admin' | 'staff' | 'guest'
export type Account = { username: string; role: Role; access_token: string }
export type Product = { id: number; sku: string; name: string; description: string | null; price: string }
export type Warehouse = { id: number; name: string; location: string }
export type Balance = { product_id: number; warehouse_id: number; on_hand: number; reserved: number; available: number }
export type OrderItem = { product_id: number; quantity: number; unit_price_snapshot: string }
export type Order = {
  id: number; customer_reference: string; warehouse_id: number
  status: 'RESERVED' | 'CANCELLED' | 'FULFILLED'; items: OrderItem[]; created_at: string
}
export type Movement = {
  id: number; product_id: number; warehouse_id: number; order_id: number | null
  movement_type: string; delta_on_hand: number; delta_reserved: number; created_at: string
}
export type Discrepancy = {
  product_id: number; warehouse_id: number; actual_on_hand: number | null; actual_reserved: number | null
  expected_on_hand: number; expected_reserved: number
}

export const publicDemo = import.meta.env.VITE_PUBLIC_DEMO === 'true'
const base = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function request<T>(path: string, token?: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (token) headers.set('Authorization', 'Bearer ' + token)
  if (options.body) headers.set('Content-Type', 'application/json')
  const deadline = AbortSignal.timeout(publicDemo ? 75_000 : 15_000)
  const signal = options.signal ? AbortSignal.any([options.signal, deadline]) : deadline
  let response: Response
  try {
    response = await fetch(base + path, { ...options, headers, signal })
  } catch (error) {
    if (publicDemo && !options.signal?.aborted) {
      throw new Error('The demo API is unavailable or still waking up. Use Refresh data to try again.')
    }
    throw error
  }
  if (publicDemo && (response.status >= 500 || !response.headers.get('content-type')?.includes('application/json'))) {
    throw new Error('The demo API is unavailable or still waking up. Use Refresh data to try again.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const issue = body?.issues?.[0]
    const detail = issue ? issue.location.slice(1).join('.') + ' · ' + issue.message : body?.detail
    throw new ApiError(response.status, typeof detail === 'string' ? detail : 'The API request failed.')
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export async function listAll<T>(path: string, token: string | undefined, signal: AbortSignal) {
  const pageSize = 100
  const rows: T[] = []
  for (let offset = 0; ; offset += pageSize) {
    const page = await request<T[]>(path + '?limit=' + pageSize + '&offset=' + offset, token, { signal })
    rows.push(...page)
    if (page.length < pageSize) return rows
  }
}

export function post(body: object, method = 'POST'): RequestInit {
  return { method, body: JSON.stringify(body) }
}
