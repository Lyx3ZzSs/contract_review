import {UserManager, WebStorageStateStore} from 'oidc-client-ts'
import {developmentIssuer, validateOidcUrl, validateDiscovery} from './oidc-transport'
import {createAccessTokenProvider} from './auth-session'
import {configureAuthTransport, authFetch} from './auth-http'
export interface Identity {
  enabled: boolean; sub: string; name?: string; preferred_username?: string
  email?: string; department_code?: string; department_name?: string; roles: string[]
}
async function createManager(){
  const authority=(import.meta.env.VITE_OIDC_ISSUER || developmentIssuer).replace(/\/+$/,'')
  const local=location.origin==='http://127.0.0.1:9174'
  const devOrigin=local&&authority===developmentIssuer?new URL(developmentIssuer).origin:undefined
  const redirect_uri=import.meta.env.VITE_OIDC_REDIRECT_URI || location.origin+'/callback'
  const post_logout_redirect_uri=import.meta.env.VITE_OIDC_LOGOUT_URI || location.origin+'/'
  validateOidcUrl(location.origin,local?location.origin:undefined)
  validateOidcUrl(authority,devOrigin)
  for(const uri of [redirect_uri,post_logout_redirect_uri])validateOidcUrl(uri,local?location.origin:undefined)
  const response=await fetch(authority+'/.well-known/openid-configuration',{redirect:'error',credentials:'omit'})
  if(!response.ok)throw new Error('统一认证发现服务暂不可用')
  const metadata=await response.json()
  validateDiscovery(metadata,authority,devOrigin)
  const manager=new UserManager({
    authority,metadata,redirect_uri,post_logout_redirect_uri,
    client_id: import.meta.env.VITE_OIDC_CLIENT_ID || 'rixin-contract-review-web',
    response_type: 'code', scope: 'openid profile email',
    disablePKCE:false, automaticSilentRenew:false, loadUserInfo:false,
    userStore:new WebStorageStateStore({store:window.sessionStorage}),
    stateStore:new WebStorageStateStore({store:window.sessionStorage}),
  })
  return manager
}
let initialized:Promise<UserManager>|undefined
function getManager(){
  return initialized??=createManager().catch(error=>{initialized=undefined;throw error})
}
const expired = () => { window.dispatchEvent(new Event('rixin-auth-expired')) }
const accessToken = createAccessTokenProvider(
  async () => (await getManager()).getUser(),
  async () => (await getManager()).signinSilent(),
)
configureAuthTransport(accessToken, expired)
export async function identity(): Promise<Identity | null> {
  if (!await (await getManager()).getUser()) return null
  const response = await authFetch('/api/v1/auth/me')
  if (!response.ok) throw new Error('无法验证当前账号，请重试')
  return response.json()
}
let initialization: Promise<Identity | null> | null = null
export function initializeAuth() {
  initialization ??= (async () => {
    if (location.pathname === '/callback') {
      const user = await (await getManager()).signinRedirectCallback()
      const state = user.state as {returnTo?: string} | undefined
      history.replaceState(null, '', '/' + (state?.returnTo?.startsWith('#/') ? state.returnTo : '#/'))
    }
    await (await getManager()).clearStaleState()
    return identity()
  })()
  return initialization
}
export async function signIn() {
  return (await getManager()).signinRedirect({state: {returnTo: location.hash.startsWith('#/') ? location.hash : '#/'}})
}
export async function signOut() {
  const manager=await getManager()
  const user = await manager.getUser()
  // Clear tab-local business navigation and tokens even if logout navigation fails.
  await manager.removeUser()
  localStorage.removeItem('rixin:workbench:last-document')
  await manager.signoutRedirect({id_token_hint: user?.id_token})
}
