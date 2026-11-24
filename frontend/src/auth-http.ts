/** API-only bearer transport; never sends credentials to document/model servers. */
let tokenProvider: (() => Promise<string | null>) | null = null
let onUnauthorized = () => {}
export function configureAuthTransport(provider: () => Promise<string | null>, expired: () => void) {
  tokenProvider = provider
  onUnauthorized = expired
}
export async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const base = typeof location === 'undefined' ? 'http://127.0.0.1:9174' : location.origin
  const url = new URL(input instanceof Request ? input.url : String(input), base)
  const protectedApi = url.origin === base && url.pathname.startsWith('/api/')
  if (!protectedApi || !tokenProvider) return fetch(input, init)
  const token = await tokenProvider()
  if (!token) { onUnauthorized(); throw new Error('登录已过期，请重新登录') }
  const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined))
  headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(input, {...init, headers, redirect: 'error'})
  if (response.status === 401) onUnauthorized()
  return response
}
export async function downloadAuthenticated(url: string, filename = '') {
  const response = await authFetch(url)
  if (!response.ok) throw new Error(`下载失败 (${response.status})`)
  const blobUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = blobUrl; link.download = filename || '合同文件.docx'
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
}
