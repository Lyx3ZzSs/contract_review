export type AppRoute = {kind:'workbench'}|{kind:'rules'}|{kind:'records'}|{kind:'record';id:string}|{kind:'review';id:string}|{kind:'invalid'}
export function readAppRoute(hash:string):AppRoute {
  const path=hash.replace(/^#/,'')
  if(!path||path==='/')return {kind:'workbench'}
  if(path==='/rules')return {kind:'rules'}
  if(path==='/records')return {kind:'records'}
  const record=/^\/records\/([a-zA-Z0-9_-]+)$/.exec(path)
  if(record)return {kind:'record',id:record[1]}
  const match=/^\/contracts\/([a-zA-Z0-9_-]+)\/review$/.exec(path)
  return match?{kind:'review',id:'server:'+match[1]}:{kind:'invalid'}
}
export const contractRoute=(id:string)=>`#/contracts/${encodeURIComponent(id.replace(/^server:/,''))}/review`

// Route changes, including browser traversal, share the same save/close barrier.
export function createAppNavigation(win:Window,accept:(route:AppRoute)=>void,canLeave:()=>Promise<boolean>){
  let index=Number.isInteger(win.history.state?.rixinRouteIndex)?win.history.state.rixinRouteIndex:0
  let hash=win.location.hash,busy=false,disposed=false,rollback=false
  let target={hash,index}
  const stamp=()=>win.history.replaceState({...win.history.state,rixinRouteIndex:index},'',win.location.href)
  stamp()
  const allowed=async()=>{try{return await canLeave()}catch{return false}}
  const pop=async()=>{
    if(rollback){rollback=false;return}
    target={hash:win.location.hash,index:Number.isInteger(win.history.state?.rixinRouteIndex)?win.history.state.rixinRouteIndex:index+1}
    if(busy)return
    if(target.hash===hash){index=target.index;stamp();return}
    busy=true
    const ok=await allowed()
    if(disposed)return
    busy=false
    if(ok){hash=target.hash;index=target.index;stamp();accept(readAppRoute(hash))}
    else if(index!==target.index){rollback=true;win.history.go(index-target.index)}
    else win.history.replaceState({...win.history.state,rixinRouteIndex:index},'',hash||'#/')
  }
  win.addEventListener('popstate',pop)
  return {
    async navigate(next:string){
      if(busy||next===hash)return
      busy=true
      const ok=await allowed()
      if(disposed)return
      busy=false
      // A browser traversal during saving takes precedence over a button click.
      if(win.location.hash!==hash){if(ok){hash=target.hash;index=target.index;stamp();accept(readAppRoute(hash))}else{rollback=true;win.history.go(index-target.index)};return}
      if(!ok)return
      hash=next;index++;win.history.pushState({rixinRouteIndex:index},'',next);accept(readAppRoute(next))
    },
    dispose(){disposed=true;win.removeEventListener('popstate',pop)},
  }
}
