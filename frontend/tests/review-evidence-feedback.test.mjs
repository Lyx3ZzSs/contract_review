import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const result=await build({entryPoints:['src/review-evidence-feedback.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {evidenceFeedback}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'))
test('partial geometry and offscreen results never claim complete visible evidence',()=>{
 assert.match(evidenceFeedback({ok:true,visible:true,moved:false,geometry:'start-only'},'center'),/仅标出.*起点/)
 assert.match(evidenceFeedback({ok:true,visible:false,moved:false,geometry:'line-ranges'},'center'),/尚未进入可视区域/)
 assert.equal(evidenceFeedback({ok:true,visible:true,moved:true,geometry:'line-ranges'},'center'),'')
 for(const status of ['ambiguous','stale','unsupported','interrupted'])assert.doesNotMatch(evidenceFeedback({ok:false,visible:false,moved:false,status},'center'),/已定位原文/)
})
