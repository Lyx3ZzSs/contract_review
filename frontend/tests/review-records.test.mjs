import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const built=await build({entryPoints:['src/review-records-data.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {validateContractFile,recordStatus,recordAction,recordRoute}=await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'))
test('upload rejects wrong type, bad contents and oversized files before submission',async()=>{
 await validateContractFile(new File([new Uint8Array([80,75,3,4])],'合同.DOCX'))
 await assert.rejects(validateContractFile(new File(['text'],'合同.pdf')),/DOCX/)
 await assert.rejects(validateContractFile(new File(['text'],'合同.docx')),/有效/)
 await assert.rejects(validateContractFile({name:'合同.docx',size:20*1024*1024+1}),/20 MB/)
})
test('AI and human completion actions stay distinct; historical rounds never say continue',()=>{
 const record={id:'abc',status:'completed',incomplete:false,is_latest:true,completed_at:null}
 assert.equal(recordStatus(record),'已生成结果')
 assert.equal(recordAction(record),'继续审阅')
 assert.equal(recordAction({...record,is_latest:false}),'查看记录')
 assert.equal(recordAction({...record,completed_at:'2026-11-18'}),'查看记录')
 assert.equal(recordStatus({...record,incomplete:true}),'部分完成')
 assert.equal(recordAction({...record,status:'failed'}),'查看原因')
 assert.equal(recordAction({...record,status:'running'}),'查看进度')
 assert.equal(recordRoute('run-1'),'#/records/run-1')
})

test('legacy Word requires DOC binary signature; renaming DOCX does not pass',async()=>{
 await validateContractFile(new File([new Uint8Array([0xd0,0xcf,0x11,0xe0,0xa1,0xb1,0x1a,0xe1])],'合同.DOC'))
 await assert.rejects(validateContractFile(new File(['PKfake zip'],'合同.doc')),/有效的 DOC/)
 await assert.rejects(validateContractFile(new File(['bad'],'合同.doc')),/有效的 DOC/)
})

test('model-reviewed records use the server classification and preserve partial results',()=>{
 assert.equal(recordStatus({status:'needs_input',record_status:'completed'}),'已生成结果')
 assert.equal(recordStatus({status:'needs_input',record_status:'completed',incomplete:true}),'部分完成')
 assert.equal(recordStatus({status:'needs_input'}),'待补充信息')
})
