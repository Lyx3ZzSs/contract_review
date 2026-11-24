import {test,afterEach} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import vm from 'node:vm'
const source=await readFile(new URL('./navigation-bridge.js',import.meta.url),'utf8')
const cleanups=[];afterEach(()=>{while(cleanups.length)cleanups.pop()()})
function fixture({origin='http://127.0.0.1:5175',texts=['证据'],top=900,bottom=940,min=0,max=5000,capability=true,interrupt=false,reduced=false,starved=false,acrossPages=false,layoutShift=false,caretReveal=false,geometry=true,transformed=false}={}){
 let selectionPaints=0;let clock=0,listener,scrolls=0,selection=null,modified=false,searches=0,pendingCaret=false;const listeners={},replies=[],moves=[]
 const parent={postMessage:m=>replies.push(m)}
 const scroll={Ssa:0,qZd:max,kg:{cY:true,D0:false},scrollTo(x,y){this.scrollBy(0,y-this.Ssa)},scrollBy(x,dy){scrolls++;this.Ssa=Math.max(min,Math.min(max,this.Ssa+dy));moves.push(this.Ssa);if(interrupt&&scrolls>1)listeners.wheel()}}
 const paragraphs=texts.map((text,index)=>{
  const range=(start=0,end=Array.from(text).length)=>{
   const content=Array.from(text).slice(start,end).join('')
   const position=index*1000
   return {GetStartPage:()=>0,GetEndPage:()=>acrossPages?1:0,GetText:()=>content,
    GetStartPos:()=>position+start,GetEndPos:()=>position+end,
    ToJSON:()=>JSON.stringify({type:'paragraph',content:[{type:'run',content:[content]}]}),
    Select(){pendingCaret=true;selection={index,start,end};scroll.Ssa=top-100;return true}}
  }
  return {GetText:()=>text+'\r\n',GetRange:range,Search:quote=>{const found=[];let at=0;while((at=text.indexOf(quote,at))>=0){const start=Array.from(text.slice(0,at)).length;found.push(range(start,start+Array.from(quote).length));at+=quote.length}return found}}
 })
 const drawing={uba:false,T_:null,GWc(){},lWb(){},cl:[0,1].map(()=>({Cw:1000,mz:2000,get zp(){return {left:0,right:1000,top:-scroll.Ssa,bottom:2000-scroll.Ssa}}}))};const sdk={G9e:false,ye:()=>({wq:()=>selectionPaints++,vo:()=>drawing,Az:()=>selection,xB:s=>{selection=s;pendingCaret=true},KK:geometry?page=>{drawing.T_=transformed?{}:null;drawing.lWb(page,100,acrossPages?(page?bottom-20:top):top,200,acrossPages?20:bottom-top)}:undefined,$p(){if(sdk.G9e&&drawing.uba)pendingCaret=false}}),wa:{MA:scroll},asc_GetSelectionBounds:()=>[[0,top-scroll.Ssa],[0,bottom-scroll.Ssa]],asc_findText:()=>{searches++;throw Error('global search must not be used')},asc_GetSelectedText:()=>selection?Array.from(texts[selection.index]).slice(selection.start,selection.end).join(''):'',isDocumentModified:()=>modified,asc_isDocumentCanSave:()=>modified}
 const elements=new Map(),make=()=>({dataset:{},style:{},children:[],append(node){this.children.push(node);if(node.id)elements.set(node.id,node)},remove(){elements.delete(this.id);for(const parent of elements.values())parent.children=parent.children.filter(n=>n!==this)}})
 const document={body:make(),createElement:make,addEventListener:(n,f)=>listeners[n]=f,getElementById:id=>id==='id_viewer'?{getBoundingClientRect:()=>({height:600,width:800,left:0,top:0})}:elements.get(id)}
 const doc={GetAllParagraphs:()=>paragraphs,GetRangeBySelect:()=>selection?
  paragraphs[selection.index].GetRange(selection.start,selection.end):{Select(){pendingCaret=true;selection=null}}}
 const context={document,parent,location:{search:'?parentOrigin='+encodeURIComponent(origin)},URLSearchParams,window:{Asc:{editor:sdk},AscBuilder:capability?{sb:{GetDocument:()=>doc}}:{},DE:{getController:()=>({_isDocReady:true,document:{key:'d'}})},addEventListener:(n,f)=>{if(n==='message')listener=f}},performance:{now:()=>clock},matchMedia:()=>({matches:reduced}),requestAnimationFrame:f=>starved?0:setImmediate(()=>{clock+=16;if(caretReveal&&pendingCaret){scroll.Ssa=0;pendingCaret=false}if(layoutShift&&clock===32)scroll.Ssa-=400;f()}),setTimeout,clearTimeout,cancelAnimationFrame:clearImmediate}
 vm.runInNewContext(source,context)
 let serial=0
 async function call(action,args={}){const requestId='test-'+serial++;await listener({source:parent,origin,data:{channel:'rixin-editor-v1',documentKey:'d',requestId,action,args}});return replies.find(m=>m.requestId===requestId)?.result}
 cleanups.push(()=>call('clearEvidence'));
 const blocks=texts.map((text,i)=>({id:'v:p'+i,text}))
 return {call,blocks,scroll,sdk,drawing,document,context,layer:()=>elements.get('rixin-evidence-layer'),marks:()=>elements.get('rixin-evidence-layer')?.children.filter(n=>n.dataset.role==='current')??[],wheel:()=>listeners.wheel(),bind:()=>call('bindAnchors',{version:'v',blocks}),locate:(i=0,start=0,end=Array.from(texts[i]).length)=>call('locate',{version:'v',blockId:blocks[i].id,paragraph:blocks[i].text,quote:Array.from(texts[i]).slice(start,end).join(''),start,end}),get selectionPaints(){return selectionPaints},get selection(){return selection},get moves(){return moves},get searches(){return searches},dirty(){modified=true},replies}
}
const present=(f,reveal='never',overrides={})=>f.call('presentEvidence',{reveal,targets:[{version:'v',blockId:f.blocks[0].id,paragraph:f.blocks[0].text,quote:f.blocks[0].text,start:0,end:Array.from(f.blocks[0].text).length,...overrides}]})
test('evidence overlay restores the original native selection and never scrolls for updates',async()=>{const f=fixture({top:250,bottom:290});await f.bind();const r=await present(f);assert.equal(r.status,'presented');assert.equal(r.moved,false);assert.equal(f.selection,null);assert.equal(f.scroll.Ssa,0);assert.equal(f.marks().length,1)})
test('already readable evidence is marked in place; offscreen evidence is revealed preserving the caret',async()=>{const f=fixture({top:250,bottom:290});await f.bind();assert.equal((await present(f,'if-needed')).moved,false);const far=fixture({top:1200,bottom:1240});await far.bind();const r=await present(far,'if-needed');assert.equal(r.visible,true);assert.equal(r.moved,true);assert.equal(far.selection,null)})
test('invalid evidence and stale versions cannot replace current marks or move the viewport',async()=>{const f=fixture({top:250,bottom:290});await f.bind();await present(f);assert.equal((await present(f,'center',{quote:'不匹配'})).status,'not_found');assert.equal(f.marks().length,1);assert.equal(f.scroll.Ssa,0);f.dirty();assert.equal((await present(f)).status,'stale')})
test('scrolling preserves decorations and cancels outstanding presentation',async()=>{const f=fixture({top:250,bottom:290});await f.bind();await present(f);f.wheel();assert.equal(f.marks().length,1);const moving=fixture({interrupt:true});await moving.bind();assert.equal((await present(moving,'center')).status,'interrupted');assert.equal(moving.selection,null)})
test('an oversized end offset cannot validate just because JS slice clamps it',async()=>{const f=fixture();await f.bind();assert.equal((await present(f,'never',{end:999})).reason,'invalid_offsets');assert.equal(f.marks().length,0)})
test('cross-page evidence paints separate ranges; rebinding removes old geometry',async()=>{const f=fixture({top:250,bottom:290,acrossPages:true});await f.bind();await present(f);assert.equal(f.marks()[0].dataset.shape,'range');assert.equal(f.marks().length,2);await f.call('bindAnchors',{version:'different',blocks:f.blocks});assert.equal(f.marks().length,0)})
test('repeated full paragraphs are identified by a verified complete ordered mapping',async()=>{const f=fixture({texts:['项目','包含项目的长段','重复标题','重复标题','（盖章）','（盖章）']});assert.equal((await f.bind()).mapped,6);for(let i=0;i<6;i++){assert.equal((await f.locate(i)).status,'located');assert.equal(f.selection.index,i)}assert.equal(f.searches,0)})
test('short repeated evidence is selected only within its bound paragraph; offsets count Unicode code points',async()=>{const f=fixture({texts:['第一条 😀服务费及服务费','其他服务费']});await f.bind();assert.equal((await f.locate(0,5,8)).status,'located');assert.deepEqual(f.selection,{index:0,start:5,end:8});assert.equal(f.searches,0)})
test('generated extra text is permitted only when the entire ordered embedding is unique',async()=>{const f=fixture({texts:['2','标题','标题','正文']});const r=await f.call('bindAnchors',{version:'v',blocks:[{id:'v:a',text:'标题'},{id:'v:b',text:'标题'},{id:'v:c',text:'正文'}]});assert.equal(r.mapped,3);const got=await f.call('locate',{version:'v',blockId:'v:b',paragraph:'标题',quote:'标题',start:0,end:2});assert.equal(got.paragraphIndex,2);assert.equal(f.selection.index,2)})
test('multiple valid sequence mappings remain unresolved rather than selecting the first occurrence',async()=>{const f=fixture({texts:['标题','标题']});const r=await f.call('bindAnchors',{version:'v',blocks:[{id:'v:a',text:'标题'}]});assert.equal(r.mapped,0);assert.equal((await f.call('locate',{version:'v',blockId:'v:a',paragraph:'标题',quote:'标题',start:0,end:2})).status,'ambiguous');assert.equal(f.selection,null)})
test('a mismatching new version invalidates the old map',async()=>{const f=fixture();await f.bind();assert.equal((await f.call('bindAnchors',{version:'v2',blocks:[{id:'v2:a',text:'变更原文'}]})).status,'mapping_mismatch');assert.equal((await f.locate()).status,'mapping_missing')})
test('stale content and invalid offsets do not move selection',async()=>{const f=fixture();await f.bind();assert.equal((await f.call('locate',{version:'v',blockId:'v:p0',paragraph:'证据',quote:'证据',start:1,end:2})).reason,'invalid_offsets');f.dirty();assert.equal((await f.locate()).status,'stale');assert.equal(f.selection,null)})
test('legacy callers can locate unique full paragraphs even when the quote repeats elsewhere',async()=>{const f=fixture({texts:['甲方支付费用','乙方收取费用']});const r=await f.call('locate',{paragraph:'甲方支付费用',quote:'费用'});assert.equal(r.status,'located');assert.equal(f.selection.index,0);assert.equal(f.searches,0)})
test('near targets restore the native jump before smoothly centering once',async()=>{const f=fixture();await f.bind();const r=await f.locate();assert.equal(r.centered,true);assert.equal(r.stable,true);assert.equal(r.centerError,0);assert.equal(f.moves[0],0);assert.equal(r.transition,'smooth');assert.ok(r.frames>10)})
test('large distances switch directly instead of animating across many pages',async()=>{const f=fixture({top:3000,bottom:3040});await f.bind();const r=await f.locate();assert.equal(r.transition,'direct');assert.equal(r.frames,1);assert.equal(r.centered,true)})
test('top boundary is confirmed by actual clamping',async()=>{const f=fixture({top:20,bottom:60});await f.bind();const r=await f.locate();assert.equal(r.centered,false);assert.equal(r.boundary,true)})
test('long selection starts and reduced motion avoid long animation',async()=>{const f=fixture({top:900,bottom:1900,reduced:true});await f.bind();const r=await f.locate();assert.equal(r.alignment,'start');assert.equal(r.centered,true);assert.equal(r.frames,1)})
test('user scroll cancels instead of acknowledging a completed navigation',async()=>{const f=fixture({interrupt:true});await f.bind();const r=await f.locate();assert.equal(r.status,'interrupted');assert.equal(r.centered,false);assert.equal(f.replies.find(m=>m.event==='user_scroll').documentKey,'d')})
test('unknown build cannot claim a validated map',async()=>{const f=fixture({capability:false});assert.equal((await f.bind()).status,'unsupported')})

test('throttled animation frames have bounded waits and fall back to direct positioning',async()=>{const f=fixture({starved:true});await f.bind();const start=Date.now(),r=await f.locate();assert.equal(r.status,'located');assert.equal(r.frameFallback,true);assert.equal(r.transition,'direct');assert.ok(Date.now()-start<1000)})

test('cross-page selections align their start even when the middle lies in a page gap',async()=>{const f=fixture({top:700,bottom:1100,acrossPages:true});await f.bind();const r=await f.locate();assert.equal(r.alignment,'start');assert.equal(r.centerError,0);assert.equal(r.centered,true)})

test('a late SDK layout adjustment is corrected before reporting evidence visible',async()=>{const f=fixture({top:3000,bottom:3040,layoutShift:true});await f.bind();const r=await present(f,'if-needed');assert.equal(r.visible,true);assert.equal(f.scroll.Ssa,2720);assert.equal(f.selection,null)})

test('presentation and restoration bypass wheel delta correction using absolute scroll',async()=>{const f=fixture({top:3000,bottom:3040});await f.bind();const absolute=f.scroll.scrollBy.bind(f.scroll);f.scroll.scrollTo=(x,y)=>absolute(0,y-f.scroll.Ssa);f.scroll.scrollBy=()=>{throw Error('wheel delta correction must not run')};const r=await present(f,'if-needed');assert.equal(r.visible,true);assert.equal(f.scroll.Ssa,2720);assert.equal(f.selection,null)})

test('restoring the caret consumes its deferred reveal without leaking SDK flags',async()=>{const f=fixture({top:3000,bottom:3040,caretReveal:true});await f.bind();const r=await present(f,'if-needed');assert.equal(r.visible,true);assert.equal(f.scroll.Ssa,2720);assert.equal(f.sdk.G9e,false);assert.equal(f.drawing.uba,false);assert.equal(f.selection,null)})


test('unsupported transformed text has an explicit fallback, not a guessed rectangle',async()=>{const f=fixture({top:250,bottom:290,transformed:true});await f.bind();const r=await present(f);assert.equal(r.geometry,'start-only');assert.equal(f.marks()[0].dataset.shape,'start');assert.equal(f.layer().children.find(n=>n.dataset.role==='status'),undefined)})
test('same-anchor task updates reuse the overlay and do not scroll',async()=>{const f=fixture({top:250,bottom:290});await f.bind();await present(f);const layer=f.layer();const args={targets:[{version:'v',blockId:f.blocks[0].id,paragraph:'证据',quote:'证据',start:0,end:2}],reveal:'never',context:{phase:'attention',title:'核对付款条件'}};assert.equal((await f.call('presentEvidence',args)).moved,false);assert.equal(f.layer(),layer);assert.match(f.layer().children.find(n=>n.dataset.role==='status').textContent,/有意见待核对/);assert.equal(f.selection,null)})
test('native selection state, including its direction, is restored after geometry capture',async()=>{const f=fixture({texts:['第一处证据'],top:250,bottom:290});await f.bind();await f.locate();f.selection.direction='backward';const saved=f.selection;await present(f);assert.equal(f.selection,saved);assert.equal(f.selection.direction,'backward')})
test('geometry collection restores drawing callbacks even when collection throws',async()=>{const f=fixture({top:250,bottom:290});await f.bind();const original=f.drawing.lWb;const logic=f.sdk.ye();logic.KK=()=>{throw Error('layout not ready')};f.sdk.ye=()=>logic;await present(f);assert.equal(f.drawing.lWb,original);assert.equal(f.selection,null);assert.equal(f.scroll.Ssa,0)})

test('paused context updates change only the label and reject another block',async()=>{const f=fixture({top:250,bottom:290});await f.bind();await present(f);f.wheel();const layer=f.layer(),y=f.scroll.Ssa;assert.equal((await f.call('evidenceContext',{version:'v',blockId:'elsewhere',context:{phase:'finished',title:'错误条款'}})).status,'not_current');assert.equal((await f.call('evidenceContext',{version:'v',blockId:f.blocks[0].id,context:{phase:'attention',title:'付款条件'}})).status,'updated');assert.equal(f.layer(),layer);assert.equal(f.scroll.Ssa,y);assert.match(layer.children.find(n=>n.dataset.role==='status').textContent,/手动阅读 · 有意见待核对/);assert.equal(f.selection,null)})

test('mid-line evidence places its label outside the full paragraph, not over preceding text',async()=>{
 const f=fixture({texts:['前文证据'],top:250,bottom:290});await f.bind();const logic=f.sdk.ye();
 logic.KK=page=>f.drawing.lWb(page,f.selection.start?400:100,250,200,40);f.sdk.ye=()=>logic;
 await present(f,'center',{quote:'证据',start:2,end:4});const label=f.layer().children.find(n=>n.dataset.role==='status');
 const left=Number(label.style.cssText.match(/left:([\d.]+)px/)[1]),width=Number(label.style.cssText.match(/width:([\d.]+)px/)[1]);assert.ok(left+width<100)
})


test('review command confirms the active native tab without changing document content',async()=>{
 const f=fixture();let active=false;
 const tab={getClientRects:()=>[{}],getAttribute:()=>null,click(){active=true}};
 f.document.querySelector=selector=>selector.includes('.active')?(active?tab:null):tab;
 assert.equal((await f.call('review')).tab,'review');assert.equal(active,true);assert.equal(f.selection,null);assert.equal(f.scroll.Ssa,0);
})
test('review command reports missing, hidden and unsuccessful tabs instead of false success',async()=>{
 for(const tab of [null,{getClientRects:()=>[]},{getClientRects:()=>[{}],getAttribute:()=>null,click(){}}]){
  const f=fixture();f.document.querySelector=selector=>selector.includes('.active')?null:tab;
  await f.call('review');assert.equal(f.replies.at(-1).ok,false);assert.match(f.replies.at(-1).error,/审阅工具栏/);
 }
})


test('document language uses the native document default and is idempotent',async()=>{
 const f=fixture();let language=1033,writes=0;
 f.context.window.DE.getController=()=>({_isDocReady:true,document:{key:'d'},editorConfig:{mode:'edit'}});
 f.sdk.asc_getDefaultLanguage=()=>language;f.sdk.asc_setDefaultLanguage=value=>{writes++;language=value};
 assert.equal((await f.call('defaultLanguage')).changed,true);assert.equal(language,2052);
 assert.equal((await f.call('defaultLanguage')).changed,false);assert.equal(writes,1);assert.equal(f.selection,null);
})
test('document language cannot mutate a read-only document or claim a blocked update succeeded',async()=>{
 const f=fixture();let writes=0;
 f.sdk.asc_getDefaultLanguage=()=>1033;f.sdk.asc_setDefaultLanguage=()=>writes++;
 f.context.window.DE.getController=()=>({_isDocReady:true,document:{key:'d'},editorConfig:{mode:'view'}});
 await f.call('defaultLanguage');assert.equal(f.replies.at(-1).ok,false);assert.equal(writes,0);
 f.context.window.DE.getController=()=>({_isDocReady:true,document:{key:'d'},editorConfig:{mode:'edit'}});
 await f.call('defaultLanguage');assert.equal(f.replies.at(-1).ok,false);assert.equal(writes,1);
})

test('native reference selection repaints the editor and removes the legacy overlay',async()=>{const f=fixture({texts:['第一条证据','第二条证据']});await f.bind();await present(f);assert.ok(f.layer());assert.equal((await f.locate(0)).status,'located');assert.equal(f.layer(),undefined);assert.equal(f.selectionPaints,1);assert.equal(f.sdk.asc_GetSelectedText(),'第一条证据');await f.locate(1);assert.equal(f.sdk.asc_GetSelectedText(),'第二条证据');assert.equal(f.selectionPaints,2);assert.equal(f.sdk.isDocumentModified(),false)});

test('automatic numbering does not invalidate an exact native selection; altered source still fails',async()=>{
 const f=fixture({texts:['按月支付服务费。']});await f.bind();
 const original=f.sdk.asc_GetSelectedText;
 f.sdk.asc_GetSelectedText=()=>`1.1\t${original()}`;
 const doc=f.context.window.AscBuilder.sb.GetDocument();
 const selectedRange=doc.GetRangeBySelect;
 doc.GetRangeBySelect=()=>({...selectedRange(),ToJSON:undefined,GetText(options){assert.equal(options.Numbering,false);return original()}});
 assert.equal((await f.locate()).status,'located');assert.equal(f.sdk.isDocumentModified(),false);
 doc.GetRangeBySelect=()=>({...selectedRange(),ToJSON:undefined,GetText(){return '另一段原文'}});
 assert.equal((await f.locate()).reason,'selected_text_mismatch');
});

function writeFixture(initial='付款五日'){
 const f=fixture({texts:[initial]}),doc=f.context.window.AscBuilder.sb.GetDocument(),p=doc.GetAllParagraphs()[0];
 let text=initial,selected='',comments=0,writes=0,bookmarks=0;const order=[];
 f.context.Asc={c_oAscRestrictionType:{None:0,View:1}};
 f.context.window.DE.getController=()=>({_isDocReady:true,document:{key:'d'},editorConfig:{mode:'edit'}});
 p.GetText=()=>text+'\r\n';p.ToJSON=()=>JSON.stringify({content:[{type:'run',content:[text],reviewType:'common'}]});
 p.Search=q=>text.includes(q)?[{GetStartPos:()=>text.indexOf(q),GetText:()=>q,ToJSON:()=>JSON.stringify({type:'document',content:[{type:'paragraph',content:[{type:'run',content:[q],reviewType:'common'},{type:'endRun'}]}]}),Select:()=>{selected=q},AddBookmark:()=>{bookmarks++;return true},AddComment:()=>{order.push('comment');comments++;return {GetId:()=>String(comments)}}}]:[];
 f.sdk.asc_SetLocalTrackRevisions=()=>{};f.sdk.asc_GetSelectedText=()=>selected;
 f.sdk.asc_AddText=after=>{order.push('write');writes++;text=text.replace(selected,after)};
 const args={id:'op',bookmark:'rx_'+'a'.repeat(32),mode:'ALL',comment:'确认付款时间',after_text:'付款十日',target:{version:'v',blocks:f.blocks,blockId:'v:p0',paragraph:initial,quote:initial,start:0,end:Array.from(initial).length}};
 return {f,args,order,get counts(){return {writes,comments,bookmarks}},get text(){return text}};
}
test('combined application adds comment after replacement and replay is idempotent',async()=>{
 const w=writeFixture();assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');
 assert.deepEqual(w.order,['write','comment']);assert.equal(w.text,'付款十日');
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');assert.deepEqual(w.counts,{writes:1,comments:1,bookmarks:1});
});
test('comment-only and modify-only do not perform the other operation',async()=>{
 for(const mode of ['COMMENT','MODIFY']){const w=writeFixture();assert.equal((await w.f.call('applyProposal',{...w.args,mode})).status,'applied');assert.equal(w.counts.comments,mode==='COMMENT'?1:0);assert.equal(w.counts.writes,mode==='MODIFY'?1:0)}
});
test('stale, readonly, and existing tracked edits reject before mutation',async()=>{
 for(const reason of ['dirty','readonly','tracked','commented']){
  const w=writeFixture();if(reason==='dirty')w.f.sdk.isDocumentModified=()=>true;
  if(reason==='readonly')w.f.context.window.DE.getController=()=>({_isDocReady:true,document:{key:'d'},editorConfig:{mode:'view'}});
  if(reason==='tracked')w.f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0].ToJSON=()=>JSON.stringify({changes:[{}],content:[]});
  if(reason==='commented')w.f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0].ToJSON=()=>JSON.stringify({content:[{type:'commentRangeStart'}]});
  assert.equal((await w.f.call('applyProposal',w.args)).status,'rejected');assert.deepEqual(w.counts,{writes:0,comments:0,bookmarks:0});
 }
});
test('partial application retains an uncertain receipt and cannot repeat the edit',async()=>{
 const w=writeFixture();const p=w.f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0],search=p.Search;p.Search=q=>search(q).map(r=>({...r,AddComment:()=>null}));
 assert.equal((await w.f.call('applyProposal',w.args)).status,'uncertain');assert.equal(w.counts.writes,1);
 assert.equal((await w.f.call('applyProposal',w.args)).status,'uncertain');assert.equal(w.counts.writes,1);
});


test('numbered proposal writes verify the selected range without generated numbering',async()=>{
 const w=writeFixture(),doc=w.f.context.window.AscBuilder.sb.GetDocument();
 const selected=w.f.sdk.asc_GetSelectedText;
 w.f.sdk.asc_GetSelectedText=()=>`1.1\t${selected()}`;
 doc.GetRangeBySelect=()=>({GetText:options=>{assert.equal(options.Numbering,false);return selected()}});
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');
 assert.equal(w.text,'付款十日');
});

test('canonical source maps unrelated numbered and ordinary paragraphs without invented tabs',async()=>{
 const w=writeFixture(),doc=w.f.context.window.AscBuilder.sb.GetDocument(),target=doc.GetAllParagraphs()[0];
 doc.GetAllParagraphs=()=>[{GetText:()=> '验收款\r\n',ToJSON:()=>JSON.stringify({pPr:{numPr:{numId:1}}})},target];
 w.args.target.blocks=[{id:'v:list',text:'验收款'},...w.args.target.blocks];
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');
 assert.equal(w.text,'付款十日');assert.deepEqual(w.counts,{writes:1,comments:1,bookmarks:1});
});
test('write mapping rejects missing, reordered, ambiguous and unverified list paragraphs before mutation',async()=>{
 for(const kind of ['missing','reordered','ambiguous','ordinary','internal-space']){
  const w=writeFixture(),doc=w.f.context.window.AscBuilder.sb.GetDocument(),target=doc.GetAllParagraphs()[0];
  const list={GetText:()=>kind==='internal-space'?'验 收款\r\n':'验收款\r\n',ToJSON:()=>JSON.stringify({pPr:kind==='ordinary'?{}:{numPr:{numId:1}}})};
  doc.GetAllParagraphs=()=>kind==='missing'?[target]:kind==='reordered'?[target,list]:kind==='ambiguous'?[list,list,target]:[list,target];
  w.args.target.blocks=[{id:'v:list',text:'\t\t验收款'},...w.args.target.blocks];
  assert.equal((await w.f.call('applyProposal',w.args)).status,'rejected',kind);
  assert.deepEqual(w.counts,{writes:0,comments:0,bookmarks:0},kind);
 }
});
function listWriteTarget(w){
 const p=w.f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0],json=p.ToJSON,get=p.GetText;
 p.GetText=()=> '\t\t'+get();
 p.ToJSON=()=>{const value=JSON.parse(json());return JSON.stringify({...value,pPr:{numPr:{numId:1}},content:[{type:'run',content:[{type:'tab'},{type:'tab'}]},...value.content]})};
 const source='\t\t'+w.args.target.paragraph;
 w.args.target={...w.args.target,blocks:[{id:'v:p0',text:source}],paragraph:source,start:w.args.target.start+2,end:w.args.target.end+2};
 return p;
}
test('real body tabs retain exact source offsets and quotes in all modes',async()=>{
 for(const mode of ['ALL','COMMENT','MODIFY']){
  const w=writeFixture();listWriteTarget(w);w.args.mode=mode;const saved=JSON.stringify(w.args.target);
  assert.equal((await w.f.call('applyProposal',w.args)).status,'applied',mode);
  assert.equal(w.text,mode==='COMMENT'?'付款五日':'付款十日');assert.equal(JSON.stringify(w.args.target),saved);
  assert.deepEqual(w.counts,{writes:mode==='COMMENT'?0:1,comments:mode==='MODIFY'?0:1,bookmarks:1});
 }
});
test('list target projection preserves Unicode prefixes and untouched suffixes',async()=>{
 const w=writeFixture('😀前文付款五日后文');
 w.args.target={...w.args.target,quote:'付款五日',start:3,end:7};listWriteTarget(w);
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');assert.equal(w.text,'😀前文付款十日后文');
});
test('writes never clip quoted formatting or tolerate other target text differences',async()=>{
 for(const reason of ['offset','missing-body-tabs','trailing','internal']){
  const w=writeFixture(),p=listWriteTarget(w);
  if(reason==='prefix-in-quote')Object.assign(w.args.target,{quote:w.args.target.paragraph,start:0});
  if(reason==='offset')w.args.target.start=1;
  if(reason==='missing-body-tabs')p.GetText=()=>w.text+'\r\n';
  if(reason==='trailing')w.args.target.blocks[0].text=w.args.target.paragraph+='\t';
  if(reason==='internal')p.GetText=()=> '付款 五日\r\n';
  assert.equal((await w.f.call('applyProposal',w.args)).status,'rejected');
  assert.deepEqual(w.counts,{writes:0,comments:0,bookmarks:0});
 }
});


function continuationFixture(mode){
 const w=writeFixture(),doc=w.f.context.window.AscBuilder.sb.GetDocument(),p=doc.GetAllParagraphs()[0];
 const priorBookmark='rx_'+'b'.repeat(32),originalSearch=p.Search;
 doc.GetBookmark=name=>name===priorBookmark?{GetRange:()=>originalSearch('付款五日')[0]}:null;
 w.args.continuation={bookmark:priorBookmark,mode,comment:w.args.comment};
 let oldPresent=true,replies=0;
 const oldComment={GetId:()=> 'old',GetText:()=>w.args.comment,GetAuthorName:()=> '法务审阅员',GetQuoteText:()=> '付款五日',GetUserId:()=> 'user',GetRepliesCount:()=>replies,IsSolved:()=>false,Delete:()=>{oldPresent=false;return true}};
 doc.GetAllComments=()=>oldPresent?[oldComment]:[];
 doc.GetCommentById=id=>id==='old'&&oldPresent?oldComment:null;
 if(mode==='COMMENT')p.ToJSON=()=>JSON.stringify({content:[{type:'run',content:[w.text]},{type:'commentRangeStart'},{type:'commentRangeEnd'}]});
 else {w.args.mode='COMMENT';p.ToJSON=()=>JSON.stringify({changes:[{}],content:[{type:'run',content:[w.text],reviewType:'add'}]})}
 return {...w,doc,p,counts:()=>w.counts,oldPresent:()=>oldPresent,reply:()=>replies++};
}
test('list targets keep saved source coordinates during comment and revision continuations',async()=>{
 for(const mode of ['COMMENT','MODIFY']){
  const w=continuationFixture(mode);listWriteTarget(w);
  assert.equal((await w.f.call('applyProposal',w.args)).status,'applied',mode);
  assert.deepEqual(w.counts(),{writes:mode==='COMMENT'?1:0,comments:1,bookmarks:1});
 }
});
test('comment continuation migrates an untouched own comment after tracked replacement',async()=>{
 const w=continuationFixture('COMMENT');
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');
 assert.deepEqual(w.counts(),{writes:1,comments:1,bookmarks:1});assert.equal(w.oldPresent(),false);
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');assert.equal(w.counts().comments,1);
});
test('comment continuation refuses replies, ambiguous threads and stale bookmarks without mutation',async()=>{
 for(const reason of ['reply','ambiguous','bookmark']){
  const w=continuationFixture('COMMENT');
  if(reason==='reply')w.reply();
  if(reason==='ambiguous'){const old=w.doc.GetAllComments()[0];w.doc.GetAllComments=()=>[old,{...old,GetId:()=> 'other'}]}
  if(reason==='bookmark')w.doc.GetBookmark=()=>null;
  assert.equal((await w.f.call('applyProposal',w.args)).status,'rejected');assert.equal(w.counts().writes,0);
 }
});
test('modify continuation can add comment to a verified bookmark over pending tracked text',async()=>{
 const w=continuationFixture('MODIFY');
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');
 assert.deepEqual(w.counts(),{writes:0,comments:1,bookmarks:1});
});
test('inspectProposal distinguishes receipts, saved markers, clean absence and uncertain dirty state',async()=>{
 const w=writeFixture(),doc=w.f.context.window.AscBuilder.sb.GetDocument();doc.GetBookmark=()=>null;
 const query={id:w.args.id,bookmark:w.args.bookmark};
 assert.equal((await w.f.call('inspectProposal',query)).status,'absent');
 w.f.sdk.isDocumentModified=()=>true;
 assert.equal((await w.f.call('inspectProposal',query)).status,'uncertain');
 w.f.sdk.isDocumentModified=()=>false;doc.GetBookmark=()=>({});
 assert.equal((await w.f.call('inspectProposal',query)).status,'present');
 doc.GetBookmark=()=>null;await w.f.call('applyProposal',w.args);
 assert.equal((await w.f.call('inspectProposal',query)).status,'present');
});


test('failed comment migration retains the original thread and an uncertain receipt',async()=>{
 const w=continuationFixture('COMMENT'),search=w.p.Search;
 w.p.Search=q=>search(q).map(r=>({...r,AddComment:()=>null}));
 assert.equal((await w.f.call('applyProposal',w.args)).status,'uncertain');
 assert.equal(w.oldPresent(),true);assert.equal(w.counts().writes,1);
 assert.equal((await w.f.call('inspectProposal',{id:w.args.id,bookmark:w.args.bookmark})).status,'uncertain');
 assert.equal((await w.f.call('applyProposal',w.args)).status,'uncertain');assert.equal(w.counts().writes,1);
});


test('saved OOXML comment IDs are never used as runtime SDK comment IDs',async()=>{
 const w=continuationFixture('COMMENT'),comment=w.doc.GetAllComments()[0];
 const lookups=[];comment.GetId=()=> '614492515';
 w.doc.GetCommentById=id=>{lookups.push(id);return id==='614492515'&&w.oldPresent()?comment:null};
 w.args.continuation.ooxml_comment_id='0';
 w.args.continuation.comment_id='0'; // Legacy serialized proof must also be ignored.
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');
 assert.equal(lookups.includes('0'),false);assert.equal(w.oldPresent(),false);
});
test('explicit runtime comment ID must still match verified comment content',async()=>{
 const w=continuationFixture('COMMENT');w.args.continuation.runtime_comment_id='missing';
 assert.equal((await w.f.call('applyProposal',w.args)).status,'rejected');assert.equal(w.counts().writes,0);
});


test('tracked result binding uses bounded selection JSON when GetText includes deleted text',async()=>{
 const w=writeFixture(),p=w.f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0],search=p.Search;
 p.Search=q=>search(q).map(r=>({...r,GetText:()=>q===w.args.after_text?q+'旧删除内容':q}));
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');assert.equal(w.counts.comments,1);
});
test('invalid or mismatched selection JSON never receives a success receipt',async()=>{
 for(const content of [[{type:'hyperlink',content:['付款十日']}],[{type:'run',content:['错误文字']}],[{type:'run',content:[{}]}]]){
  const w=writeFixture(),p=w.f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0],search=p.Search;
  p.Search=q=>search(q).map(r=>q===w.args.after_text?{...r,ToJSON:()=>JSON.stringify({type:'document',content:[{type:'paragraph',content}]})}:r);
  assert.equal((await w.f.call('applyProposal',w.args)).status,'uncertain');assert.equal(w.counts.comments,0);
 }
});
test('continuation validates bounded bookmark JSON despite deleted GetText suffix',async()=>{
 const w=continuationFixture('MODIFY'),get=w.doc.GetBookmark;
 w.doc.GetBookmark=name=>{const b=get(name);if(!b)return b;return {GetRange:()=>({...b.GetRange(),GetText:()=> '付款五日旧删除文字'})}};
 assert.equal((await w.f.call('applyProposal',w.args)).status,'applied');assert.equal(w.counts().writes,0);
});

test('explicit navigation locates an exact unique paragraph despite unrelated structure mismatch',async()=>{
 const f=fixture({texts:['编辑器中的不同标题','付款原文','结尾']});
 const blocks=[{id:'v:a',text:'解析器标题'},{id:'v:b',text:'付款原文'},{id:'v:c',text:'结尾'}];
 assert.equal((await f.call('bindAnchors',{version:'v',blocks})).status,'mapping_mismatch');
 const r=await f.call('bindAnchors',{version:'v',blocks,allowPartial:true});assert.equal(r.status,'bound');assert.equal(r.partial,true);assert.equal(r.mapped,2);
 const got=await f.call('locate',{version:'v',blockId:'v:b',paragraph:'付款原文',quote:'付款',start:0,end:2});
 assert.equal(got.status,'located');assert.equal(f.selection.index,1);
 // A subsequent strict bind (used for writes) must still fail and discard this map.
 assert.equal((await f.call('bindAnchors',{version:'v',blocks})).status,'mapping_mismatch');
 assert.equal((await f.call('locate',{version:'v',blockId:'v:b',paragraph:'付款原文',quote:'付款',start:0,end:2})).status,'mapping_missing');
})
test('partial binding rejects duplicates on either side and distinguishes missing paragraphs',async()=>{
 for(const [texts,source] of [[['标题变化','重复','重复'],['标题','重复']],[['标题变化','重复'],['标题','重复','重复']]]){
  const f=fixture({texts}),blocks=source.map((text,i)=>({id:'v:p'+i,text}));
  await f.call('bindAnchors',{version:'v',blocks,allowPartial:true});
  assert.equal((await f.call('locate',{version:'v',blockId:'v:p1',paragraph:'重复',quote:'重复',start:0,end:2})).status,'ambiguous');
  assert.equal((await f.call('locate',{version:'v',blockId:'v:p0',paragraph:'标题',quote:'标题',start:0,end:2})).reason,'paragraph_missing');
  assert.equal(f.selection,null);assert.equal(f.scroll.Ssa,0);
 }
})
test('partial mapping still enforces offsets and dirty-document protection',async()=>{
 const f=fixture({texts:['不同标题','😀付款原文']}),blocks=[{id:'v:a',text:'标题'},{id:'v:b',text:'😀付款原文'}];
 await f.call('bindAnchors',{version:'v',blocks,allowPartial:true});
 const target={version:'v',blockId:'v:b',paragraph:'😀付款原文',quote:'付款',start:0,end:2};
 assert.equal((await f.call('locate',target)).reason,'invalid_offsets');assert.equal(f.selection,null);
 assert.equal((await f.call('locate',{...target,start:1,end:3})).status,'located');
 f.dirty();assert.equal((await f.call('locate',{...target,start:1,end:3})).status,'stale');
})

function trackedNavigationFixture(){
 const f=fixture({texts:['甲😀旧乙旧丙']}),doc=f.context.window.AscBuilder.sb.GetDocument(),p=doc.GetAllParagraphs()[0],original=p.GetRange;
 const tokens=[null,['甲'],['😀'],['旧','remove'],null,['乙'],['旧','remove'],['丙'],null];let selected;
 const json=(a,b)=>({type:'document',content:[{type:'paragraph',content:tokens.slice(a,b).filter(Boolean).map(([text,reviewType='common'])=>({type:'run',reviewType,content:[text]}))}]});
 p.ToJSON=()=>JSON.stringify(json(0,tokens.length).content[0]);
 p.GetRange=(a=0,b=tokens.length)=>({GetStartPos:()=>100+a,GetEndPos:()=>100+b,GetStartPage:()=>0,GetEndPage:()=>0,GetText:()=>tokens.slice(a,b).filter(Boolean).map(t=>t[0]).join('')+'旧删除尾文',ToJSON:()=>JSON.stringify(json(a,b)),Select(){selected=this;original(a,b).Select()}});
 p.Search=()=>[];doc.GetRangeBySelect=()=>selected;
 const text='甲😀乙丙',blocks=[{id:'v:p0',text}];
 return {f,p,doc,bind:()=>f.call('bindAnchors',{version:'v',blocks}),locate:(start,end)=>f.call('locate',{version:'v',blockId:'v:p0',paragraph:text,quote:[...text].slice(start,end).join(''),start,end}),selected:()=>selected};
}
test('native navigation spans tracked deletions using verified SDK boundaries and proposed selection text',async()=>{
 const x=trackedNavigationFixture();assert.equal((await x.bind()).mapped,1);
 assert.equal((await x.locate(0,4)).status,'located');assert.equal(x.selected().GetEndPos(),108);
 assert.equal((await x.locate(1,3)).status,'located');assert.equal(x.selected().GetStartPos(),102);assert.equal(x.selected().GetEndPos(),106);
 assert.equal(x.f.sdk.isDocumentModified(),false);
})
test('proposed-range fallback refuses unsupported structures and mismatching selected JSON',async()=>{
 const x=trackedNavigationFixture();await x.bind();const original=x.p.GetRange;
 x.p.GetRange=(...args)=>({...original(...args),ToJSON:()=>JSON.stringify({type:'document',content:[{type:'paragraph',content:[{type:'hyperlink',content:['甲😀乙丙']}]}]})});
 assert.equal((await x.locate(0,4)).reason,'range_text_mismatch');assert.equal(x.f.selection,null);
 const y=trackedNavigationFixture();await y.bind();y.doc.GetRangeBySelect=()=>({ToJSON:()=>JSON.stringify({type:'document',content:[{type:'paragraph',content:[{type:'run',content:['错误原文']}]}]})});
 assert.equal((await y.locate(0,4)).reason,'selected_text_mismatch');
})

test('local review app on port 5190 completes the verified bridge handshake',async()=>{const f=fixture({origin:'http://127.0.0.1:5190'});await f.bind();assert.equal((await present(f)).status,'presented')})

test('local review app on port 9174 registers the bridge and answers hello',async()=>{const f=fixture({origin:'http://127.0.0.1:9174'});f.document.documentElement={classList:{add(){}}};const hello=await f.call('hello');assert.equal(hello.navigationVersion,33);assert.equal(hello.structuredAnchors,true)})

test('navigation preserves native full-width spaces lost by range serialization',async()=>{
 for(const text of ['地址：\u3000','地址：甲\u3000乙']){
  const f=fixture({texts:[text]});
  const p=f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0],getRange=p.GetRange;
  p.Search=()=>[];
  p.GetRange=(...args)=>{
   const range=getRange(...args);
   return {...range,
    GetText:()=>range.GetText()+(args.length?'':'\r\n'),
    ToJSON:()=>JSON.stringify({type:'paragraph',content:[{type:'run',content:[range.GetText().replaceAll('\u3000',' ')]}]}),
   };
  };
  const selected=f.sdk.asc_GetSelectedText;
  f.sdk.asc_GetSelectedText=()=>selected().replaceAll('\u3000',' ');
  await f.bind();
  assert.equal((await f.locate()).status,'located');
  assert.deepEqual(f.selection,{index:0,start:0,end:[...text].length});
 }
});

test('a date search hit outside its signed cell falls back to the verified paragraph range',async()=>{
 const date='日期：',f=fixture({texts:[date+'\t',date]});
 const [first,second]=f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs();
 first.Search=quote=>second.Search(quote);
 const blocks=[{id:'v:client-date',text:date},{id:'v:provider-date',text:date}];
 assert.equal((await f.call('bindAnchors',{version:'v',blocks})).mapped,2);
 const result=await f.call('locate',{version:'v',blockId:blocks[0].id,paragraph:date,quote:date,start:0,end:3});
 assert.equal(result.status,'located');
 assert.deepEqual(f.selection,{index:0,start:0,end:3});
})

test('date navigation restores one lost selection and refuses an identical quote in the other cell',async()=>{
 const date='日期：',f=fixture({texts:[date,date]});
 const doc=f.context.window.AscBuilder.sb.GetDocument(),readSelection=doc.GetRangeBySelect;
 const other=doc.GetAllParagraphs()[1].GetRange(0,3);
 await f.bind();
 let firstRead=true;
 doc.GetRangeBySelect=()=>{
  if(firstRead){firstRead=false;return other}
  return readSelection();
 };
 assert.equal((await f.locate(0)).status,'located');
 assert.equal(f.selectionPaints,2);
 doc.GetRangeBySelect=()=>other;
 const failed=await f.locate(0);
 assert.equal(failed.reason,'selected_text_mismatch');
 assert.deepEqual([failed.blockId,failed.sourceStart,failed.sourceEnd],['v:p0',0,3]);
})

test('table terminators use the same identity in full and partial navigation',async()=>{
 const f=fixture({texts:['45天全省负荷预测\t','编辑器标题','未来7日\t']});
 const blocks=[{id:'v:a',text:'45天全省负荷预测'},{id:'v:b',text:'解析器标题'},{id:'v:c',text:'未来7日'}];
 const bound=await f.call('bindAnchors',{version:'v',blocks,allowPartial:true});
 assert.equal(bound.mapped,2);assert.equal(bound.partial,true);
 for(const b of [blocks[0],blocks[2]])assert.equal((await f.call('locate',{version:'v',blockId:b.id,paragraph:b.text,quote:b.text,start:0,end:[...b.text].length})).status,'located');
 assert.equal(f.sdk.isDocumentModified(),false);
});
test('unrelated missing text preserves ordered duplicate matches on both sides',async()=>{
 const f=fixture({texts:['甲\t','1\t','乙\t','1\t','编辑器独有段落','丙\t','1\t']});
 const blocks=['甲','1','乙','1','不存在','丙','1'].map((text,i)=>({id:'v:p'+i,text}));
 const bound=await f.call('bindAnchors',{version:'v',blocks,allowPartial:true});assert.equal(bound.mapped,6);
 for(const i of [1,3,6]){const b=blocks[i];assert.equal((await f.call('locate',{version:'v',blockId:b.id,paragraph:b.text,quote:'1',start:0,end:1})).status,'located');assert.equal(f.selection.index,i)}
});
test('canonical collisions remain ambiguous instead of merging whitespace variants',async()=>{
 const f=fixture({texts:['变更','重复','重复\t']});
 const blocks=[{id:'v:a',text:'旧标题'},{id:'v:b',text:'重复'}];
 await f.call('bindAnchors',{version:'v',blocks,allowPartial:true});
 assert.equal((await f.call('locate',{version:'v',blockId:'v:b',paragraph:'重复',quote:'重复',start:0,end:2})).status,'ambiguous');assert.equal(f.selection,null);
});
test('numbering cannot justify invented source tabs during navigation',async()=>{
 const f=fixture({texts:['😀验收款']});const p=f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0];
 p.ToJSON=()=>JSON.stringify({pPr:{numPr:{numId:'1'}},content:[{type:'run',content:['😀验收款']}]});
 const b={id:'v:p',text:'\t\t😀验收款'};
 assert.equal((await f.call('bindAnchors',{version:'v',blocks:[b]})).status,'mapping_mismatch');
 assert.equal((await f.call('bindAnchors',{version:'v',blocks:[b],allowPartial:true})).mapped,0);
 assert.equal((await f.call('locate',{version:'v',blockId:b.id,paragraph:b.text,quote:'验收款',start:3,end:6})).status,'not_found');
 assert.equal(f.selection,null);assert.equal(f.sdk.isDocumentModified(),false);
});
test('list projection rejects ordinary paragraphs and never strips internal whitespace',async()=>{
 for(const text of ['验收款','验 收款']){
  const f=fixture({texts:[text]}),b={id:'v:p',text:'\t验收款'};
  const bound=await f.call('bindAnchors',{version:'v',blocks:[b],allowPartial:true});assert.equal(bound.mapped,0);
 }
 const f=fixture({texts:['验 收款']}),p=f.context.window.AscBuilder.sb.GetDocument().GetAllParagraphs()[0];
 p.ToJSON=()=>JSON.stringify({pPr:{numPr:{numId:'1'}},content:[]});
 assert.equal((await f.call('bindAnchors',{version:'v',blocks:[{id:'v:p',text:'\t验收款'}],allowPartial:true})).mapped,0);
});
