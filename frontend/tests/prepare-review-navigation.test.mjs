import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const result=await build({entryPoints:['src/prepare-review-navigation.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {prepareReviewNavigation:prepare}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'))
const editor=(overrides={})=>({ready:true,busy:false,saveStatus:'saved',flushSave:async()=>true,...overrides})
test('saved document navigates directly without unnecessary save',async()=>{
 assert.equal(await prepare(editor({flushSave:()=>assert.fail('unexpected save')}),()=>true,()=>{}),true)
})
test('dirty, saving and failed saves are flushed before navigation continues',async()=>{
 for(const state of [{saveStatus:'saving'},{saveStatus:'error'},{busy:true}]){
  let release;const messages=[];let done=false
  const work=prepare(editor({...state,flushSave:()=>new Promise(r=>release=r)}),()=>true,m=>messages.push(m)).then(r=>{done=true;return r})
  assert.equal(done,false);assert.match(messages[0],/保存后继续定位/)
  release(true);assert.equal(await work,true);assert.match(messages.at(-1),/正在定位/)
 }
})
test('save failure and unloaded editor provide actionable errors without navigation',async()=>{
 await assert.rejects(prepare(editor({saveStatus:'error',flushSave:async()=>false}),()=>true,()=>{}),/再次点击定位原文重试/)
 await assert.rejects(prepare(editor({ready:false}),()=>true,()=>{}),/尚未加载完成/)
})
test('superseded click or leaving the page cancels navigation after shared save completes',async()=>{
 let release,valid=true;const messages=[]
 const pending=prepare(editor({saveStatus:'saving',flushSave:()=>new Promise(r=>release=r)}),()=>valid,m=>messages.push(m))
 valid=false;release(true);assert.equal(await pending,false);assert.equal(messages.length,1)
})
