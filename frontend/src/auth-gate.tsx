import {createContext, useContext, useEffect, useState, type ReactNode} from 'react'
import {initializeAuth, signIn, signOut, type Identity} from './auth'
import {OidcConfigError} from './oidc-transport'
import {downloadAuthenticated} from './auth-http'
import './auth.css'
const IdentityContext = createContext<Identity | null>(null)
export const useIdentity = () => useContext(IdentityContext)
export function AccountMenu() {
  const user = useIdentity()
  const [error, setError] = useState('')
  if (!user) return null
  return <div className="account-menu"><span title={user.department_name}>{user.name || user.preferred_username || '已登录'}</span><button onClick={() => void signOut().catch(() => setError('退出未完成，请重试'))}>退出登录</button>{error && <span role="alert">{error}</span>}</div>
}
export function AuthGate({children}: {children: ReactNode}) {
  const [user, setUser] = useState<Identity | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let disposed = false
    void initializeAuth().then(async value => {
      if (disposed) return
      if (value) {setUser(value); setLoading(false)}
      else await signIn()
    }).catch(reason => {
      if (disposed) return
      setError(reason instanceof OidcConfigError?reason.message:'登录验证未完成，请重新登录或检查公司网络连接。')
      setLoading(false)
      if (location.pathname === '/callback') history.replaceState(null, '', '/')
    })
    const expired = () => {setUser(null); setError('登录已过期，请重新登录。')}
    window.addEventListener('rixin-auth-expired', expired)
    return () => {disposed = true; window.removeEventListener('rixin-auth-expired', expired)}
  }, [])
  useEffect(() => {
    // Native anchors cannot attach Authorization; keep existing download UI intact.
    const download = (event: MouseEvent) => {
      const anchor = (event.target as Element)?.closest?.('a[href]') as HTMLAnchorElement | null
      if (!anchor) return
      const url = new URL(anchor.href, location.href)
      if (url.origin !== location.origin || !url.pathname.startsWith('/api/') || !url.pathname.endsWith('/file')) return
      event.preventDefault()
      void downloadAuthenticated(url.href, anchor.download).catch(e => setError(String(e)))
    }
    document.addEventListener('click', download)
    return () => document.removeEventListener('click', download)
  }, [])
  if (loading) return <main className="auth-screen" role="status">正在连接公司统一身份认证…</main>
  if (!user || (user.enabled && !user.roles.length)) return <main className="auth-screen"><section><img src="/favicon.png" alt="国能日新"/><h1>合同智能审查</h1><p>{user ? '当前账号尚未开通本系统权限，请联系统一身份认证管理员。' : '使用公司账号登录后，开始合同审查。'}</p>{error && <p role="alert">{error}</p>}<button onClick={() => void (user ? signOut() : signIn()).catch(() => setError('认证服务暂不可用，请检查公司网络后重试。'))}>{user ? '退出并切换账号' : '公司统一身份认证登录'}</button></section></main>
  return <IdentityContext.Provider value={user}>{children}{error && <div className="auth-notice" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}</IdentityContext.Provider>
}
