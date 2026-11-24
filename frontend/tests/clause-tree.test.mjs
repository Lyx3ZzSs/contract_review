import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createRequire} from 'node:module'
let dir,model,evidenceLabel
before(async()=>{
 dir=await mkdtemp(join(tmpdir(),'rixin-clause-tree-'))
 await build({entryPoints:['src/clause-tree.ts','src/review-card-content.ts'],bundle:true,platform:'node',format:'cjs',outExtension:{'.js':'.cjs'},outdir:dir})
 const require=createRequire(import.meta.url)
 model=require(join(dir,'clause-tree.cjs'))
 ;({evidenceLabel}=require(join(dir,'review-card-content.cjs')))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const clause=(id,parent_id,block_ids,number,title,kind='clause')=>({id,parent_id,block_ids,number,title,kind})
const version={id:'v',structure_version:'clause-tree-v2',blocks:[{id:'a',text:'第一条 费用'},{id:'b',text:'1.1 😀 付款'},{id:'c',text:'100元'}],clauses:[clause('root',null,['a'],'第一条','费用'),clause('child','root',['b'],'1.1','付款'),clause('table','child',['c'],null,'费用表','table')]}
const evidence=(id,text)=>({block_id:id,start:0,end:[...text].length,quote:text})
test('table evidence is grouped under its owning clause',()=>{
 assert.equal(model.reviewClauseAt(version,evidence('c','100元')).id,'child')
})
test('signature fields use the party in the same signing cell',()=>{
 const inCell=(id,text,cell)=>({id,text,table_location:{table:3,row:1,cell}})
 const blocks=[inCell('client','甲方：公司甲',1),inCell('stamp-a','（盖章）',1),inCell('address-a','地址：\u3000',1),inCell('date-a','日期：',1),
  inCell('provider','乙方：公司乙',2),inCell('stamp-b','（签字）',2),inCell('date-b','日期：',2),inCell('date-c','日期：',3)]
 const v={...version,blocks,clauses:[clause('owner',null,[],'第三条','特别约定'),clause('table','owner',blocks.map(b=>b.id),null,'表格 3','table')]}
 assert.equal(evidenceLabel(v,evidence('date-a','日期：')),'签署表 · 甲方日期')
 assert.equal(evidenceLabel(v,evidence('address-a','地址：\u3000')),'签署表 · 甲方地址')
 assert.equal(evidenceLabel(v,evidence('date-b','日期：')),'签署表 · 乙方日期')
 assert.equal(evidenceLabel(v,evidence('date-c','日期：')),'表格 3 · 日期')
})
test('source span selection keeps Python code point offsets and separate clauses in one paragraph',()=>{
 const v={id:'v',blocks:[{id:'p',text:'😀第一条第二条'}],clauses:[{...clause('a',null,['p'],'1','甲'),source_spans:[{block_id:'p',start:0,end:4}]},{...clause('b',null,['p'],'2','乙'),source_spans:[{block_id:'p',start:4,end:7}]}]}
 assert.equal(model.clauseAt(v,{block_id:'p',start:4,end:7}).id,'b')
})
