import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, BookOpen, ChevronRight, LayoutDashboard, Scale, Search, Settings2, ShieldCheck } from 'lucide-react'
import { Button } from './components/ui/button'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './components/ui/tabs'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './components/ui/dialog'
import { loadRules, isCaseAdvisory, type RulePack } from './rule-data'
import { RuleCasesPanel } from './rule-cases'
import { cn } from './lib/utils'
import './rules.css'

export function RulesCenter({onBack,onStart}: {onBack:()=>void;onStart:(setId:string)=>void}) {
  const [pack,setPack]=useState<RulePack|null>(null)
  const [selected,setSelected]=useState('')
  const [query,setQuery]=useState('')
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [mobileDetail,setMobileDetail]=useState(false)
  const [technical,setTechnical]=useState(false)
  const load=async()=>{
    setLoading(true);setError('')
    try {setPack(await loadRules())} catch(e){setPack(null);setError(e instanceof Error?e.message:'规则读取失败')} finally {setLoading(false)}
  }
  useEffect(()=>{void load()},[])
  const visible=pack?.rules.filter(r=>[r.id,r.title,r.trigger,pack.presentation.items[r.id]?.title,pack.presentation.items[r.id]?.summary].join(' ').toLowerCase().includes(query.trim().toLowerCase()))??[]
  const rule=visible.find(r=>r.id===selected)??visible[0]
  const advisory=!!rule&&isCaseAdvisory(rule)
  const display=rule && pack?.presentation.items[rule.id]
  return <div className="app-shell rules-shell">
    <aside className="app-rail" aria-label="应用导航"><button className="brand-mark" aria-label="返回合同工作台" onClick={onBack}><img src="/favicon.png" alt="国能日新" width={36} height={36}/></button><div className="rail-items"><button className="rail-button" aria-label="合同工作台" onClick={onBack}><LayoutDashboard/></button><button className="rail-button current" aria-label="审查规则中心" aria-current="page"><Scale/></button></div></aside>
    <div className="workspace rules-workspace">
      <header className="workspace-header"><div className="breadcrumb"><button className="rules-breadcrumb-back" aria-label="返回工作台" onClick={onBack}><ArrowLeft/></button><span className="brand-name">国能日新</span><span className="breadcrumb-slash">/</span><span>审查规则中心</span></div></header>
      <main className="rules-main"><div className="rules-page-heading"><div><div className="workbench-eyebrow">REVIEW PLAYBOOKS</div><h1>审查规则中心</h1><p>了解审查口径，核对案例结果，追溯规则来源。</p></div><Button variant="outline" onClick={()=>void load()} disabled={loading}>刷新规则</Button></div>
        {loading?<div className="rules-loading" role="status">正在读取服务端规则…</div>:error?<div className="rules-loading" role="alert"><p>{error}</p><Button variant="outline" onClick={()=>void load()}>重新加载</Button></div>:!pack?.rules.length?<div className="rules-loading">暂无可用审查规则</div>:<div className="rules-layout">
          <aside className="rules-library" aria-label="规则集"><div className="rules-library-heading"><span>服务端规则集</span><span>1</span></div><div className="rules-library-scroll"><button className="rule-set-item active" aria-pressed="true"><BookOpen/><span><strong>合同审查规则</strong><small>{pack.rules.length} 条</small></span><ChevronRight/></button></div><div className="rules-library-note"><ShieldCheck/><span>基础检查与案例提示<p>适用范围与正式发布待确认</p></span></div></aside>
          <section className="rules-set-workspace" aria-label="当前规则集">
            <header className="rules-set-heading"><div><div className="rules-set-title"><h2>合同审查规则</h2><span className="rule-version">{pack.version}</span></div><div className="rules-set-meta"><span>执行口径 {pack.execution_policy.version}</span></div></div><div className="rules-set-actions"><Button variant="outline" onClick={()=>setTechnical(true)}><Settings2/>技术配置</Button><Button onClick={()=>onStart('redlines')}>发起审阅<ArrowRight/></Button></div></header>
            <div className="rules-set-description"><p>基础检查依据法务提供的审查标准；案例提示来自历史案例，需法务复核。审查范围以本轮资料和执行版本为准。</p></div>
            <div className={cn('rules-content-grid',mobileDetail&&'show-rule-detail')}>
              <section className="rule-list-panel" aria-label="规则列表"><div className="rule-list-toolbar"><h3>审查规则 <span>{pack.rules.length}</span></h3><label className="rule-search"><Search/><input aria-label="搜索规则" placeholder="搜索规则名称或编号…" value={query} onChange={e=>{setQuery(e.target.value);setMobileDetail(false)}}/></label></div><div className="rule-list-scroll">{visible.map(r=><button key={r.id} className={cn('rule-list-item',rule?.id===r.id&&'selected')} aria-pressed={rule?.id===r.id} onClick={()=>{setSelected(r.id);setMobileDetail(true)}}><div><span>{r.id}</span><small>{isCaseAdvisory(r)?'案例提示 · 需法务复核':'基础检查'}</small></div><h4>{pack.presentation.items[r.id]?.title??r.title}</h4><p>{pack.presentation.items[r.id]?.summary??r.trigger}</p><footer>查看规则说明<ChevronRight/></footer></button>)}{!visible.length&&<div className="rule-list-empty"><p>没有匹配的规则</p><Button variant="outline" onClick={()=>setQuery('')}>清除搜索</Button></div>}</div><div className="rule-list-foot">{visible.length} 条规则 · 服务端只读</div></section>
              <section className="rule-detail-panel" aria-label="规则详情">{rule?<><header className="rule-detail-heading"><button className="rule-mobile-back" onClick={()=>setMobileDetail(false)}><ArrowLeft/>返回规则列表</button><div className="rule-detail-overline"><span>{rule.id}</span><span>执行口径 {pack.execution_policy.version}</span></div><h3 key={rule.id}>{display?.title??rule.title}</h3><div className="rule-detail-badges"><span>{advisory?'案例提示 · 需法务复核':'规则口径：已原则确认'}</span><span>风险等级：{rule.severity}</span></div></header>
                <Tabs defaultValue="description" key={rule.id} className="rule-reader">
                  <TabsList variant="line" className="rule-reader-tabs" aria-label="规则详情内容"><TabsTrigger value="description">规则说明</TabsTrigger><TabsTrigger value="cases">案例验证</TabsTrigger><TabsTrigger value="source">来源与版本</TabsTrigger></TabsList>
                  <TabsContent value="description" className="rule-detail-scroll">
                    <p className="rule-purpose">{display?.summary??rule.source_principle}</p>
                    {rule.id==='RL-04'&&<p className="rule-scope-note"><strong>当前检查范围</strong>{pack.presentation.current_scope}</p>}
                    <section className="rule-detail-section"><h4>什么情况需要关注</h4><p>{rule.trigger}</p></section>
                    <section className="rule-detail-section"><h4>哪些情况需要区分</h4><ul>{rule.non_trigger_or_exceptions.map(item=><li key={item}>{item}</li>)}</ul></section>
                    <section className="rule-detail-section"><h4>发现问题后怎么处理</h4><p>{rule.insufficient_evidence_behavior}</p><p>{rule.proposed_output}</p></section>
                    <details className="rule-detail-section rule-evidence"><summary>核对时需要的材料与信息</summary><p>{rule.required_inputs.join('、')}</p><p>拟定适用范围：{rule.proposed_scope}</p></details>
                    {rule.id!=='RL-04'&&<p className="rule-scope-note"><strong>当前检查范围</strong>{pack.presentation.current_scope}</p>}
                  </TabsContent>
                  <TabsContent value="cases" className="rule-detail-scroll"><RuleCasesPanel ruleId={rule.id} pack={pack}/></TabsContent>
                  <TabsContent value="source" className="rule-detail-scroll">
                    <section className="rule-detail-section"><h4>法务审查原则</h4><blockquote className="rule-source-quote">{rule.source_principle}</blockquote>{(rule.source_ids??(advisory?[]:['S06'])).map(id=><p key={id}>来源：{pack.presentation.sources.find(s=>s.id===id)?.filename??'来源文件未记录'} · {id}</p>)}<p>依据状态：{rule.authority}</p>{advisory&&<p>政策阈值：{rule.policy_threshold==null?'未确认，不作为通用标准':rule.policy_threshold}。历史案例不代表通用规则已批准。</p>}</section>
                    {!advisory&&<section className="rule-detail-section"><h4>口径确认记录</h4><p>{pack.presentation.confirmation.date} · 当前会话用户“{pack.presentation.confirmation.user_statement}”</p><p>{pack.presentation.confirmation.scope}</p><p>记录编号：{pack.presentation.confirmation.id}</p></section>}
                    {!advisory&&<section className="rule-detail-section"><h4>仍待确认</h4><ul>{pack.presentation.confirmation.pending_configuration.map(item=><li key={item}>{item}</li>)}</ul><p>本次确认不包含：{pack.presentation.confirmation.not_covered.join('、')}。</p></section>}
                    <section className="rule-detail-section"><h4>版本记录</h4><dl className="rule-version-list"><dt>规则集</dt><dd>{pack.version}</dd><dt>执行口径</dt><dd>{pack.execution_policy.version}</dd><dt>展示文案</dt><dd>{pack.presentation.version}</dd></dl><p>执行口径以当前版本为准。历史审查继续保留发起时的规则快照。</p></section>
                  </TabsContent>
                </Tabs>
                <footer className="rule-detail-footer"><span>每次审查保存规则与执行口径版本，历史结果可追溯。</span></footer>
              </>:<div className="rule-detail-empty">请选择一条规则</div>}</section>
            </div>
          </section>
        </div>}
      </main>
    </div>
    {pack&&<Dialog open={technical} onOpenChange={setTechnical}><DialogContent className="rule-technical-dialog"><DialogHeader><DialogTitle>合同审查规则 · 技术配置</DialogTitle><DialogDescription>面向开发与排查。以下是服务端当前实际使用的整套执行指令，只读展示。</DialogDescription></DialogHeader><div className="rule-technical-scroll"><dl className="rule-version-list"><dt>执行口径</dt><dd>{pack.execution_policy.version}</dd><dt>规则集摘要</dt><dd><code>{pack.pack_sha256}</code></dd><dt>指令摘要</dt><dd><code>{pack.execution_policy.prompt_sha256}</code></dd></dl><h4>模型执行指令</h4><pre>{pack.execution_policy.instructions}</pre></div></DialogContent></Dialog>}
  </div>
}
