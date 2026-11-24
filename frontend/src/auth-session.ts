// The identity provider owns the login session. API requests may reject an
// individual access token while its refresh token still works.
interface SessionUser {
  access_token: string
  refresh_token?: string
  expires_at?: number
}

function tokenTiming(user: SessionUser) {
  const now = Date.now() / 1000
  let deadline = user.expires_at ?? Infinity
  let margin = 60
  try {
    // This is a scheduling hint only. The API verifies the JWT independently.
    const encoded = user.access_token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const {exp, iat} = JSON.parse(atob(encoded))
    if (Number.isFinite(exp)) {
      deadline = Math.min(deadline, exp)
      if (Number.isFinite(iat) && exp > iat) margin = Math.min(margin, (exp - iat) / 5)
    }
  } catch { /* Opaque tokens use the expiry supplied by OIDC. */ }
  return {remaining: deadline - now, margin}
}

export function createAccessTokenProvider(
  read: () => Promise<SessionUser | null>,
  renew: () => Promise<SessionUser | null>,
) {
  let refreshing: Promise<SessionUser | null> | undefined
  return async (rejected?: string): Promise<string | null> => {
    const user = await read()
    if (!user) return null
    const {remaining, margin} = tokenTiming(user)
    const denied = user.access_token === rejected
    if (!denied && remaining > margin) return user.access_token
    if (!user.refresh_token) return !denied && remaining > 0 ? user.access_token : null
    refreshing ??= renew().finally(() => { refreshing = undefined })
    try {
      return (await refreshing)?.access_token ?? null
    } catch (cause) {
      const code = (cause as {error?: string} | null)?.error
      if (code === 'invalid_grant' || code === 'login_required' || code === 'interaction_required') return null
      if (!denied && tokenTiming(user).remaining > 0) return user.access_token
      throw new Error('暂时无法连接统一认证，连接恢复后请重试。', {cause})
    }
  }
}
