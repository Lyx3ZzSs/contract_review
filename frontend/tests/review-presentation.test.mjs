import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
let dir, model
before(async()=>{dir=await mkdtemp(join(tmpdir(),'rixin-presentation-'));await build({entryPoints:['src/review-issue-presentation.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'view.mjs')});model=await import(pathToFileURL(join(dir,'view.mjs')))})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const evidence=(quote)=>({block_id:'p1',start:0,end:quote.length,quote})
const issue={id:'x',rule_id:'RL-05',status:'insufficient_evidence',explanation:'原始解释',evidence:[evidence('编号：'),evidence('签字：')]}
test('structured display separates excluded fields and retains only relevant primary evidence',()=>{
  const finding={...issue,presentation:{version:'issue-presentation-v1',title:'编号的填写要求待确认',summary:'需要核对编号',next_step:'核对填写阶段',observations:[{name:'编号',status:'insufficient_evidence',evidence:[issue.evidence[0]],requirement_evidence:[]},{name:'签字',status:'no_flag_for_target_rule',evidence:[issue.evidence[1]],requirement_evidence:[]}]}}
  const view=model.issuePresentation(finding,'字段完整性')
  assert.equal(view.title,'编号的填写要求待确认');assert.equal(view.excluded.length,1)
  assert.deepEqual(view.evidence,[issue.evidence[0]])
  assert.equal(finding.explanation,'原始解释')
})
test('legacy explanations never get reverse-parsed into invented titles',()=>{
  const view=model.issuePresentation(issue,'字段完整性')
  assert.equal(view.title,'字段完整性');assert.equal(view.summary,'原始解释')
  assert.deepEqual(view.evidence,issue.evidence)
})
test('attachment actions distinguish missing files from existing-content association',()=>{
  assert.equal(model.supplementAction({...issue,attachment_name:'技术附件',match_state:'missing'}).mode,'material')
  assert.equal(model.supplementAction({...issue,attachment_name:'技术附件',match_state:'candidate'}).mode,'link')
  assert.equal(model.supplementAction(issue).mode,'statement')
  assert.match(model.issuePresentation({...issue,attachment_name:'技术附件',match_state:'missing'},'附件完整性').title,/本轮未见/)
})
test('history compares matching identities, preserves AI state and detects evidence-only changes',()=>{
  const old={run_id:'old',issue:{...issue,subject_key:'field'},decisions:[],created_at:'2026-11-10T00:00:00Z'}
  const current={...old,run_id:'now',created_at:'2026-11-11T00:00:00Z',issue:{...old.issue,id:'y',evidence:[evidence('新证据')]}}
  const history={items:[current,old],assertions:[]}
  const changes=model.historyChanges(history)
  assert.equal(changes[1].change,'证据已更新，AI 判断保持不变')
  assert.equal(model.historyChanges({items:[old,{...current,issue:{...current.issue,subject_key:'other'}}],assertions:[]})[1].change,'首次记录')
})
test('case advisories retain specific titles and request legal review rather than attachments',()=>{
 const finding={...issue,rule_id:'CR-02',execution_mode:'case_advisory',title:'9.3 已履约服务费可能被扣留',attachment_name:'相关附件'}
 assert.equal(model.issuePresentation(finding,'责任检查').title,finding.title)
 assert.match(model.issuePresentation(finding,'责任检查').nextStep,/需法务复核/)
 assert.doesNotMatch(model.issuePresentation(finding,'责任检查').nextStep,/补充附件/)
 assert.equal(model.supplementAction(finding).mode,'statement')
})
