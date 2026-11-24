import {fetchEventSource} from '@microsoft/fetch-event-source'
import {authFetch} from './auth-http'
/** Bearer-authenticated SSE. The caller owns cursor recovery and reconnect delays. */
export class AuthEventSource {
  onopen: (() => void) | null = null
  onmessage: ((event: {data: string}) => void) | null = null
  onerror: (() => void) | null = null
  private controller = new AbortController()
  private listeners = new Map<string, () => void>()
  constructor(url: string) {
    void fetchEventSource(url, {
      fetch: authFetch, signal: this.controller.signal, openWhenHidden: true,
      onopen: async response => {
        if (!response.ok || !response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('审查实时连接失败')
        this.onopen?.()
      },
      onmessage: event => {
        if (!event.event || event.event === 'message') this.onmessage?.(event)
        else this.listeners.get(event.event)?.()
      },
      onclose: () => {if (!this.controller.signal.aborted) this.onerror?.()},
      onerror: error => {throw error},
    }).catch(() => {if (!this.controller.signal.aborted) this.onerror?.()})
  }
  addEventListener(name: string, listener: () => void) {this.listeners.set(name, listener)}
  close() {this.controller.abort()}
}
