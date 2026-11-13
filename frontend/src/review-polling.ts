// One request at a time. A manual refresh during an existing request must read
// again afterward (e.g. a new review was submitted while the old GET was running).
export function createReviewPoller(load:()=>Promise<boolean>, onError:(error:unknown)=>void, interval=2500) {
  let stopped=false, rerun=false, failures=0
  let timer:ReturnType<typeof setTimeout>|undefined
  let pending:Promise<void>|undefined
  const refresh=():Promise<void>=>{
    if(stopped)return Promise.resolve()
    clearTimeout(timer)
    if(pending){rerun=true;return pending}
    pending=(async()=>{
      let active=false
      do {
        rerun=false
        try {active=await load();failures=0}
        catch(error){if(!stopped)onError(error);active=++failures<3}
      }while(rerun&&!stopped)
      if(active&&!stopped)timer=setTimeout(()=>{void refresh()},interval)
    })().finally(()=>{pending=undefined})
    return pending
  }
  return {refresh,stop:()=>{stopped=true;clearTimeout(timer)}}
}
