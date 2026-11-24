import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('./editor-service-worker.js',import.meta.url),'utf8');
const scope='http://127.0.0.1:18083/10.0.0-labesign9/';
function harness(){
 const events={},entries=new Map(),fetched=[];let claimed=false;
 const response=(text,headers={})=>({ok:true,type:'basic',redirected:false,headers:new Headers(headers),text,clone(){return this}});
 const cache={keys:async()=>[...entries.keys()].map(url=>({url})),match:async r=>entries.get(r.url),delete:async r=>entries.delete(r.url),put:async(r,v)=>entries.set(r.url,v)};
 vm.runInNewContext(source,{URL,self:{registration:{scope},addEventListener:(k,f)=>events[k]=f,skipWaiting:async()=>{},clients:{claim:async()=>{claimed=true}}},caches:{open:async()=>cache},fetch:async r=>{fetched.push(r.url);return response('network',r.headers||{})}});
 return {events,entries,fetched,response,claimed:()=>claimed,async activate(){let done;events.activate({waitUntil:p=>done=p});await done},async request(path,headers){let result;events.fetch({request:{url:scope+path,method:'GET',headers},respondWith:p=>result=p});return result}};
}
test('upgrade removes stale mutable bridge and no-store assets but preserves document data',async()=>{
 const h=harness();h.entries.set(scope+'web-apps/bridge.js',h.response('old'));h.entries.set(scope+'sdkjs/private.js',h.response('old',{'cache-control':'no-store'}));h.entries.set(scope+'sdkjs/sdk.js',h.response('sdk'));h.entries.set(scope+'cache/files/document',h.response('document'));
 await h.activate();assert.equal(h.claimed(),true);assert.deepEqual([...h.entries.keys()],[scope+'sdkjs/sdk.js',scope+'cache/files/document']);
 assert.equal(await h.request('web-apps/bridge.js'),undefined);assert.equal(await h.request('cache/files/document'),undefined);
});
test('no-store never reused or written even when an old worker cached it',async()=>{
 const h=harness(),path='sdkjs/sdk.js';h.entries.set(scope+path,h.response('stale',{'cache-control':'private, no-store'}));
 assert.equal((await h.request(path,{'cache-control':'no-store'})).text,'network');assert.equal(h.entries.size,0);assert.equal(h.fetched.length,1);
});
test('immutable assets retain cache acceleration',async()=>{
 const h=harness();await h.request('sdkjs/sdk.js');await h.request('sdkjs/sdk.js');assert.equal(h.fetched.length,1);
});
