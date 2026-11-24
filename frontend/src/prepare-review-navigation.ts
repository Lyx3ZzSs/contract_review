import type {ReviewEditor} from './editors/contract-editor'

export async function prepareReviewNavigation(editor:Pick<ReviewEditor,'ready'|'busy'|'saveStatus'|'flushSave'>,valid:()=>boolean,status:(message:string)=>void){
 if(!valid())return false
 if(!editor.ready)throw Error('正文尚未加载完成，请稍后再次点击定位原文。')
 if(editor.saveStatus!=='saved'||editor.busy){
  status('正在保存正文，保存后继续定位…')
  const saved=await editor.flushSave()
  if(!valid())return false
  if(!saved)throw Error('正文保存未成功，暂时无法定位。请再次点击定位原文重试。')
 }
 if(!valid())return false
 status('正在定位所选原文…')
 return true
}
