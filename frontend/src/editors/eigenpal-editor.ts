import {createDocxEditor} from '@docx-editor.dev/core/editor'
import type {DocxEditorConfig} from '@docx-editor.dev/core/editor'
import {initialState} from '../review-state'
import type {ReviewEditor,ReviewTarget} from './contract-editor'
import {bindEigenpalAnchors,type SourceBlock} from './eigenpal-anchors'
import '@docx-editor.dev/core/styles/editor.css'

// A background tab may throttle RAF to 1 Hz; navigation must still settle/cancel promptly.
const frame=()=>new Promise<void>(resolve=>{let id=0;const timer=setTimeout(()=>{cancelAnimationFrame(id);resolve()},80);id=requestAnimationFrame(()=>{clearTimeout(timer);resolve()})})
export async function mountEigenpal(host:HTMLElement,bytes:Uint8Array,version:string,blocks:SourceBlock[],fonts?:DocxEditorConfig['fonts']){
 // Core 2.37 locates its scrolling viewport through this source-verified adapter CSS structure.
 host.classList.add('docx-editor','docx-editor__scroll-container')
 host.style.overflow='auto'
 const surface=document.createElement('div');surface.className='docx-paginated-surface';surface.style.width='max-content';host.append(surface)
 // Reading gutters let even the first/last clause reach the viewport center.
 const resize=new ResizeObserver(()=>{surface.style.marginBlock=`${host.clientHeight/2}px`});resize.observe(host)
 surface.style.marginBlock=`${host.clientHeight/2}px`
 const native=createDocxEditor({container:surface,document:bytes,mode:'view',fonts,zoomMode:'auto'})
 let generation=0,disposed=false,changed=false,navigationCount=0
 const listeners=new Set<()=>void>()
 const cancel=()=>{generation++}
 const interaction=()=>{cancel();listeners.forEach(l=>l())}
 host.addEventListener('wheel',interaction,{passive:true});host.addEventListener('pointerdown',interaction);host.addEventListener('keydown',interaction)
 let unsubscribe=()=>{}
 const destroy=()=>{disposed=true;cancel();unsubscribe();resize.disconnect();host.removeEventListener('wheel',interaction);host.removeEventListener('pointerdown',interaction);host.removeEventListener('keydown',interaction);native.destroy();surface.remove()}
 try{
  const until=performance.now()+20000
  while(native.snapshot().isOpening){if(performance.now()>until)throw Error('正文排版超时');await frame()}
  const binding=bindEigenpalAnchors(version,blocks,native.query({type:'paragraphs'}),text=>native.findMatches(text,{matchCase:true}))
  host.scrollTop=Math.max(0,host.clientHeight/2-24)
  unsubscribe=native.on('change',()=>{changed=true;cancel()})
  const locate=async(target:ReviewTarget)=>{
   if(disposed||changed)return false
   const current=++generation,valid=()=>!disposed&&!changed&&current===generation
   try{
    const range=binding.resolve(target)
    const scrolls=[host,...host.querySelectorAll<HTMLElement>('*')].filter(el=>el.scrollHeight>el.clientHeight+1&&/(auto|scroll)/.test(getComputedStyle(el).overflowY))
    const before=new Map(scrolls.map(el=>[el,el.scrollTop]))
    const painted=native.setHighlights('rixin-current',[range],{color:'rgba(109,78,225,.22)',className:'rixin-eigenpal-current',priority:30})
    if(painted.applied!==1||!native.scrollToBlock(range.blockId,{block:'center',behavior:'instant',offsetPx:0}))return false
    if(!valid())return false
    const marks=[...host.querySelectorAll<HTMLElement>('.rixin-eigenpal-current')]
    if(!marks.length)return false
    const first=marks[0].getBoundingClientRect(),last=marks.at(-1)!.getBoundingClientRect()
    const scroller=scrolls.find(el=>el.contains(marks[0]))
    if(!scroller)return false
    const viewport=scroller.getBoundingClientRect(),height=last.bottom-first.top
    // Long evidence starts near the upper third; short evidence is centered.
    scroller.scrollTop+=height>viewport.height*.65?first.top-viewport.top-viewport.height*.25:(first.top+last.bottom)/2-(viewport.top+viewport.height/2)
    const destination=scroller.scrollTop,origin=before.get(scroller)??destination
    if(Math.abs(destination-origin)>1&&Math.abs(destination-origin)<viewport.height*1.5&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
     scroller.scrollTop=origin;const started=performance.now()
     while(valid()){
      const t=Math.min(1,(performance.now()-started)/260);scroller.scrollTop=origin+(destination-origin)*(1-Math.pow(1-t,3))
      if(t===1)break;await frame()
     }
    }
    if(!valid())return false
    await frame();if(!valid())return false
    navigationCount++;return true
   }catch{return false}
  }
  const adapter:ReviewEditor={readOnly:true,ready:true,busy:false,saveStatus:'saved',review:initialState(),capabilities:{locateEvidence:true,applyTrackedSuggestion:false},flushSave:async()=>!changed,canAutomaticallyLocate:()=>!changed&&!disposed,cancelReviewNavigation:cancel,subscribeDocumentInteraction:l=>{listeners.add(l);return()=>{listeners.delete(l)}},setReviewReadonly:async locked=>{if(!locked)throw Error('对照原型仅支持只读')},locateReviewTarget:locate,locateEvidence:async()=>false}
  return {adapter,native,destroy,diagnostics:()=>({bound:binding.size,navigationCount,changed,pages:native.getTotalPages()}),highlightRelated(targets:ReviewTarget[]){return native.setHighlights('rixin-related',targets.map(t=>binding.resolve(t)),{color:'rgba(225,153,24,.22)',className:'rixin-eigenpal-related',priority:20})}}
 }catch(error){destroy();throw error}
}
