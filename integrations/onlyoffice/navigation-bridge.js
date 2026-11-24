/* Version-pinned, allowlisted host bridge. No eval or generic SDK proxy. */
(function(){
 'use strict';
 const protocol='rixin-editor-v1',build='10.0.0-labesign9';
 const origin=new URLSearchParams(location.search).get('parentOrigin');
 if(!['http://127.0.0.1:5173','http://127.0.0.1:5174','http://127.0.0.1:5175','http://127.0.0.1:5190','http://127.0.0.1:9174','http://127.0.0.1:18084'].includes(origin))return;
 let composing=false,held=false,busy=false,restoreRestriction=0,modeRestriction=0;
 document.addEventListener('compositionstart',()=>{composing=true},true);
 document.addEventListener('compositionend',()=>{composing=false},true);
 const block=e=>{if(held){e.preventDefault();e.stopImmediatePropagation()}};
 ['keydown','beforeinput','paste','drop','pointerdown','mousedown','click'].forEach(x=>document.addEventListener(x,block,true));
 let navigation=0,binding=null,marks=[],focusMarks=[],presentation=null,overlayFrame=0,paintKey='',overlayNodes=new Map();
 const api=()=>window.Asc?.editor;
 document.addEventListener('wheel',()=>userInteraction(),{passive:true,capture:true});
 const frame=()=>new Promise(resolve=>{
   let settled=false,raf;const finish=rendered=>{if(settled)return;settled=true;clearTimeout(timer);if(!rendered&&typeof cancelAnimationFrame==='function')cancelAnimationFrame(raf);resolve(rendered)};
   const timer=setTimeout(()=>finish(false),60);raf=requestAnimationFrame(()=>finish(true));
 });
 // Office API wrappers are available through this pinned build's namespace.
 // Never expose an arbitrary method or command evaluator to the host.
 const rawParagraphText=p=>p.GetText({Numbering:false,NewLineSeparator:'\n'}).replace(/\r?\n$/,'');
 function runText(content){
   if(!Array.isArray(content))return null;
   let result='';for(const token of content){
     if(typeof token==='string')result+=token;
     else if(token?.type==='tab')result+='\t';
     else if(token?.type==='break'&&['line','page','column'].includes(token.breakType))result+='\n';
     else return null;
   }return result;
 }
 function paragraphText(p){
   const raw=rawParagraphText(p);
   // Builder GetText includes tracked deletions. For simple paragraphs, align the
   // proposed view with the server parser. Unknown inline structures fail closed.
   if(typeof p.ToJSON!=='function')return raw;
   try{const j=JSON.parse(p.ToJSON());if(!j.content?.some(n=>n.reviewType==='remove'))return raw;
     const valid=j.content.every(n=>['run','endRun','commentRangeStart','commentRangeEnd','bookmarkStart','bookmarkEnd'].includes(n.type)&&(!n.content||runText(n.content)!==null));
     return valid?j.content.filter(n=>n.reviewType!=='remove'&&n.type==='run').map(n=>runText(n.content||[])).join(''):raw;
   }catch{return raw}
 }
 const comparable=t=>t.replace(/[ \t\r\n]+$/,'');
 function paragraphs(){
   const get=window.AscBuilder?.sb?.GetDocument;
   if(typeof get!=='function')return null;
   return get().GetAllParagraphs().map(p=>({p,text:paragraphText(p)})).filter(x=>x.text.trim());
 }
 function bindAnchors(args){
   binding=null;clearEvidence();
   if(typeof args.version!=='string'||!Array.isArray(args.blocks)||!args.blocks.length||args.blocks.length>5000)return {status:'invalid_request'};
   const blocks=args.blocks,ids=new Set();let size=0;
   for(const b of blocks){if(typeof b.id!=='string'||!b.id.startsWith(args.version+':')||ids.has(b.id)||typeof b.text!=='string'||!b.text.trim()||(size+=b.text.length)>3000000)return {status:'invalid_request'};ids.add(b.id)}
   const rows=paragraphs();if(!rows)return {status:'unsupported'};
   const byText=new Map();
   rows.forEach((row,index)=>{row.index=index;const key=comparable(row.text);if(!byText.has(key))byText.set(key,[]);byText.get(key).push(index)});
   // Source v3 excludes paragraph properties. Leading body tabs are real text;
   // numbering is never evidence that a mismatching character may be discarded.
   const candidates=blocks.map(b=>byText.get(comparable(b.text))||[]);
   function embedding(indices){
     const first=new Map(),last=new Map();let j=-1;
     for(const i of indices){const found=candidates[i].find(k=>k>j);if(found===undefined)return {failed:i};first.set(i,found);j=found}
     j=rows.length;
     for(const i of [...indices].reverse()){const found=candidates[i].findLast(k=>k<j);last.set(i,found);j=found}
     return {first,last};
   }
   const indices=blocks.map((_,i)=>i),full=embedding(indices);
   if(full.failed!==undefined&&args.allowPartial!==true)return {status:'mapping_mismatch',sourceIndex:full.failed};
   // Missing text cannot poison other ordered matches. Keep only positions shared
   // by the earliest AND latest complete embedding of all remaining sources.
   const ordered=full.failed===undefined?full:embedding(indices.filter(i=>candidates[i].length));
   const useCount=new Map();for(const cs of candidates)for(const j of cs)useCount.set(j,(useCount.get(j)||0)+1);
   const entries=new Map(),failures=new Map();
   blocks.forEach((b,i)=>{
     const cs=candidates[i];let j;
     if(ordered.first?.has(i)&&ordered.first.get(i)===ordered.last.get(i))j=ordered.first.get(i);
     // Reordering or a missing duplicate prevents a full embedding. Only unique
     // one-to-one text identities remain usable; never choose the nth duplicate.
     else if(!ordered.first&&cs.length===1&&useCount.get(cs[0])===1)j=cs[0];
     if(j!==undefined){
       entries.set(b.id,{...rows[j],source:b.text});
     }else failures.set(b.id,cs.length?{status:'ambiguous',reason:'paragraph_mapping'}:{status:'not_found',reason:'paragraph_missing'});
   });
   binding={version:args.version,entries,failures};
   return {status:'bound',mapped:entries.size,total:blocks.length,unresolved:[...failures.keys()],
     ...(full.failed!==undefined?{partial:true,sourceIndex:full.failed}:{})};
 }
 // Search uses the marked-up text and cannot find a quote spanning a deletion.
 // For navigation, derive SDK offsets from verified proposed-text prefixes. SDK
 // positions include run boundaries, so Unicode offsets cannot be used directly.
 function proposedRange(p,paragraph,start,end,quote){
   try{
     const full=p.GetRange(),text=navigationRangeText(full);
     if(text===null||comparable(text)!==paragraph)return null;
     const max=full.GetEndPos()-full.GetStartPos();
     if(!Number.isInteger(max)||max<0||max>300000)return null;
     const boundary=offset=>{
       if(offset===0)return 0;
       let lo=0,hi=max;
       while(lo<hi){const mid=Math.floor((lo+hi)/2),text=navigationRangeText(p.GetRange(0,mid));if(text===null)throw Error('unsupported range');if(Array.from(text).length<offset)lo=mid+1;else hi=mid}
       if(navigationRangeText(p.GetRange(0,lo))!==Array.from(paragraph).slice(0,offset).join(''))throw Error('invalid prefix');
       return lo;
     };
     const range=p.GetRange(boundary(start),boundary(end));
     return navigationRangeText(range)===quote?range:null;
   }catch{return null}
 }
 function rangeBounds(range){
   const start=range?.GetStartPos?.(),end=range?.GetEndPos?.();
   return Number.isInteger(start)&&Number.isInteger(end)&&end>start?{start,end}:null;
 }
 // Source and native text share content-only coordinates; never clip a write.
 function writeAnchor(args,entry){
   const {paragraph,quote,start,end}=args;
   if(!entry||typeof paragraph!=='string'||paragraph.length>30000||typeof quote!=='string'||!quote||entry.source!==paragraph||paragraphText(entry.p)!==entry.text)return null;
   const chars=Array.from(paragraph);
   if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<=start||end>chars.length||chars.slice(start,end).join('')!==quote||paragraph!==entry.text)return null;
   return {paragraph,quote,start,end};
 }
 function resolveRange(args,allowProposedRange=false){
     let {paragraph,quote}=args;
     if(typeof paragraph!=='string'||typeof quote!=='string'||paragraph.length>30000||!quote)return {status:'not_found',reason:'invalid_anchor'};
     let entry,start=args.start,end=args.end;
     if(args.blockId){
       if(!binding||binding.version!==args.version)return {status:'mapping_missing'};
       entry=binding.entries.get(args.blockId);if(!entry)return binding.failures?.get(args.blockId)||{status:'ambiguous',reason:'paragraph_mapping'};
       if(entry.source!==paragraph)return {status:'stale',reason:'source_changed'};
     }else{
       const rows=paragraphs();if(!rows)return {status:'unsupported'};
       const matches=rows.filter(x=>x.text===paragraph);
       if(matches.length!==1)return {status:matches.length?'ambiguous':'not_found',reason:'paragraph_mapping',matches:matches.length};
       entry=matches[0];const found=paragraph.indexOf(quote);
       if(found<0)return {status:'not_found'};
       if(paragraph.indexOf(quote,found+1)>=0)return {status:'ambiguous',reason:'quote_mapping'};
       start=Array.from(paragraph.slice(0,found)).length;end=start+Array.from(quote).length;
     }
     if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<=start||end>Array.from(paragraph).length||Array.from(paragraph).slice(start,end).join('')!==quote)return {status:'not_found',reason:'invalid_offsets'};
     if(paragraphText(entry.p)!==entry.text){binding=null;return {status:'stale',reason:'paragraph_changed'}}
     if(allowProposedRange){
       const sourceChars=Array.from(paragraph),limit=Array.from(comparable(paragraph)).length;
       if(comparable(paragraph)!==comparable(entry.text))return {status:'stale',reason:'source_changed'};
       // Source offsets are validated above BEFORE converting to the native view.
       // Only boundary formatting is excluded; internal whitespace is untouched.
       const begin=start,finish=Math.min(end,limit);
       if(begin>=finish)return {status:'not_found',reason:'invalid_offsets'};
       paragraph=sourceChars.slice(0,limit).join('');quote=sourceChars.slice(begin,finish).join('');
       start=begin;end=finish;
     }
     // SDK range positions include non-text inline elements. Resolve actual ranges
     // inside the verified paragraph, then match the exact source occurrence.
     const offsets=[];let at=0;
     while((at=paragraph.indexOf(quote,at))>=0){offsets.push(Array.from(paragraph.slice(0,at)).length);at+=quote.length}
     const occurrence=offsets.indexOf(start);
     const ranges=entry.p.Search(quote,true).sort((a,b)=>a.GetStartPos()-b.GetStartPos());
     const scope=allowProposedRange?rangeBounds(entry.p.GetRange()):null;
     function matches(range){
       if(range.GetText({Numbering:false})!==quote)return false;
       if(!allowProposedRange)return true;
       const bounds=rangeBounds(range);
       return scope&&bounds&&bounds.start>=scope.start&&bounds.end<=scope.end;
     }
     const searchMatch=occurrence>=0&&ranges.length===offsets.length&&ranges.every(matches);
     const range=searchMatch?ranges[occurrence]:allowProposedRange?proposedRange(entry.p,paragraph,start,end,quote):null;
     return range?{range,entry,quote,paragraph,start,end}:{status:'not_found',reason:'range_text_mismatch'};
 }
 function matchesSelection(range,quote){
   const selectedRange=window.AscBuilder?.sb?.GetDocument?.()?.GetRangeBySelect?.();
   const expected=rangeBounds(range),actual=rangeBounds(selectedRange);
   if(!expected||!actual||actual.start!==expected.start||actual.end!==expected.end)return false;
   // Native text can include numbering or a table terminator. Use the bounded
   // selection's projected text when the native representation differs.
   return api().asc_GetSelectedText()===quote||navigationRangeText(selectedRange,true)===quote;
 }
 async function selectRange(range){
   const a=api(),scroll=a?.wa?.MA,viewer=document.getElementById('id_viewer');
   const logic=a?.ye?.();
   if(typeof logic?.wq!=='function')return {centered:false,reason:'selection_rendering_unsupported'};
   const supported=typeof a?.asc_GetSelectionBounds==='function'&&typeof scroll?.scrollBy==='function'&&Number.isFinite(scroll.Ssa)&&viewer;
   const command=++navigation,start=performance.now(),beforeY=supported?scroll.Ssa:0;
   range.Select();
   // Builder Select sets the logical range but does not refresh the native
   // selection canvas. wq is Document_UpdateSelectionState in this pinned build.
   logic.wq();
   const selectionMs=performance.now()-start;
   if(!supported)return {centered:false,reason:'centering_unsupported'};
   // Range.Select scrolls synchronously. Restore before the next paint so there is
   // only one visible transition, not native jump followed by a second correction.
   scroll.scrollBy(0,beforeY-scroll.Ssa);
   const read=()=>{const points=a.asc_GetSelectionBounds(),height=viewer.getBoundingClientRect().height,ys=points.map(p=>p[1]);return {top:Math.min(...ys),bottom:Math.max(...ys),height}};
   let frameFallback=!await frame();const before=read();
   if(!before.height||!Number.isFinite(before.top)||!Number.isFinite(before.bottom))return {centered:false,reason:'bounds_unavailable'};
   const acrossPages=typeof range.GetStartPage==='function'&&typeof range.GetEndPage==='function'&&range.GetStartPage()!==range.GetEndPage();
   const long=acrossPages||before.bottom-before.top>before.height*.8,point=b=>long?b.top:(b.top+b.bottom)/2;
   const offset=point(before)-before.height/2;
   // Near targets move smoothly; long distances switch directly rather than fly
   // through pages the reader did not ask to inspect.
   const duration=frameFallback||matchMedia('(prefers-reduced-motion: reduce)').matches||Math.abs(offset)>before.height*1.5?0:280;
   let moved=0,frames=0;const animationStart=performance.now();
   do{const rendered=await frame();if(!rendered)frameFallback=true;if(command!==navigation)return {centered:false,interrupted:true};const progress=duration&&rendered?Math.min(1,(performance.now()-animationStart)/duration):1;const eased=progress<.5?4*progress**3:1-(-2*progress+2)**3/2;const desired=offset*eased;scroll.scrollBy(0,desired-moved);moved=desired;frames++;if(progress===1)break}while(true);
   await frame();await frame();if(command!==navigation)return {centered:false,interrupted:true};let after=read(),boundary=false;
   if(Math.abs(point(after)-after.height/2)>2){const prior=point(after);scroll.scrollBy(0,prior-after.height/2);await frame();after=read();boundary=Math.abs(point(after)-prior)<1}
   await frame();const final=read(),error=Math.abs(point(final)-final.height/2),stable=Math.abs(point(final)-point(after))<1;
   if(command!==navigation)return {centered:false,interrupted:true};
   return {centered:stable&&error<=2,centerError:error,boundary:stable&&boundary,stable,alignment:long?'start':'center',transition:duration&&!frameFallback?'smooth':'direct',frameFallback,frames,selectionMs:Math.round(selectionMs*10)/10,durationMs:Math.round(performance.now()-start)};
 }


 // Geometry is document-relative; user selection and DOCX formatting are not decorations.
 function clearEvidence(){navigation++;marks=[];focusMarks=[];presentation=null;paintKey='';overlayNodes.clear();if(overlayFrame&&typeof cancelAnimationFrame==='function')cancelAnimationFrame(overlayFrame);overlayFrame=0;document.getElementById('rixin-evidence-layer')?.remove()}
 const canSetEvidenceScroll=s=>typeof s?.scrollTo==='function'&&s.kg?.cY===true&&s.kg?.D0===false&&Number.isFinite(s.qZd);
 const setEvidenceScroll=(s,y)=>s.scrollTo(0,Math.max(0,Math.min(s.qZd,y)));
 function projectEvidence(m){
   const drawing=api()?.ye?.()?.vo?.(),scroll=api()?.wa?.MA;
   if(!m.fragments&&m.zoom!==api()?.wa?.rp)return null;
   if(!m.fragments)return {...m,rects:[{left:m.startX,top:m.startY-scroll.Ssa,width:4,height:28}],precise:false};
   const rects=m.fragments.map(r=>{
     const page=drawing?.cl?.[r.page],p=page?.zp;
     if(!p||page.Cw!==r.pageWidth||page.mz!==r.pageHeight)return null;
     const sx=(p.right-p.left)/page.Cw,sy=(p.bottom-p.top)/page.mz;
     return {page:r.page,left:p.left+r.x*sx,top:p.top+r.y*sy,width:r.w*sx,height:r.h*sy};
   });
   if(rects.some(r=>!r||![r.left,r.top,r.width,r.height].every(Number.isFinite)))return null;
   const left=Math.min(...rects.map(r=>r.left)),right=Math.max(...rects.map(r=>r.left+r.width)),top=Math.min(...rects.map(r=>r.top))+scroll.Ssa,bottom=Math.max(...rects.map(r=>r.top+r.height))+scroll.Ssa;
   return {...m,rects,left,right,top,bottom,startX:rects[0].left,startY:rects[0].top+scroll.Ssa,precise:true};
 }
 function measureEvidence(range,target,role){
   const a=api(),scroll=a?.wa?.MA,logic=a?.ye?.(),drawing=logic?.vo?.();
   // Az/xB are this build's native selection-state snapshot/restore, including direction.
   if(!canSetEvidenceScroll(scroll)||a.asc_getSelectedDrawingObjectsCount?.()>0||composing||typeof logic?.Az!=='function'||typeof logic?.xB!=='function'||typeof logic?.$p!=='function'||typeof drawing?.uba!=='boolean'||typeof a.G9e!=='boolean')return null;
   const saved=logic.Az(),selected=a.asc_GetSelectedText(),y=scroll.Ssa,active=document.activeElement;
   const original=drawing.lWb,transform=drawing.T_,outline=drawing.GWc,fragments=[],seen=new Set();let unsupported=false,result;
   try{
     const first=range.GetStartPage?.(),last=range.GetEndPage?.();
     range.Select();if(a.asc_GetSelectedText()!==target.quote)return null;
     const points=a.asc_GetSelectionBounds();if(!Array.isArray(points)||points.length<2)return null;
     result={role,blockId:target.blockId,zoom:a.wa.rp,startX:points[0][0],startY:points[0][1]+scroll.Ssa,crossPage:first!==last};
     if(typeof logic.KK==='function'&&typeof original==='function'&&Number.isInteger(first)&&Number.isInteger(last)&&first>=0&&last>=first&&last-first<32){
       drawing.lWb=function(page,x,y,w,h){
         const p=this.cl?.[page];
         if(this.T_||!p||![page,x,y,w,h,p.Cw,p.mz].every(Number.isFinite)||w<0||h<=0||p.Cw<=0||p.mz<=0){unsupported=true;return}
         const key=[page,x,y,w,h].join(':');if(seen.has(key)||!w)return;seen.add(key);
         if(seen.size>1500){unsupported=true;return}
         fragments.push({page,x,y,w,h,pageWidth:p.Cw,pageHeight:p.mz});
       };
       // Collect only geometry. Do not change native outline settings while measuring.
       if(typeof outline==='function')drawing.GWc=()=>{};
       for(let page=first;page<=last;page++)logic.KK(page);
     }
     if(!unsupported&&fragments.length)result.fragments=fragments.sort((a,b)=>a.page-b.page||a.y-b.y||a.x-b.x);
   }finally{
     drawing.lWb=original;drawing.T_=transform;drawing.GWc=outline;
     logic.xB(saved);
     const suppress=a.G9e,update=drawing.uba;
     try{a.G9e=true;drawing.uba=true;logic.$p()}finally{drawing.uba=update;a.G9e=suppress;setEvidenceScroll(scroll,y)}
     if(active&&active!==document.activeElement&&typeof active.focus==='function')active.focus({preventScroll:true});
   }
   if(a.asc_GetSelectedText()!==selected)throw Error('原选区恢复未确认');
   return result?projectEvidence(result):null;
 }
 const phaseLabels={queued:'等待核查',checking:'正在核查',settling:'等待核查意见',attention:'有意见待核对',incomplete:'核查未完成',finished:'本项核查已结束',context:'正在查看原文'};
 function paintEvidence(){
   if(!marks.length)return;
   const viewport=document.getElementById('id_viewer')?.getBoundingClientRect();if(!viewport)return;
   const projected=marks.map(projectEvidence),scope=focusMarks.map(projectEvidence);
   if([...projected,...scope].some(m=>!m)){clearEvidence();return}
   const key=JSON.stringify([viewport.left,viewport.top,viewport.width,viewport.height,presentation,projected.map(m=>m.rects),scope.map(m=>m.rects)]);
   if(key===paintKey)return;paintKey=key;
   let layer=document.getElementById('rixin-evidence-layer');
   if(!layer){layer=document.createElement('div');layer.id='rixin-evidence-layer';document.body.append(layer)}
   layer.style.cssText=`position:fixed;pointer-events:none;overflow:hidden;z-index:6000;left:${viewport.left}px;top:${viewport.top}px;width:${viewport.width}px;height:${viewport.height}px`;
   const used=new Set();
   const draw=(key,style,data,text)=>{
     used.add(key);let node=overlayNodes.get(key);if(!node){node=document.createElement('div');overlayNodes.set(key,node);layer.append(node)}
     Object.assign(node.dataset,data);node.style.cssText=style;if(text!==undefined&&node.textContent!==text)node.textContent=text;
   };
   const visible=r=>r.top+r.height>0&&r.top<viewport.height&&r.left+r.width>0&&r.left<viewport.width;
   // Scope rectangles are per paragraph/page, never a rectangle spanning page gaps.
   for(const [i,m] of scope.entries())if(m.precise){
     const pages=new Map();for(const r of m.rects){const b=pages.get(r.page);pages.set(r.page,b?{left:Math.min(b.left,r.left),top:Math.min(b.top,r.top),right:Math.max(b.right,r.left+r.width),bottom:Math.max(b.bottom,r.top+r.height)}:{left:r.left,top:r.top,right:r.left+r.width,bottom:r.top+r.height})}
     for(const [page,b] of pages){const r={...b,width:b.right-b.left,height:b.bottom-b.top};if(visible(r))draw(`scope:${i}:${page}`,`position:absolute;left:${r.left-7}px;top:${r.top-3}px;width:${r.width+14}px;height:${r.height+6}px;background:#8063cf0c;border-left:3px solid #8063cf88;border-radius:3px;box-sizing:border-box`,{role:'scope',shape:'paragraph',blockId:m.blockId})}
   }
   for(const [i,m] of projected.entries())for(const [j,r] of m.rects.entries())if(visible(r)){
     const color=m.role==='current'?'#8063cf':'#bd8c33';
     draw(`evidence:${i}:${j}`,`position:absolute;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;background:${color}${m.precise?'26':''};border-bottom:2px solid ${color};border-radius:2px;box-sizing:border-box`,{blockId:m.blockId,role:m.role,shape:m.precise?'range':'start'});
   }
   const current=projected[0],first=current.rects.find(visible);
   if(first){
     const label=phaseLabels[presentation?.phase]||phaseLabels.context;
     const text=(presentation?.paused?'手动阅读 · ':'')+label+'\n'+(presentation?.title||'当前核查范围')+(current.precise?'':'\n仅标出起点，范围未展开');
     // A quote can start halfway across a line. Its left edge is not the page gutter.
     const paragraphRects=scope.flatMap(m=>m.rects).filter(r=>r.page===first.page);
     const marginLeft=Math.min(first.left,...paragraphRects.map(r=>r.left),...current.rects.filter(r=>r.page===first.page).map(r=>r.left));
     const width=Math.min(108,marginLeft-20),left=Math.max(8,marginLeft-width-12),top=Math.max(8,Math.min(viewport.height-82,first.top));
     // When no readable gutter exists the host still shows status; never cover body text.
     if(width>=48)draw('status',`position:absolute;left:${left}px;top:${top}px;width:${width}px;max-height:82px;overflow:hidden;padding:7px 8px;box-sizing:border-box;border:1px solid #cbbce7;border-radius:6px;background:#f7f3ff;color:#50368b;font:12px/1.5 sans-serif;white-space:pre-line;overflow-wrap:anywhere;box-shadow:0 2px 6px #37215412`,{role:'status',phase:presentation?.phase||'context'},text);
   }
   for(const [key,node] of overlayNodes)if(!used.has(key)){node.remove();overlayNodes.delete(key)}
 }
 function watchEvidence(){
   if(overlayFrame||!marks.length)return;
   overlayFrame=requestAnimationFrame(()=>{overlayFrame=0;if(!marks.length)return;if(api()?.isDocumentModified()||api()?.asc_isDocumentCanSave()){clearEvidence();return}paintEvidence();watchEvidence()});
 }
 async function presentEvidence(args){
   if(api().isDocumentModified()||api().asc_isDocumentCanSave()){clearEvidence();return {status:'stale'}};
   if(!Array.isArray(args.targets)||!args.targets.length||args.targets.length>8||!['never','if-needed','center'].includes(args.reveal))return {status:'invalid_request'};
   const resolved=args.targets.map(target=>({target,result:resolveRange(target)}));
   const failed=resolved.find(x=>!x.result.range);if(failed)return failed.result;
   if(args.context&&(!Object.hasOwn(phaseLabels,args.context.phase)||typeof args.context.title!=='string'||args.context.title.length>200))return {status:'invalid_request'};
   const command=++navigation,measurements=resolved.map((x,i)=>measureEvidence(x.result.range,x.target,i===0?'current':'related'));
   if(measurements.some(x=>!x))return {status:'unsupported',reason:'selection_preservation'};
   const t=args.targets[0],full={...t,quote:t.paragraph,start:0,end:Array.from(t.paragraph).length},scope=resolveRange(full);
   const focus=t.quote===t.paragraph?measurements[0]:scope.range&&measureEvidence(scope.range,full,'scope');
   const scroll=api().wa.MA,viewer=document.getElementById('id_viewer'),height=viewer.getBoundingClientRect().height;
   if(!height)return {status:'unsupported'};
   const initialY=scroll.Ssa;let current=measurements[0];
   const long=!current.precise||current.crossPage||current.bottom-current.top>height*.7;
   const targetY=()=>long?current.startY-height*.25:(current.top+current.bottom)/2-height/2;
   const top=(long?current.startY:current.top)-scroll.Ssa,bottom=current.bottom-scroll.Ssa;
   const visible=long?top>=48&&top<=height*.6:top>=48&&bottom<=height-48;
   const move=args.reveal==='center'||args.reveal==='if-needed'&&!visible;
   const offset=move?targetY()-initialY:0;
   marks=measurements;focusMarks=focus?[focus]:[];presentation=args.context?{...args.context}:{phase:'context',title:'当前核查范围'};paintKey='';paintEvidence();watchEvidence();
   if(move){
     const start=performance.now(),duration=matchMedia('(prefers-reduced-motion: reduce)').matches||Math.abs(offset)>height*1.5?0:240;
     do{
       const rendered=await frame();if(command!==navigation)return {status:'interrupted'};
       const t=duration&&rendered?Math.min(1,(performance.now()-start)/duration):1,desired=initialY+offset*(1-Math.pow(1-t,3));
       setEvidenceScroll(scroll,desired);paintEvidence();if(t===1)break;
     }while(true);
     // The SDK can adjust its scroll position during the next layout frame.
     // Verify fresh geometry and correct once; never acknowledge a requested delta
     // as actual movement, and never loop against a document boundary.
     for(let pass=0;pass<2;pass++){
       await frame();if(command!==navigation)return {status:'interrupted'};
       const fresh=marks.map(projectEvidence);
       if(fresh.some(x=>!x)){clearEvidence();return {status:'unsupported',reason:'selection_preservation'}}
       marks=fresh;current=fresh[0];
       if(pass===0&&Math.abs(targetY()-scroll.Ssa)>2)setEvidenceScroll(scroll,targetY());
       paintEvidence();
     }
   }
   if(command!==navigation)return {status:'interrupted'};
   if(api().isDocumentModified()||api().asc_isDocumentCanSave()){clearEvidence();return {status:'stale'}}
   const finalTop=(long?current.startY:current.top)-scroll.Ssa,finalBottom=current.bottom-scroll.Ssa;
   return {status:'presented',moved:Math.abs(scroll.Ssa-initialY)>1,visible:long?finalTop>=0&&finalTop<height:finalTop>=0&&finalBottom<=height,selectionPreserved:true,marked:marks.length,geometry:current.precise?'line-ranges':'start-only',fragments:current.rects.length,alignment:long?'start':'center'};
 }
 // User input cancels navigation; document-relative decorations keep tracking the viewport.
 const userInteraction=()=>{navigation++;if(presentation){presentation.paused=true;paintEvidence()}parent.postMessage({channel:protocol,event:'user_scroll',documentKey:main()?.document?.key},origin)};
 document.addEventListener('pointerdown',userInteraction,true);
 document.addEventListener('keydown',userInteraction,true);
 window.addEventListener('resize',()=>{navigation++;paintKey='';paintEvidence()});

 const main=()=>window.DE?.getController('Main');
 const unlock=()=>{if(!held)return;held=false;api().asc_setRestriction(restoreRestriction);document.getElementById('rixin-save-shield')?.remove()};
 async function freeze(){
   if(composing)throw Error('请先完成正在输入的文字');
   if(held)return {synced:true};
   restoreRestriction=modeRestriction;held=true;
   const shield=document.createElement('div');shield.id='rixin-save-shield';shield.textContent='正在确认文档保存…';
   shield.style.cssText='position:fixed;inset:0;z-index:999999;background:#ffffff66;display:flex;align-items:center;justify-content:center;color:#334155;font:14px sans-serif;cursor:wait';document.body.append(shield);
   api().asc_Save();
   const start=Date.now();
   while(api().isDocumentModified()||api().asc_isDocumentCanSave()){
     if(Date.now()-start>15000){unlock();throw Error('修改尚未同步，请稍后重试')}
     await new Promise(r=>setTimeout(r,80));
   }
   api().asc_setRestriction(Asc.c_oAscRestrictionType.View);
   return {synced:true};
 }
 // GetText can append deleted runs beyond a range in the pinned SDK.
 // Selection JSON respects its actual boundaries; accept only simple paragraphs.
 function rangeSourceText(range,allowPlainText=false){
   if(typeof range?.ToJSON!=='function')return allowPlainText?range?.GetText?.({Numbering:false}):null;
   try{
     const value=range.ToJSON(),j=typeof value==='string'?JSON.parse(value):value;
     const p=j?.type==='document'&&j.content?.length===1?j.content[0]:j;
     if(p?.type!=='paragraph'||!Array.isArray(p.content))return null;
     let text='';
     for(const n of p.content){
       if(!['run','endRun','bookmarkStart','bookmarkEnd','commentRangeStart','commentRangeEnd'].includes(n.type))return null;
       if(n.type==='run'){
         const value=runText(n.content);if(value===null)return null;
         if(n.reviewType!=='remove')text+=value;
       }
     }
     return text;
   }catch{return null}
 }
 // The pinned SDK serializes a full-width space as ASCII in range JSON.
 // Recover the original characters only when plain text and bounded JSON
 // agree one-for-one, including the position of every horizontal space.
 function navigationRangeText(range,allowPlainText=false){
   const projected=rangeSourceText(range,allowPlainText);
   if(typeof projected!=='string')return null;
   const text=range.GetText?.({Numbering:false,NewLineSeparator:'\n'});
   if(typeof text!=='string'||text===projected)return projected;
   const horizontalSpaces=value=>value.replace(/\p{Zs}/gu,' ');
   const canonical=horizontalSpaces(projected);
   if(horizontalSpaces(text)===canonical)return text;
   const withoutMark=text.replace(/\r?\n$/,'');
   return horizontalSpaces(withoutMark)===canonical?withoutMark:projected;
 }
 const writes=new Map();
 function applyProposal(args){
   const a=api(),d=window.AscBuilder?.sb?.GetDocument?.();
   if(writes.has(args.id))return writes.get(args.id);
   const reject=reason=>({status:'rejected',reason});
   if(held||composing||modeRestriction!==Asc.c_oAscRestrictionType.None||main().editorConfig.mode==='view')return reject('当前正文只读或正在保存');
   if(a.isDocumentModified()||a.asc_isDocumentCanSave())return reject('正文存在未保存修改');
   if(typeof args.id!=='string'||!/^rx_[a-f0-9]{32}$/.test(args.bookmark)||!['ALL','COMMENT','MODIFY'].includes(args.mode)||typeof args.after_text!=='string'||args.after_text.length>30000||typeof args.comment!=='string'||args.comment.length>10000)return reject('操作参数无效');
   const appended=args.append_paragraphs;
   const append=Array.isArray(appended)&&appended.length>0;
   if(append&&(args.mode==='COMMENT'||appended.some(t=>typeof t!=='string'||!t.trim()||/[\r\n\t]/.test(t))||typeof d.InsertParagraphBreak!=='function'))return reject('新增段落格式无效');
   if(!append&&args.mode!=='COMMENT'&&(!args.after_text.trim()||/[\r\n\t]/.test(args.after_text)||args.after_text===args.target?.quote))return reject('仅支持普通单段条款替换');
   if(args.mode!=='MODIFY'&&!args.comment.trim())return reject('批注内容为空');
   const bound=bindAnchors({version:args.target?.version,blocks:args.target?.blocks});
   if(bound.status!=='bound'||bound.mapped!==bound.total)return {...reject('正文结构与保存版本不一致'),diagnostic:{code:'source_mapping_mismatch',sourceIndex:bound.sourceIndex,blockId:args.target.blocks[bound.sourceIndex]?.id,unresolved:bound.unresolved}};
   const nativeTarget=writeAnchor(args.target,binding.entries.get(args.target.blockId));
   if(!nativeTarget)return reject('目标段落与保存原文不一致，请在正文中核对');
   let resolved=resolveRange(args.target);
   const continuation=args.continuation;
   if(continuation){
     if(!/^rx_[a-f0-9]{32}$/.test(continuation.bookmark)||!['COMMENT','MODIFY'].includes(continuation.mode))return reject('补做操作参数无效');
     const bookmark=d.GetBookmark?.(continuation.bookmark),priorRange=bookmark?.GetRange?.();
     const entry=binding?.entries.get(args.target.blockId);
     if(!priorRange||rangeSourceText(priorRange,false)!==args.target.quote||!entry||paragraphText(entry.p)!==nativeTarget.paragraph)return reject('此前操作位置已变化，请重新核对');
     resolved={range:priorRange,entry};
   }
   if(!resolved.range)return reject('原文已变化或无法唯一定位');
   const {range,entry}=resolved;
   if(typeof a.asc_AddText!=='function'||typeof range.AddBookmark!=='function'||typeof range.AddComment!=='function')return reject('编辑器缺少写入能力');
   const json=JSON.parse(entry.p.ToJSON());
   if(!(continuation?.mode==='MODIFY'&&args.mode==='COMMENT')&&(json.changes?.length||json.content?.some(n=>['add','remove'].includes(n.reviewType))))return reject('该段已有未处理修订，请先在正文中核对');
   if(args.mode!=='COMMENT'&&continuation?.mode!=='COMMENT'&&json.content?.some(n=>['commentRangeStart','commentRangeEnd'].includes(n.type)))return reject('该段已有批注，请在正文中核对后手工修订');
   if(args.mode!=='COMMENT'&&json.content?.some(n=>!['run','endRun','commentRangeStart','commentRangeEnd','bookmarkStart','bookmarkEnd'].includes(n.type)))return reject('该段包含复杂行内内容，请手工修订');
   let previousComment,commentAuthor='法务审阅员',commentUser;
   if(continuation?.mode==='COMMENT'&&!append){
     if(args.mode!=='ALL'||continuation.comment!==args.comment||typeof d.GetAllComments!=='function')return reject('不能完整保留此前批注');
     const matches=d.GetAllComments().filter(c=>c.GetText()===continuation.comment&&c.GetAuthorName()==='法务审阅员'&&c.GetQuoteText()===args.target.quote);
     // OOXML w:id values are not SDK runtime comment IDs (and change on reopen).
     // Only explicitly supplied runtime IDs may address GetCommentById.
     previousComment=continuation.runtime_comment_id?d.GetCommentById?.(continuation.runtime_comment_id):matches.length===1?matches[0]:null;
     if(!previousComment||!matches.includes(previousComment)&&!matches.some(c=>c.GetId()===previousComment.GetId())||previousComment.GetRepliesCount()!==0||previousComment.IsSolved())return reject('原批注已变化或包含回复，请在正文中处理');
     commentAuthor=previousComment.GetAuthorName();commentUser=previousComment.GetUserId();
     // Other comment threads might overlap the selection. Do not move them.
     if(d.GetAllComments().some(c=>c.GetId()!==previousComment.GetId()&&c.GetQuoteText()&&(args.target.paragraph.includes(c.GetQuoteText())||c.GetQuoteText().includes(args.target.quote))))return reject('修改位置还有其他批注，请在正文中处理');
   }
   if(d.GetBookmark?.(args.bookmark))return {status:'uncertain',reason:'本次操作已开始，请保存并确认结果'};
   clearEvidence();
   // Set a receipt BEFORE the first mutation. A lost message or partial failure
   // must never cause the same operation to apply twice.
   writes.set(args.id,{status:'uncertain',reason:'操作尚未完整确认，请保存后核对'});
   try{
     a.asc_SetLocalTrackRevisions(true);
     let commentId;
     if(args.mode!=='COMMENT'&&!append){
       range.Select();
       const selected=d.GetRangeBySelect?.();
       const selectedText=selected?.ToJSON?rangeSourceText(selected):selected?.GetText?selected.GetText({Numbering:false}):a.asc_GetSelectedText();
       if(selectedText!==args.target.quote)throw Error('写入前选区发生变化');
       a.asc_AddText(args.after_text);
       const proposed=paragraphText(entry.p),chars=Array.from(nativeTarget.paragraph);
       const expected=chars.slice(0,nativeTarget.start).join('')+args.after_text+chars.slice(nativeTarget.end).join('');
       if(proposed!==expected)throw Error('修改后的正文与建议不一致');
     }
     // Both bookmarks and comments attached to a replaced selection may be
     // removed by the native replacement. Bind them to the resulting text.
     let resultRange=range;
     if(args.mode!=='COMMENT'&&!append){
       const updated=JSON.parse(entry.p.ToJSON());
       const plain=!updated.changes?.length&&!updated.content?.some(n=>['add','remove'].includes(n.reviewType));
       const matches=entry.p.Search(args.after_text,true).filter(r=>rangeSourceText(r,plain)===args.after_text);
       if(matches.length!==1)throw Error('修改已写入，但新文本无法唯一绑定');
       resultRange=matches[0];
     }
     if(!resultRange.AddBookmark(args.bookmark))throw Error('无法记录修改位置');
     if(args.mode!=='MODIFY'&&!(append&&continuation?.mode==='COMMENT')){
       const comment=resultRange.AddComment(args.comment,commentAuthor,commentUser);
       commentId=comment?.GetId?.();if(!commentId)throw Error('批注未能写入');
       if(previousComment){
         const remaining=d.GetCommentById?.(previousComment.GetId());
         if(remaining&&!remaining.Delete())throw Error('新批注已保存，原批注尚未移除，请核对');
       }
     }
     if(append){
       let paragraph=entry.p;
       for(const value of appended){
         // SDK ranges include the final paragraph mark. Split just before it,
         // after real trailing tabs and the source clause's comment/bookmark.
         const full=paragraph.GetRange();
         const end=full.GetEndPos()-full.GetStartPos()-1;
         if(end<0||rangeSourceText(paragraph.GetRange(0,end))!==paragraphText(paragraph))throw Error('无法确认原条款段尾');
         paragraph.GetRange(end,end).Select();
         if(!d.InsertParagraphBreak())throw Error('未能插入段落');
         a.asc_AddText(value);
         paragraph=paragraph.GetNext();
         if(!paragraph||paragraphText(paragraph)!==value)throw Error('新增段落内容与建议不一致');
       }
       if(paragraphText(entry.p)!==nativeTarget.paragraph)throw Error('新增段落时原条款发生变化');
     }
     a.ye()?.wq?.();binding=null;
     const result={status:'applied',commentId,bookmark:args.bookmark};writes.set(args.id,result);return result;
   }catch(err){const result={status:'uncertain',reason:String(err.message||err)};writes.set(args.id,result);return result}
 }
 async function execute(action,args){
   if(!main()?._isDocReady||!api())throw Error('正文尚未就绪');
   if(action==='hello'){document.documentElement.classList.add('rixin-integrated');return {build,protocol,navigationVersion:33,applyTrackedSuggestion:true,evidencePresentation:true,structuredAnchors:true,documentKey:main().document.key};}
   if(action==='applyProposal')return applyProposal(args);
   if(action==='inspectProposal'){
     if(typeof args.id!=='string'||!/^rx_[a-f0-9]{32}$/.test(args.bookmark))return {status:'invalid_request'};
     const cached=writes.get(args.id);if(cached)return {status:cached.status==='applied'?'present':'uncertain',receipt:cached};
     const doc=window.AscBuilder?.sb?.GetDocument?.();
     if(!doc||typeof doc.GetBookmark!=='function')return {status:'uncertain'};
     if(doc.GetBookmark(args.bookmark))return {status:'present'};
     // A failed edit can change text before a bookmark is created.
     return {status:api().isDocumentModified()||api().asc_isDocumentCanSave()?'uncertain':'absent'};
   }
   if(action==='freeze')return freeze();
   if(action==='unfreeze'){unlock();return {ok:true}}
   if(action==='state')return {modified:api().isDocumentModified(),canSave:api().asc_isDocumentCanSave(),held};
   if(action==='bindAnchors'){if(api().isDocumentModified()||api().asc_isDocumentCanSave())return {status:'stale'};return bindAnchors(args)}
   if(action==='cancelNavigation'){navigation++;return {ok:true}}
   if(action==='clearEvidence'){clearEvidence();return {ok:true}}
   if(action==='evidenceContext'){
     if(api().isDocumentModified()||api().asc_isDocumentCanSave()){clearEvidence();return {status:'stale'}}
     if(!binding||binding.version!==args.version||marks[0]?.blockId!==args.blockId)return {status:'not_current'};
     if(!args.context||!Object.hasOwn(phaseLabels,args.context.phase)||typeof args.context.title!=='string'||args.context.title.length>200)return {status:'invalid_request'};
     presentation={...args.context,paused:presentation?.paused};paintEvidence();return {status:'updated'};
   }
   if(action==='presentEvidence')return presentEvidence(args);
   if(action==='locate'){
     clearEvidence();
     const changed=()=>api().isDocumentModified()||api().asc_isDocumentCanSave();
     if(changed())return {status:'stale'};
     const resolved=resolveRange(args,true);
     const anchor={blockId:args.blockId,sourceStart:args.start,sourceEnd:args.end};
     if(!resolved.range)return resolved.reason==='range_text_mismatch'?{...resolved,...anchor}:resolved;
     const {entry,quote,paragraph,start,end}=resolved;
     let range=resolved.range;
     for(let attempt=0;attempt<2&&range;attempt++){
       const result=await selectRange(range);
       if(result.reason==='selection_rendering_unsupported')return {status:'unsupported',...result};
       if(result.interrupted)return {status:'interrupted',...result};
       if(changed()||paragraphText(entry.p)!==entry.text)return {status:'stale'};
       if(matchesSelection(range,quote))
         return {status:'located',method:'paragraph_range',blockId:args.blockId,paragraphIndex:entry.index,...result};
       if(attempt===0)range=proposedRange(entry.p,paragraph,start,end,quote);
     }
     return {status:'not_found',reason:'selected_text_mismatch',...anchor};
   }
   if(action==='mode'){
     if(held)throw Error('正在保存');
     if(main().editorConfig.mode==='view'&&args.mode!=='viewing')throw Error('已定稿文档只读');
     if(!['viewing','suggesting','editing'].includes(args.mode))throw Error('未知模式');
     clearEvidence();modeRestriction=args.mode==='viewing'?Asc.c_oAscRestrictionType.View:Asc.c_oAscRestrictionType.None;api().asc_setRestriction(modeRestriction);api().asc_SetLocalTrackRevisions(args.mode==='suggesting');return {ok:true};
   }
   if(action==='disableSpellcheck'){
     if(typeof api().asc_setSpellCheck!=='function'||!window.Common?.NotificationCenter)throw Error('当前编辑器不支持关闭拼写检查');
     api().asc_setSpellCheck(false);
     window.Common.NotificationCenter.trigger('spelling:turn','off',true);
     return {enabled:false};
   }
   if(action==='defaultLanguage'){
     if(held||main().editorConfig.mode==='view')throw Error('当前文档不可修改校对语言');
     const a=api(),language=2052; // zh-CN, the same property as Set Document Language.
     if(typeof a.asc_getDefaultLanguage!=='function'||typeof a.asc_setDefaultLanguage!=='function')throw Error('当前编辑器不支持文档语言设置');
     if(a.asc_getDefaultLanguage()===language)return {language,changed:false};
     a.asc_setDefaultLanguage(language);
     if(a.asc_getDefaultLanguage()!==language)throw Error('文档语言设置未生效');
     return {language,changed:true};
   }
   if(action==='review'){
     const tab=document.querySelector('.ribtab a[data-tab="review"]');
     if(!tab||!tab.getClientRects().length||tab.getAttribute('aria-disabled')==='true')throw Error('审阅工具栏不可用');
     tab.click();
     if(!document.querySelector('.ribtab.active a[data-tab="review"]'))throw Error('审阅工具栏未能打开');
     return {ok:true,tab:'review'};
   }
   if(action==='comments'){document.querySelector('#left-btn-comments')?.click();return {ok:true}}
   throw Error('不支持的编辑器操作');
 }
 window.addEventListener('message',async e=>{
   const m=e.data;if(e.source!==parent||e.origin!==origin||!m||m.channel!==protocol||typeof m.requestId!=='string'||m.requestId.length>100)return;
   if(m.documentKey!==main()?.document?.key)return;
   const reply=data=>parent.postMessage({channel:protocol,requestId:m.requestId,documentKey:m.documentKey,...data},origin);
   if(m.action==='cancelNavigation'){navigation++;reply({ok:true,result:{ok:true}});return}
   if(busy){reply({ok:false,error:'编辑器正忙'});return}
   busy=true;try{reply({ok:true,result:await execute(m.action,m.args||{})})}catch(err){reply({ok:false,error:String(err.message||err)})}finally{busy=false}
 });
})();
