import type {ProposalOperation} from './contract-editor'
export type RecoverableProposal=ProposalOperation&{bookmark:string}
type Inspection={status:string}
type EditorState={modified:boolean;canSave:boolean}
export type ProposalRecovery={
 confirm:()=>Promise<ProposalOperation>;
 load:()=>Promise<RecoverableProposal>;
 inspect:(op:RecoverableProposal)=>Promise<Inspection>;
 state:()=>Promise<EditorState>;
 cancel:(op:RecoverableProposal)=>Promise<ProposalOperation>;
 saveAndConfirm:()=>Promise<ProposalOperation>;
 markClean:()=>void;
}
/** Recover an existing operation without ever replaying its content command. */
export async function recoverProposal(io:ProposalRecovery):Promise<ProposalOperation>{
 let confirmed:ProposalOperation|undefined,confirmationError:unknown
 try{confirmed=await io.confirm()}catch(error){confirmationError=error}
 if(confirmed){
   // A failed cosmetic/read-only state query cannot invalidate a committed receipt.
   try{const state=await io.state();if(!state.modified&&!state.canSave)io.markClean()}catch{/* Keep dirty state until the next successful state check. */}
   return confirmed
 }
 const op=await io.load()
 if(op.state!=='prepared')return op
 const inspected=await io.inspect(op)
 if(inspected.status==='absent')return io.cancel(op)
 const state=await io.state()
 if(op.phase==='saved_unverified'&&!state.modified&&!state.canSave){
   // Saving the same invalid snapshot produces error 4 and cannot repair it.
   throw Error(op.verification_error||(confirmationError instanceof Error?confirmationError.message:'保存结果未通过核验，请核对或撤销未完成操作'))
 }
 return io.saveAndConfirm()
}
/** A lost reply allows inspection, never a second apply command. */
export async function inspectProposalFailure(io:{inspect:()=>Promise<Inspection>;cancel:()=>Promise<ProposalOperation>}):Promise<ProposalOperation|undefined>{
 const inspected=await io.inspect()
 if(inspected.status==='absent')return io.cancel()
 return undefined
}
