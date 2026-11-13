import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('./fixtures/editor-bridge-candidate.js',import.meta.url),'utf8');
function harness({online=true,reconnecting=false,disconnectDuringSave=false}={}) {
 const handlers={},replies=[];let held=false,disconnected=false;
 const api={isDocumentModified:()=>false,asc_isDocumentCanSave:()=>false,asc_Save:()=>{if(disconnectDuringSave)disconnected=true},asc_setRestriction:()=>{},};
 const main={_isDocReady:true,document:{key:'test'},_state:{get isDisconnected(){return disconnected}},stackDisableActions:{get:({type})=>type==='reconnect'&&reconnecting}};
 const doc={addEventListener:()=>{},createElement:()=>({style:{}}),body:{append:()=>{held=true}},getElementById:()=>({remove:()=>{held=false}})};
 const parent={postMessage:x=>replies.push(x)};
 const box={URLSearchParams,location:{search:'?parentOrigin=http://127.0.0.1:5175'},navigator:{onLine:online},document:doc,parent,Asc:{c_oAscRestrictionType:{View:1}},setTimeout,clearTimeout,Date};
 box.window={Asc:{editor:api},DE:{getController:()=>main},addEventListener:(name,fn)=>handlers[name]=fn};
 vm.runInNewContext(source,box);
 return {async freeze(){await handlers.message({source:parent,origin:'http://127.0.0.1:5175',data:{channel:'rixin-editor-v1',requestId:'r',documentKey:'test',action:'freeze'}});return replies.at(-1)},held:()=>held};
}
test('offline cannot be reported synchronized even with clean local flags',async()=>{const h=harness({online:false});assert.equal((await h.freeze()).ok,false);assert.equal(h.held(),false)});
test('document service reconnecting cannot be reported synchronized',async()=>{const h=harness({reconnecting:true});assert.equal((await h.freeze()).ok,false)});
test('disconnect during save unlocks the local shield and refuses confirmation',async()=>{const h=harness({disconnectDuringSave:true});assert.equal((await h.freeze()).ok,false);assert.equal(h.held(),false)});
test('connected clean editor can freeze',async()=>{const h=harness();assert.equal((await h.freeze()).ok,true);assert.equal(h.held(),true)});
