export class ApiError extends Error {
  status: number
  detail: any
  constructor(status: number, detail: any) {
    const msg =
      detail && typeof detail === 'object'
        ? detail.message || JSON.stringify(detail)
        : String(detail || `请求失败 ${status}`)
    super(msg)
    this.status = status
    this.detail = detail
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let detail: any
    try {
      detail = (await res.json()).detail
    } catch {
      detail = res.statusText
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
