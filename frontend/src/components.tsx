import { useState, type ReactNode } from 'react'
import { ArrowLeft, ArrowRight, CircleAlert, CircleCheck, Inbox, Info } from 'lucide-react'

export const formatNumber = (value: number) => value.toLocaleString()
export const formatDate = (value: string) => new Date(value).toLocaleString(undefined, {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
})
export const signed = (value: number) => (value > 0 ? '+' : '') + formatNumber(value)
export const label = (value: string) => value.charAt(0) + value.slice(1).toLowerCase()

export function Status({ value }: { value: string }) {
  return <span className={'status status-' + value.toLowerCase()}>{label(value)}</span>
}

export function Notice({ children, error = false, tone = 'info' }: {
  children: ReactNode; error?: boolean; tone?: 'info' | 'success' | 'warning'
}) {
  const Icon = error || tone === 'warning' ? CircleAlert : tone === 'success' ? CircleCheck : Info
  return <div role={error ? 'alert' : 'status'} className={'notice ' + (error ? 'error' : tone)}>
    <Icon size={17} aria-hidden="true" />{children}
  </div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><Inbox size={24} aria-hidden="true" /><p>{children}</p></div>
}

export function Table<T>({ columns, rows, render, empty }: {
  columns: string[]; rows: T[]; render: (row: T) => ReactNode; empty: string
}) {
  const pageSize = 10
  const [page, setPage] = useState(0)
  const currentPage = Math.min(page, Math.max(0, Math.ceil(rows.length / pageSize) - 1))
  const start = currentPage * pageSize
  if (!rows.length) return <div className="surface"><Empty>{empty}</Empty></div>
  return <div className="surface">
    <div className="table-scroll"><table>
      <thead><tr>{columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
      <tbody>{rows.slice(start, start + pageSize).map(render)}</tbody>
    </table></div>
    {rows.length > pageSize && <div className="pagination">
      <span>{start + 1}–{Math.min(start + pageSize, rows.length)} of {rows.length}</span>
      <button className="icon-button" aria-label="Previous page" disabled={!currentPage}
        onClick={() => setPage(currentPage - 1)}><ArrowLeft size={16} /></button>
      <button className="icon-button" aria-label="Next page" disabled={start + pageSize >= rows.length}
        onClick={() => setPage(currentPage + 1)}><ArrowRight size={16} /></button>
    </div>}
  </div>
}
