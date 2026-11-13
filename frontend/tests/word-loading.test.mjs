import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
let dir, serial = 0
const originalFetch = globalThis.fetch
before(async () => {
  dir = await mkdtemp(join(tmpdir(), 'rixin-load-tests-'))
  await build({ entryPoints: ['src/backend-api.ts'], bundle: true, platform: 'node', format: 'esm', outfile: join(dir, 'api.mjs') })
})
after(async () => { globalThis.fetch = originalFetch; await rm(dir, { recursive: true, force: true }) })
const fresh = () => import(pathToFileURL(join(dir, 'api.mjs')).href + '?' + serial++)
const pause = ms => new Promise(r => setTimeout(r, ms))
function server() {
  const calls = []; let version = 'v1', complete = false, failFile = false
  globalThis.fetch = async (path, init) => {
    calls.push({ path, init })
    await pause(5)
    if (path.endsWith('/file')) {
      if (failFile) { failFile = false; return new Response('', { status: 503 }) }
      return new Response(path.includes('/v1/') && path.includes('/versions/v1/') ? 'first document' : 'second document')
    }
    if (init?.method === 'POST') { version = 'v2'; return Response.json({ id: 'v2', filename: 'contract.docx', blocks: [] }) }
    if (path.endsWith('/editor-state')) return Response.json({ document_version_id: version, draft_state: null, results: complete ? [{ id: 'result', document_version_id: version, created_at: '2026-11-10T10:00:00Z' }] : [] })
    if (path.endsWith('/reviews')) return Response.json([])
    if (path.endsWith('/draft-state')) return Response.json(null)
    if (path.endsWith('/results')) return Response.json(complete ? [{ id: 'result', document_version_id: version, created_at: '2026-11-10T10:00:00Z' }] : [])
    if (path.includes('/versions/')) return Response.json({ id: path.split('/').at(-1), filename: 'contract.docx', blocks: [] })
    return Response.json({ id: 'c1', current_document_version_id: version })
  }
  return { calls, setVersion: value => { version = value }, complete: () => { complete = true }, failFile: () => { failFile = true } }
}
test('concurrent opens share the file download and metadata request', async () => {
  const s = server(), api = await fresh()
  const [a, b] = await Promise.all([api.remoteDraft('server:c1'), api.remoteDraft('server:c1')])
  assert.equal(await a.blob.text(), 'first document'); assert.equal(await b.blob.text(), 'first document')
  assert.equal(s.calls.filter(c => c.path.endsWith('/file')).length, 1)
  assert.equal(s.calls.filter(c => c.path === '/api/v1/contracts/c1/editor-state').length, 1)
})
test('reopen reuses immutable bytes but reads fresh completion state', async () => {
  const s = server(), api = await fresh()
  assert.equal((await api.remoteDraft('server:c1')).review.completed, false)
  s.complete()
  assert.equal((await api.remoteDraft('server:c1')).review.completed, true)
  assert.equal(s.calls.filter(c => c.path.endsWith('/file')).length, 1)
  assert.equal(s.calls.filter(c => c.path.endsWith('/editor-state')).length, 2)
})
test('a newer version gets new bytes and becomes the optimistic save version', async () => {
  const s = server(), api = await fresh()
  await api.remoteDraft('server:c1'); s.setVersion('v2')
  const next = await api.remoteDraft('server:c1')
  assert.equal(await next.blob.text(), 'second document'); assert.equal(api.knownVersion('server:c1'), 'v2')
  await api.remoteSave('server:c1', next)
  assert.equal(s.calls.find(c => c.init?.method === 'POST').init.body.get('expected_version_id'), 'v2')
})
test('failed downloads are evicted so reopening can retry', async () => {
  const s = server(), api = await fresh(); s.failFile()
  await assert.rejects(api.remoteDraft('server:c1'), /正文下载失败/)
  assert.equal(await (await api.remoteDraft('server:c1')).blob.text(), 'first document')
  assert.equal(s.calls.filter(c => c.path.endsWith('/file')).length, 2)
})
test('version metadata and binary download run in parallel after one consistent snapshot', async () => {
  const s = server(), api = await fresh(), fetch = globalThis.fetch
  let release
  const gate = new Promise(r => { release = r })
  globalThis.fetch = async (path, init) => { if (path === '/api/v1/versions/v1') await gate; return fetch(path, init) }
  const loading = api.remoteDraft('server:c1')
  await pause(20)
  const requestedFile = s.calls.some(c => c.path.endsWith('/file'))
  release(); await loading
  assert.equal(requestedFile, true)
})
test('save conflict preserves the actually loaded version for retry', async () => {
  server(); const api = await fresh(); const draft = await api.remoteDraft('server:c1')
  globalThis.fetch = async () => Response.json({detail:'文档版本已变化，请刷新后重新保存'}, {status:409})
  await assert.rejects(api.remoteSave('server:c1', draft), /文档版本已变化/)
  assert.equal(api.knownVersion('server:c1'), 'v1')
})
test('concurrent JSON readers cannot mutate each other\'s review state', async () => {
  server(); const api = await fresh()
  const [a,b] = await Promise.all([api.api('/contracts/c1/editor-state'),api.api('/contracts/c1/editor-state')])
  a.results.push({id:'local-only'})
  assert.deepEqual(b.results,[])
})
test('same-document new material review unfreezes saved draft and updates queue completion',async()=>{
 const api=await fresh()
 const old={id:'old',status:'completed',document_version_id:'v1',material_bundle_id:'b1',findings:[]}
 let latest={...old,id:'new',material_bundle_id:'b2',status:'running'}
 const result={id:'final',run_id:'old',document_version_id:'v1',created_at:'2026-11-10T10:00:00Z',review_snapshot:old}
 const contract={id:'c1',title:'合同',created_at:'2026-11-10T00:00:00Z',current_document_version_id:'v1',client_metadata:{}}
 const draft={review:{completed:true,decisions:{},activity:[]}}
 globalThis.fetch=async path=>{
   if(path.endsWith('/editor-state'))return Response.json({document_version_id:'v1',draft_state:draft,results:[result]})
   if(path.endsWith('/reviews'))return Response.json([latest])
   if(path.includes('/runs/'))return Response.json(latest)
   if(path.endsWith('/results'))return Response.json([result])
   if(path.endsWith('/draft-state'))return Response.json(draft)
   if(path.includes('/contracts?'))return Response.json([contract])
   if(path.endsWith('/file'))return new Response('document')
   if(path.includes('/versions/'))return Response.json({id:'v1',filename:'合同.docx',blocks:[]})
   return Response.json(contract)
 }
 assert.equal((await api.remoteDraft('server:c1')).review.completed,false)
 assert.equal((await api.remoteContracts())[0].status,'审阅中')
 latest=old
 assert.equal((await api.remoteDraft('server:c1')).review.completed,true)
 assert.equal((await api.remoteContracts())[0].status,'已完成')
})
