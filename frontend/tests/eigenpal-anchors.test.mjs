import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
let dir,bind
before(async()=>{dir=await mkdtemp(join(tmpdir(),'eigenpal-'));await build({entryPoints:['src/editors/eigenpal-anchors.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'test.mjs')});bind=(await import(pathToFileURL(join(dir,'test.mjs')))).bindEigenpalAnchors})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const paragraphs=[{text:'合同'},{text:''},{text:'付款付款'},{text:'🧾验收后付款'},{text:'付款付款'}]
const blocks=paragraphs.flatMap((p,i)=>p.text?[{id:'v:p'+(i+1),text:p.text}]:[])
const find=text=>paragraphs.flatMap((p,i)=>p.text===text?[{blockId:'native'+i,paragraphIndex:i,start:0,length:text.length}]:[])
const target=(blockId,paragraph,start,end,quote)=>({documentVersionId:'v',blockId,paragraph,start,end,quote,blocks})
test('duplicate paragraphs bind by verified structural ordinal including empty paragraphs',()=>{
 const map=bind('v',blocks,paragraphs,find)
 assert.equal(map.resolve(target('v:p5','付款付款',2,4,'付款')).blockId,'native4')
 assert.equal(map.resolve(target('v:p3','付款付款',0,2,'付款')).blockId,'native2')
})
test('Python Unicode offsets are translated to UTF-16 without selecting the wrong text',()=>{
 const map=bind('v',blocks,paragraphs,find)
 assert.deepEqual(map.resolve(target('v:p4','🧾验收后付款',1,4,'验收后')),{blockId:'native3',start:2,length:3,expectedText:'验收后'})
 assert.equal(map.resolve(target('v:p4','🧾验收后付款',0,1,'🧾')).length,2)
})
test('projection changes, removed empty paragraphs, and duplicate native IDs fail closed',()=>{
 assert.throws(()=>bind('v',blocks,paragraphs.filter(p=>p.text),find))
 assert.throws(()=>bind('v',[...blocks].reverse(),paragraphs,find))
 assert.throws(()=>bind('v',blocks,paragraphs,text=>find(text).map(m=>({...m,blockId:'same'}))))
 assert.throws(()=>bind('v',blocks,paragraphs,text=>[...find(text),...find(text)]))
})
test('stale versions, mismatched quotes and invalid ranges never fall back to global text search',()=>{
 const map=bind('v',blocks,paragraphs,find),t=target('v:p3','付款付款',0,2,'付款')
 for(const override of [{documentVersionId:'old'},{paragraph:'changed'},{quote:'收款'},{start:-1},{end:20},{start:.5},{end:0}])assert.throws(()=>map.resolve({...t,...override}))
})
test('long paragraphs use a bounded identity query after full text verification',()=>{
 const text='验收后付款。'.repeat(150),block={id:'v:p1',text},queries=[]
 const map=bind('v',[block],[{text}],q=>{queries.push(q);return [{blockId:'long',paragraphIndex:0,start:0,length:q.length}]})
 assert.equal(Array.from(queries[0]).length,64)
 assert.equal(map.resolve(target('v:p1',text,100,106,Array.from(text).slice(100,106).join(''))).blockId,'long')
 assert.throws(()=>bind('v',[block],[{text:text+'变化'}],()=>[]))
})
