import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm,readFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'

let dir,api,doc
const originalFetch=globalThis.fetch
before(async()=>{
  dir=await mkdtemp(join(tmpdir(),'rixin-upload-'))
  await build({entryPoints:['src/backend-api.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'api.mjs')})
  api=await import(pathToFileURL(join(dir,'api.mjs')))
  doc=await readFile('../backend/tests/fixtures/legacy-word.doc')
})
after(async()=>{globalThis.fetch=originalFetch;await rm(dir,{recursive:true,force:true})})

for(const withParties of [true,false])for(const suffix of ['DOC','docx']){
  test(`contract upload preserves original ${suffix} bytes and filename, party selection=${withParties}`,async()=>{
    const bytes=suffix==='DOC'?doc:new Uint8Array([80,75,3,4])
    const file=new File([bytes],`原始文件.${suffix}`)
    const calls=[]
    globalThis.fetch=async(url,init)=>{
      calls.push({url,init})
      return new Response(JSON.stringify(url.endsWith('/import')
        ?{contract:{id:'c',party_details:{counterparties:['相对方']}},version:{id:'v'}}
        :{id:url.endsWith('/versions')?'v':'c'}),{status:201})
    }
    await api.createRemote({title:'用户另填的合同名称',type:'服务',position:'乙方'},file,
      withParties?{preview_id:'preview',our_index:1,counterparty_indices:[0]}:undefined)
    const request=calls.find(c=>c.init.body instanceof FormData)
    assert.ok(request)
    const uploaded=request.init.body.get('file')
    assert.equal(uploaded.name,file.name)
    assert.deepEqual(new Uint8Array(await uploaded.arrayBuffer()),new Uint8Array(bytes))
    if(withParties)assert.equal(JSON.parse(request.init.body.get('metadata')).title,'用户另填的合同名称')
  })
}
