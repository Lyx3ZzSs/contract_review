import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
let dir,http,createAccessTokenProvider
const originalFetch=globalThis.fetch
before(async()=>{
 dir=await mkdtemp(join(tmpdir(),'rixin-auth-'))
 await build({entryPoints:['src/auth-http.ts','src/auth-session.ts'],bundle:true,platform:'node',format:'esm',outdir:dir,outExtension:{'.js':'.mjs'}})
 http=await import(pathToFileURL(join(dir,'auth-http.mjs')))
 ;({createAccessTokenProvider}=await import(pathToFileURL(join(dir,'auth-session.mjs'))))
})
after(async()=>{globalThis.fetch=originalFetch;await rm(dir,{recursive:true,force:true})})
test('API requests carry current bearer token and preserve upload/body headers',async()=>{
 let token='first',calls=[]
 http.configureAuthTransport(async()=>token,()=>assert.fail('Unexpected expiry'))
 globalThis.fetch=async(input,init)=>{calls.push({input,init});return new Response('{}')}
 await http.authFetch('/api/v1/contracts',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
 token='refreshed'
 await http.authFetch('/api/v1/contracts')
 assert.equal(calls[0].init.headers.get('Authorization'),'Bearer first')
 assert.equal(calls[0].init.headers.get('Content-Type'),'application/json')
 assert.equal(calls[0].init.body,'{}')
 assert.equal(calls[0].init.redirect,'error')
 assert.equal(calls[1].init.headers.get('Authorization'),'Bearer refreshed')
})
test('bearer is not forwarded to other origins or non-API assets',async()=>{
 let calls=[]
 http.configureAuthTransport(async()=>assert.fail('Must not obtain token'),()=>{})
 globalThis.fetch=async(input,init)=>{calls.push(init);return new Response('')}
 await http.authFetch('http://document-server/api/v1/file')
 await http.authFetch('/favicon.png')
 assert.deepEqual(calls,[undefined,undefined])
})
test('expired login blocks requests and 401 never replays a mutation',async()=>{
 let expired=0,calls=0
 http.configureAuthTransport(async()=>null,()=>expired++)
 globalThis.fetch=async()=>{calls++;return new Response('',{status:401})}
 await assert.rejects(http.authFetch('/api/v1/contracts'),/登录已过期/)
 assert.equal(calls,0);assert.equal(expired,1)
 http.configureAuthTransport(async rejected=>rejected?null:'revoked',()=>expired++)
 assert.equal((await http.authFetch('/api/v1/contracts',{method:'POST'})).status,401)
 assert.equal(calls,1);assert.equal(expired,2)
})

test('OIDC discovery requires TLS outside the registered local setup',async()=>{
 const bundle=await build({entryPoints:['src/oidc-transport.ts'],bundle:true,platform:'node',format:'esm',write:false})
 const {validateDiscovery,developmentIssuer}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'))
 const metadata=issuer=>Object.fromEntries(['issuer','authorization_endpoint','token_endpoint','jwks_uri','end_session_endpoint'].map(k=>[k,k==='issuer'?issuer:issuer+'/'+k]))
 const issuer='https://auth.example/realm'
 validateDiscovery(metadata(issuer),issuer)
 validateDiscovery(metadata(developmentIssuer),developmentIssuer,new URL(developmentIssuer).origin)
 assert.throws(()=>validateDiscovery({...metadata(issuer),jwks_uri:'http://auth.example/keys'},issuer),/HTTPS/)
 assert.throws(()=>validateDiscovery(metadata(developmentIssuer),issuer),/issuer/)
})

test('parallel poll and stream requests share renewal, including a late 401 for the old token',async()=>{
 let user={access_token:'old',refresh_token:'refresh'}, renewals=0
 let release
 const pending=new Promise(resolve=>{release=resolve})
 const token=createAccessTokenProvider(async()=>user,async()=>{
   renewals++
   await pending
   return user={...user,access_token:'new'}
 })
 http.configureAuthTransport(token,()=>assert.fail('Valid session must remain mounted'))
 let sent=[]
 globalThis.fetch=async(input,init)=>{
   const value=init.headers.get('Authorization')
   sent.push(value)
   return new Response('',{status:value==='Bearer old'?401:200})
 }
 const responses=Promise.all([http.authFetch('/api/v1/events'),http.authFetch('/api/v1/stream')])
 await new Promise(resolve=>setImmediate(resolve))
 assert.equal(renewals,1)
 release()
 assert.deepEqual((await responses).map(r=>r.status),[200,200])
 assert.equal(await token('old'),'new')
 assert.equal(renewals,1)
 assert.deepEqual(sent,['Bearer old','Bearer old','Bearer new','Bearer new'])
})

test('a repeated API rejection is bounded, and recovering a write never resends it',async()=>{
 let count=0
 http.configureAuthTransport(async rejected=>rejected?'new':'old',()=>assert.fail('Renewed login is still active'))
 globalThis.fetch=async()=>{count++;return new Response('',{status:401})}
 assert.equal((await http.authFetch('/api/v1/events')).status,401)
 assert.equal(count,2)
 await assert.rejects(http.authFetch('/api/v1/contracts',{method:'POST',body:'one submission'}),/重新提交/)
 assert.equal(count,3)
})

test('use the JWT expiry when the locally calculated lifetime runs past it',async()=>{
 const now=Math.floor(Date.now()/1000)
 const claims=Buffer.from(JSON.stringify({iat:now-295,exp:now+5})).toString('base64url')
 const user={access_token:'test.'+claims+'.test',expires_at:now+295,refresh_token:'refresh'}
 const token=createAccessTokenProvider(async()=>user,async()=>({...user,access_token:'renewed'}))
 assert.equal(await token(),'renewed')
})

test('transient renewal failure preserves the session, definitive grant rejection requires login',async()=>{
 const user={access_token:'old',expires_at:Date.now()/1000+5,refresh_token:'refresh'}
 const token=createAccessTokenProvider(async()=>user,async()=>{throw new TypeError('network')})
 assert.equal(await token(),'old')
 await assert.rejects(token('old'),/暂时无法连接/)
 user.expires_at=0
 await assert.rejects(token(),/暂时无法连接/)
 const invalid=createAccessTokenProvider(async()=>user,async()=>{throw {error:'invalid_grant'}})
 assert.equal(await invalid('old'),null)
})
