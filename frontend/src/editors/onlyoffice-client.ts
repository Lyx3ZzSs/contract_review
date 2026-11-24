export interface DocsInstance {destroyEditor:()=>void;requestClose:()=>void;downloadAs:(format?:string)=>void}
declare global {interface Window {DocsAPI?:{DocEditor:new(id:string,config:Record<string,unknown>)=>DocsInstance}}}
let loading:Promise<void>|undefined,loadedUrl=''
export function loadDocs(url:string){
  if(loading&&loadedUrl===url)return loading
  if(loadedUrl&&loadedUrl!==url)throw Error('编辑器资源版本已变化，请刷新页面')
  loadedUrl=url
  loading=new Promise<void>((resolve,reject)=>{const s=document.createElement('script');s.src=url;s.onload=()=>resolve();s.onerror=()=>{loading=undefined;loadedUrl='';s.remove();reject(Error('文档服务加载失败'))};document.head.append(s)})
  return loading
}
export function bridge(host:HTMLElement,origin:string,documentKey:string){
  let disposed=false,queue:Promise<unknown>=Promise.resolve(),navigation=0
  const pending=new Map<string,{resolve:(value:any)=>void;reject:(err:Error)=>void;timer:ReturnType<typeof setTimeout>}>()
  function receive(e:MessageEvent){const m=e.data;if(e.origin!==origin||e.source!==host.querySelector('iframe')?.contentWindow||m?.channel!=='rixin-editor-v1'||m.documentKey!==documentKey)return;const p=pending.get(m.requestId);if(!p)return;clearTimeout(p.timer);pending.delete(m.requestId);m.ok?p.resolve(m.result):p.reject(Error(m.error||'编辑器操作失败'))}
  window.addEventListener('message',receive)
  function transmit<T>(action:string,args:unknown,timeoutMs=20000):Promise<T>{
      if(disposed)return Promise.reject(Error('编辑会话已结束'))
      return new Promise((resolve,reject)=>{const requestId=crypto.randomUUID();const timer=setTimeout(()=>{pending.delete(requestId);reject(Error('编辑器响应超时，请重试'))},timeoutMs);pending.set(requestId,{resolve,reject,timer});host.querySelector('iframe')?.contentWindow?.postMessage({channel:'rixin-editor-v1',requestId,documentKey,action,args},origin)})
  }
  return {
    send<T=any>(action:string,args:unknown={},timeoutMs=20000):Promise<T>{
      // Mode restoration and save barriers must not collide with a navigation.
      // Cancellation bypasses the queue and also invalidates queued locations.
      if(action==='cancelNavigation'){navigation++;return transmit<T>(action,args)}
      const generation=navigation
      const work=queue.catch(()=>{}).then(()=>['locate','presentEvidence'].includes(action)&&generation!==navigation?({status:'interrupted'} as T):transmit<T>(action,args,timeoutMs))
      queue=work
      return work
    },
    dispose(){disposed=true;window.removeEventListener('message',receive);pending.forEach(p=>{clearTimeout(p.timer);p.reject(Error('编辑器已关闭'))});pending.clear()}
  }
}
