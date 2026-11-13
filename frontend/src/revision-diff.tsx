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
  const parts=textChanges(before,after)
  return <div className="revision-diff">
    <div className="revision-diff-legend"><span>修改对照 · 尚未写入正文</span><span><span className="diff-remove-key">删除</span> <span className="diff-add-key">新增</span></span></div>
    <strong>修改前</strong><blockquote>{before ? parts.filter(p=>p.kind!=='add').map((p,i)=>p.kind==='remove'?<del key={i}>{p.text}</del>:<span key={i}>{p.text}</span>) : '（插入位置）'}</blockquote>
    <strong>修改后</strong><blockquote>{after ? parts.filter(p=>p.kind!=='remove').map((p,i)=>p.kind==='add'?<ins key={i}>{p.text}</ins>:<span key={i}>{p.text}</span>) : '（删除上述文字）'}</blockquote>
  </div>
}
