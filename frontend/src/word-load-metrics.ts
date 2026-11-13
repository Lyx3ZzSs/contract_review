export interface LoadEvent { stage: string; elapsedMs: number; durationMs?: number; detail?: string }
export interface LoadReport { id: string; documentId: string; startedAt: string; status: 'loading'|'ready'|'error'|'cancelled'; events: LoadEvent[] }
declare global { interface Window { contractLoadMetrics?: LoadReport[] } }

// Local diagnostics only: no document text, filenames, or remote telemetry.
export function startWordLoad(documentId: string) {
  const started = performance.now()
  const enabled = import.meta.env.DEV || new URLSearchParams(location.search).get('wordPerf') === '1'
  const report: LoadReport = { id: crypto.randomUUID(), documentId, startedAt: new Date().toISOString(), status: 'loading', events: [] }
  if (enabled) {
    window.contractLoadMetrics ??= []
    window.contractLoadMetrics.push(report)
    window.contractLoadMetrics.splice(0, Math.max(0, window.contractLoadMetrics.length - 12))
  }
  const seen = new Set<string>()
  function mark(stage: string, detail?: string, durationMs?: number) {
    if (report.status === 'cancelled' || report.status === 'error' || seen.has(stage)) return
    seen.add(stage)
    const elapsedMs = Math.round((performance.now() - started) * 10) / 10
    report.events.push({ stage, elapsedMs, ...(durationMs === undefined ? {} : { durationMs: Math.round(durationMs * 10) / 10 }), ...(detail ? { detail } : {}) })
  }
  async function measure<T>(stage: string, work: () => Promise<T>): Promise<T> {
    const start = performance.now()
    mark(`${stage}.start`)
    try { const result = await work(); mark(`${stage}.end`, undefined, performance.now() - start); return result }
    catch (error) { mark(`${stage}.failed`, undefined, performance.now() - start); throw error }
  }
  function finish(status: LoadReport['status']) {
    if (report.status !== 'loading') return
    mark(status === 'ready' ? 'editor.ready' : status)
    report.status = status
    if (enabled && status !== 'cancelled') {
      console.groupCollapsed(`[Word 加载] ${status} · ${Math.round(performance.now() - started)} ms`)
      console.table(report.events)
      console.groupEnd()
    }
  }
  mark('load.start')
  return { mark, measure, finish }
}
export type WordLoadTrace = ReturnType<typeof startWordLoad>
