import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
let dir,http
const originalFetch=globalThis.fetch
before(async()=>{dir=await mkdtemp(join(tmpdir(),'rixin-auth-'));await build({entryPoints:['src/auth-http.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'auth.mjs')});http=await import(pathToFileURL(join(dir,'auth.mjs')))})
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
 http.configureAuthTransport(async()=>'revoked',()=>expired++)
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
