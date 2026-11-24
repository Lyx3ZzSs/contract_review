// Serialize mode transitions so a late read-only acknowledgement cannot leave
// the document locked after the review has already ended.
export function createReviewReadonly(apply:(locked:boolean)=>Promise<void>){
 let queue=Promise.resolve(),current=false
 return (locked:boolean)=>{
  const work=queue.catch(()=>{}).then(async()=>{if(current===locked)return;await apply(locked);current=locked})
  queue=work
  return work
 }
}
