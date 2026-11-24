import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const built=await build({entryPoints:['src/app-route.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {readAppRoute,contractRoute,createAppNavigation}=await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'))
const tick=()=>new Promise(resolve=>setImmediate(resolve))
function browser(hash='#/'){
 const entries=[{hash,state:null}];let cursor=0;const listeners=new Set()
 const win={location:{hash,href:'http://test/'+hash},addEventListener:(_,fn)=>listeners.add(fn),removeEventListener:(_,fn)=>listeners.delete(fn)}
 const sync=()=>{win.location.hash=entries[cursor].hash;win.location.href='http://test/'+win.location.hash}
 win.history={get state(){return entries[cursor].state},replaceState(state,_,url){entries[cursor]={state,hash:url.includes('#')?url.slice(url.indexOf('#')):''};sync()},pushState(state,_,hash){entries.splice(cursor+1);entries.push({hash,state});cursor++;sync()},go(delta){if(cursor+delta<0||cursor+delta>=entries.length)return;cursor+=delta;sync();for(const fn of listeners)void fn()}}
 return win
}
test('address restores the selected contract; malformed addresses never become IDs',()=>{
 assert.deepEqual(readAppRoute(contractRoute('server:abc-123')),{kind:'review',id:'server:abc-123'})
 assert.deepEqual(readAppRoute(''),{kind:'workbench'})
 assert.deepEqual(readAppRoute('#/rules'),{kind:'rules'})
 for(const hash of ['#/contracts/%2F/review','#/contracts/../review','#/contracts//review','#/unknown'])assert.deepEqual(readAppRoute(hash),{kind:'invalid'})
})
test('navigation and browser traversal await saving; refresh reads the same address',async()=>{
 const win=browser();const accepted=[];let release;let blocked=false
 const nav=createAppNavigation(win,r=>accepted.push(r),()=>blocked?new Promise(resolve=>{release=resolve}):Promise.resolve(true))
 await nav.navigate(contractRoute('server:a'));blocked=true
 win.history.go(-1);assert.equal(accepted.at(-1).kind,'review')
 release(true);await tick();assert.equal(accepted.at(-1).kind,'workbench')
 blocked=false;win.history.go(1);await tick();assert.deepEqual(readAppRoute(win.location.hash),{kind:'review',id:'server:a'})
 nav.dispose()
})
test('failed save restores browser history without discarding the current contract',async()=>{
 const win=browser();const accepted=[];let allowed=true
 const nav=createAppNavigation(win,r=>accepted.push(r),async()=>allowed)
 await nav.navigate(contractRoute('server:a'));allowed=false
 win.history.go(-1);await tick();assert.equal(win.location.hash,contractRoute('server:a'));assert.equal(accepted.length,1)
 allowed=true;win.history.go(-1);await tick();assert.equal(accepted.at(-1).kind,'workbench');nav.dispose()
})
test('rapid back traversals save once and resolve to the latest destination',async()=>{
 const win=browser();const accepted=[];let release,calls=0,blocked=false
 const nav=createAppNavigation(win,r=>accepted.push(r),()=>{calls++;return blocked?new Promise(resolve=>{release=resolve}):Promise.resolve(true)})
 await nav.navigate('#/rules');await nav.navigate(contractRoute('server:a'));blocked=true
 win.history.go(-1);win.history.go(-1);assert.equal(calls,3)
 release(true);await tick();assert.equal(accepted.at(-1).kind,'workbench');nav.dispose()
})
test('disposed navigation cannot commit after a late save result',async()=>{
 const win=browser();let release
 const nav=createAppNavigation(win,()=>assert.fail('late commit'),()=>new Promise(resolve=>{release=resolve}))
 const navigation=nav.navigate('#/rules');nav.dispose();release(true);await navigation;assert.equal(win.location.hash,'#/')
})

test('iframe or duplicate history entries do not close an unchanged room',async()=>{
 const win=browser(contractRoute('server:a'));let closes=0
 const nav=createAppNavigation(win,()=>assert.fail('unchanged route'),async()=>{closes++;return true})
 win.history.pushState({rixinRouteIndex:0},'',win.location.hash);win.history.go(-1);await tick()
 assert.equal(closes,0);nav.dispose()
})

test('record URLs restore a specific round independently from the current editor',()=>{
 assert.deepEqual(readAppRoute('#/records'),{kind:'records'})
 assert.deepEqual(readAppRoute('#/records/run-1'),{kind:'record',id:'run-1'})
 assert.deepEqual(readAppRoute('#/records/%2F'),{kind:'invalid'})
})
