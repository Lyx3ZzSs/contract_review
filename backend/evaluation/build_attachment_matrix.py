"""Synthetic attachment-role checks; expectations never enter extraction requests."""
import json
from pathlib import Path
from app.amount_review import classify
HERE=Path(__file__).parent
rows=[
 ('A01',['合同总价1000元，按总价首付30%、尾款70%。','接口规范以《技术附件》为准，本次未提供该附件。'],{'技术附件':'technical'},'no_flag_for_target_rule',[]),
 ('A02',['服务费按《报价附件》所列单价乘实际数量计算，报价附件本次未提供。'],{'报价附件':'pricing'},'insufficient_evidence',['报价附件']),
 ('A03',['技术指标与各项服务单价均以《技术服务附件》为准，本次未提供。'],{'技术服务附件':'mixed'},'insufficient_evidence',['技术服务附件']),
 ('A04',['合同固定总价600元；其他约定详见附件A，本次未提供附件A。'],{'附件A':'unknown'},'no_flag_for_target_rule',[]),
 ('A05',['接口规范以《技术附件》为准，单价按《报价附件》计算，两个附件本次均未提供。'],{'技术附件':'technical','报价附件':'pricing'},'insufficient_evidence',['报价附件']),
 ('A06',['授权范围详见《授权委托书》，合同固定总价100元。'],{'授权委托书':'other'},'no_flag_for_target_rule',[]),
 ('A07',['《技术附件》仅规定接口参数，不涉及价格和计费，双方已另在正文确定固定价款1000元。'],{'技术附件':'technical'},'no_flag_for_target_rule',[]),
]
inputs=[];labels=[]
for cid,blocks,kinds,status,dependencies in rows:
 inputs.append({'id':cid,'blocks':[{'id':f'{cid}:p{i+1}','text':t} for i,t in enumerate(blocks)],'context':{'contract_type':'构造数据服务合同','our_party':'乙方服务方','stage':'pre_sign'}})
 labels.append({'id':cid,'kinds':kinds,'amount_status':status,'pricing_dependencies':dependencies,'legal_gold':False})
for filename,data in [('attachments.inputs.jsonl',inputs),('attachments.expectations.jsonl',labels)]:
 (HERE/filename).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in data))
