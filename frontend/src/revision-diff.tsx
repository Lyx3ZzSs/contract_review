import {useMemo, useState} from 'react'
// Character-level comparison preserves Chinese text, whitespace and Unicode.
export function textChanges(before: string, after: string) {
  const a = Array.from(before), b = Array.from(after)
  const parts: {kind: 'same' | 'remove' | 'add'; text: string}[] = []
  const push = (kind: typeof parts[number]['kind'], text: string) => {
    if (!text) return
    const last = parts.at(-1)
    if (last?.kind === kind) last.text += text
    else parts.push({kind, text})
  }
  let start = 0, end = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  while (end < a.length-start && end < b.length-start && a[a.length-1-end] === b[b.length-1-end]) end++
  push('same', a.slice(0,start).join(''))
  const x = a.slice(start,a.length-end), y = b.slice(start,b.length-end)
  // Bound memory for unusually long clauses; highlight the changed span in that case.
  if ((x.length+1)*(y.length+1) > 1_000_000) {
    push('remove',x.join('')); push('add',y.join(''))
  } else {
    const width = y.length+1, dp = new Uint32Array((x.length+1)*width)
    for (let i=x.length-1;i>=0;i--) for (let j=y.length-1;j>=0;j--)
      dp[i*width+j] = x[i]===y[j] ? 1+dp[(i+1)*width+j+1] : Math.max(dp[(i+1)*width+j],dp[i*width+j+1])
    let i=0,j=0
    while(i<x.length || j<y.length) {
      if(i<x.length && j<y.length && x[i]===y[j]) { push('same',x[i++]);j++ }
      else if(i<x.length && (j===y.length || dp[(i+1)*width+j]>=dp[i*width+j+1])) push('remove',x[i++])
      else push('add',y[j++])
    }
  }
  push('same',end ? a.slice(a.length-end).join('') : '')
  return parts
}
export function RevisionDiff({before,after}:{before:string;after:string}) {
  const parts=useMemo(()=>textChanges(before,after),[before,after])
  const [compare,setCompare]=useState(true)
  const [expanded,setExpanded]=useState(false)
  const long=Array.from(before).length+Array.from(after).length>700
  return <div className={`revision-diff ${long&&!expanded?'is-folded':''}`}>
    <div className="revision-diff-legend"><span>{compare?<><span className="diff-remove-key">删除</span> <span className="diff-add-key">新增</span></>:'修改后全文'}</span><button type="button" aria-pressed={compare} onClick={()=>setCompare(v=>!v)}>{compare?'关闭对比':'开启对比'}</button></div>
    <blockquote aria-label={compare?'修订对比':'修改后全文'}>{compare?parts.map((p,i)=>p.kind==='remove'?<del key={i}>{p.text}</del>:p.kind==='add'?<ins key={i}>{p.text}</ins>:<span key={i}>{p.text}</span>):after||'（删除上述文字）'}</blockquote>
    {long&&<button className="revision-expand-text" type="button" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded?'收起长条款':'展开完整修订'}</button>}
    {compare&&!after&&<span className="revision-delete-note">删除上述文字</span>}
  </div>
}
