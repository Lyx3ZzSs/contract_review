/** API-only bearer transport; never sends credentials to document/model servers. */
let tokenProvider: ((rejected?: string) => Promise<string | null>) | null = null
let onUnauthorized = () => {}
export function configureAuthTransport(provider: (rejected?: string) => Promise<string | null>, expired: () => void) {
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
  const send = (accessToken: string) => {
    headers.set('Authorization', `Bearer ${accessToken}`)
    return fetch(input, {...init, headers, redirect: 'error'})
  }
  const response = await send(token)
  if (response.status !== 401) return response
  const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined)
  signal?.throwIfAborted()
  const replacement = await tokenProvider(token)
  signal?.throwIfAborted()
  if (!replacement) { onUnauthorized(); return response }
  const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') {
    throw new Error('此次操作未通过身份验证，请重新提交。')
  }
  // A second rejection is an API error. A successful token renewal is not
  // evidence that the user has lost their company login.
  return send(replacement)
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
