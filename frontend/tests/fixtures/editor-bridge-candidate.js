/* Version-pinned, allowlisted host bridge. No eval or generic SDK proxy. */
(function(){
 'use strict';
 const protocol='rixin-editor-v1',build='10.0.0-labesign10';
 const origin=new URLSearchParams(location.search).get('parentOrigin');
 if(!['http://127.0.0.1:5173','http://127.0.0.1:5174','http://127.0.0.1:5175','http://127.0.0.1:18084'].includes(origin))return;
 let composing=false,held=false,busy=false,restoreRestriction=0,modeRestriction=0;
 document.addEventListener('compositionstart',()=>{composing=true},true);
 document.addEventListener('compositionend',()=>{composing=false},true);
 const block=e=>{if(held){e.preventDefault();e.stopImmediatePropagation()}};
 ['keydown','beforeinput','paste','drop','pointerdown','mousedown','click'].forEach(x=>document.addEventListener(x,block,true));
 const api=()=>window.Asc?.editor;
 const main=()=>window.DE?.getController('Main');
 const unlock=()=>{if(!held)return;held=false;api().asc_setRestriction(restoreRestriction);document.getElementById('rixin-save-shield')?.remove()};
 function requireConnection(){
   const controller=main();
   if(!navigator.onLine||controller?._state?.isDisconnected||controller?._state?.lostEditingRights||controller?.stackDisableActions?.get({type:'reconnect'}))throw Error('文档连接中断或正在重连，尚不能确认修改已同步');
 }
 async function freeze(){
   requireConnection();
   if(composing)throw Error('请先完成正在输入的文字');
   if(held)return {synced:true};
   restoreRestriction=modeRestriction;held=true;
   const shield=document.createElement('div');shield.id='rixin-save-shield';shield.textContent='正在确认文档保存…';
   shield.style.cssText='position:fixed;inset:0;z-index:999999;background:#ffffff66;display:flex;align-items:center;justify-content:center;color:#334155;font:14px sans-serif;cursor:wait';document.body.append(shield);
   try{
   api().asc_Save();
   const start=Date.now();
   while(api().isDocumentModified()||api().asc_isDocumentCanSave()){
     requireConnection();
     if(Date.now()-start>15000){unlock();throw Error('修改尚未同步，请稍后重试')}
     await new Promise(r=>setTimeout(r,80));
   }
   requireConnection();
   api().asc_setRestriction(Asc.c_oAscRestrictionType.View);
   return {synced:true};
   }catch(error){unlock();throw error}
 }
 function search(text){
   const s=new AscCommon.CSearchSettings();s.put_Text(text);s.put_MatchCase(true);s.put_WholeWords(false);
   return api().asc_findText(s,true);
 }
 async function execute(action,args){
   if(!main()?._isDocReady||!api())throw Error('正文尚未就绪');
   if(action==='hello'){document.documentElement.classList.add('rixin-integrated');return {build,protocol,documentKey:main().document.key};}
   if(action==='freeze')return freeze();
   if(action==='unfreeze'){unlock();return {ok:true}}
   if(action==='state')return {modified:api().isDocumentModified(),canSave:api().asc_isDocumentCanSave(),held};
   if(action==='locate'){
     if(api().isDocumentModified()||api().asc_isDocumentCanSave())return {status:'stale'};
     const {paragraph,quote}=args;
     if(typeof paragraph!=='string'||typeof quote!=='string'||paragraph.length>30000||!quote||!paragraph.includes(quote))return {status:'not_found'};
     const pc=search(paragraph);
     if(pc!==1)return {status:pc?'ambiguous':'not_found'};
     if(api().asc_GetSelectedText().replace(/\r?\n$/,'')!==paragraph)return {status:'not_found'};
     const qc=search(quote),status=RixinEvidence.validate(paragraph,quote,pc,qc);
     if(status==='located'&&api().asc_GetSelectedText()!==quote)return {status:'not_found'};
     return {status};
   }
   if(action==='mode'){
     if(held)throw Error('正在保存');
     if(main().editorConfig.mode==='view'&&args.mode!=='viewing')throw Error('已定稿文档只读');
     if(!['viewing','suggesting','editing'].includes(args.mode))throw Error('未知模式');
     modeRestriction=args.mode==='viewing'?Asc.c_oAscRestrictionType.View:Asc.c_oAscRestrictionType.None;api().asc_setRestriction(modeRestriction);api().asc_SetLocalTrackRevisions(args.mode==='suggesting');return {ok:true};
   }
   if(action==='review'){document.querySelector('.ribtab a[data-tab="review"]')?.click();return {ok:true}}
   if(action==='comments'){document.querySelector('#left-btn-comments')?.click();return {ok:true}}
   throw Error('不支持的编辑器操作');
 }
 window.addEventListener('message',async e=>{
   const m=e.data;if(e.source!==parent||e.origin!==origin||!m||m.channel!==protocol||typeof m.requestId!=='string'||m.requestId.length>100)return;
   if(m.documentKey!==main()?.document?.key)return;
   const reply=data=>parent.postMessage({channel:protocol,requestId:m.requestId,documentKey:m.documentKey,...data},origin);
   if(busy){reply({ok:false,error:'编辑器正忙'});return}
   busy=true;try{reply({ok:true,result:await execute(m.action,m.args||{})})}catch(err){reply({ok:false,error:String(err.message||err)})}finally{busy=false}
 });
})();
