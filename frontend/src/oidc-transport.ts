export const developmentIssuer='http://10.8.6.32:18080/realms/company-dev'
export class OidcConfigError extends Error {}

export function validateOidcUrl(value:string, localOrigin?:string) {
  let url: URL
  try {url=new URL(value)} catch {throw new OidcConfigError('统一认证地址格式无效。')}
  if(!url.username&&!url.password&&(url.protocol==='https:'||(url.protocol==='http:'&&url.origin===localOrigin)))return
  throw new OidcConfigError('统一认证端点和回调地址必须使用 HTTPS。')
}

export function validateDiscovery(metadata:Record<string,unknown>, issuer:string, localOrigin?:string) {
  if(metadata.issuer!==issuer)throw new OidcConfigError('统一认证发现文档的 issuer 与配置不一致。')
  for(const name of ['authorization_endpoint','token_endpoint','jwks_uri','end_session_endpoint']){
    if(typeof metadata[name]!=='string')throw new OidcConfigError(`统一认证缺少 ${name} 配置。`)
  }
  for(const [name,value] of Object.entries(metadata)){
    if(name.endsWith('_endpoint')||name==='jwks_uri')validateOidcUrl(String(value),localOrigin)
  }
}
