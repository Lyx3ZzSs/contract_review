import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
let dir,flow
before(async()=>{dir=await mkdtemp(join(tmpdir(),'rixin-export-'));await build({entryPoints:['src/export-flow.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'flow.mjs')});flow=await import(pathToFileURL(join(dir,'flow.mjs')))})
after(async()=>{await rm(dir,{recursive:true,force:true})})
test('three deliverables have no apply-all or completion action',()=>{
 assert.deepEqual(flow.exportChoices.map(c=>c.kind),['contract','changes','opinions'])
 assert.doesNotMatch(JSON.stringify(flow.exportChoices),/接受全部|一键|标记审阅完成/)
})
test('missing results never block a current contract download',()=>{
 assert.equal(flow.unavailable('contract',null),'')
 assert.equal(flow.unavailable('changes',{changes_available:false,changes_reason:'没有修改'}),'没有修改')
 assert.equal(flow.unavailable('opinions',{opinions_available:false,opinions_reason:'正在生成'}),'正在生成')
})
test('retry uses same frozen export and never silently changes document version',async()=>{
 const pending={id:'fixed',state:'pending',document_version_id:'old'};let calls=0,downloads=[]
 const generate=async id=>{assert.equal(id,'fixed');if(!calls++)throw Error('temporary');return {...pending,state:'ready',download_url:'/file'}}
 await assert.rejects(flow.finishExport(pending,generate,async()=>assert.fail()),/temporary/)
 const ready=await flow.finishExport(pending,generate,async r=>downloads.push(r.document_version_id))
 assert.deepEqual(downloads,['old']);assert.equal(ready.id,'fixed')
 await flow.finishExport(ready,async()=>assert.fail(),async r=>assert.equal(r.id,'fixed'))
})
test('download failure stays retryable and incomplete generation cannot download',async()=>{
 await assert.rejects(flow.finishExport({id:'x',state:'pending'},async()=>({id:'x',state:'failed',error:'生成失败'}),async()=>assert.fail()),/生成失败/)
 await assert.rejects(flow.finishExport({id:'x',state:'ready',download_url:'/file'},async()=>assert.fail(),async()=>{throw Error('下载失败')}),/下载失败/)
})
