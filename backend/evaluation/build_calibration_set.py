"""Build a synthetic, label-separated engineering regression suite."""
import json
from pathlib import Path
from app.parser import parse_docx

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
CASES=[];LABELS=[]

def add(cid,split,texts,expected,stage='pre_sign',purpose=''):
    CASES.append({'id':cid,'split':split,'context':{'contract_type':'构造技术服务合同','our_party':'乙方，服务提供方；甲方为客户','stage':stage},'blocks':[{'id':f'{cid}:p{i+1}','text':t} for i,t in enumerate(texts)]})
    LABELS.append({'id':cid,'expected':{r:v if isinstance(v,list) else [v] for r,v in expected.items()},'purpose':purpose,'label_status':'engineering_expectation_from_confirmed_rubric','legal_gold':False})

N='no_flag_for_target_rule';I='insufficient_evidence';F='flag'
fixture=parse_docx((ROOT/'backend/tests/fixtures/review-room-contract.docx').read_bytes())
add('D01','regression',[b['text'] for b in fixture['blocks']],{'RL-02':N,'RL-03':I,'RL-04':I,'RL-05':N},purpose='原浏览器样例三类偏差重现；合同未提供附件')
add('D02','regression',['服务内容为风电功率预测，服务期为2027年1月1日至2027年12月31日。','合同含税总价100000元，签署后支付30%，余款70%在验收后按甲方资金计划支付。','双方转让合同权利义务均须事先取得对方书面同意，无例外。'],{'RL-02':N,'RL-05':N,'RL-03':N},purpose='付款期限模糊不能冒充金额或空白缺项')
add('D03','regression',['服务期为自生效日起十二个月，提供数据分析服务。合同固定总价人民币900元。','服务提供方乙方未经甲方书面同意不得转让本合同；其他内容无转让安排。'],{'RL-03':I},purpose='仅限制我方不等于客户转让保护已具备')
add('D04','positive_control',['同一风场的数据服务从2027年1月1日起持续12个月。','本合同约定上述同一风场、同一数据服务自2027年1月1日起持续24个月，两条约定同时有效且无优先顺序。','客户甲方可将本合同全部权利义务转让给第三方，无须征得服务方乙方同意。','双方要求签署前明确填写固定总价，合同固定总价为人民币【待填写】元。'],{'RL-01':F,'RL-03':F,'RL-05':F},purpose='校准后仍须检出确定期限冲突、单方转让和明确必填占位')
add('H01','reserved',['采购气象数据接口服务，周期2028年3月1日至2029年2月28日。','含税年度费用八万元；首期一成，尾期九成。尾期结算时间由客户统筹安排。','转移合同权利或义务前，任何一方均须取得另一方书面同意。'],{'RL-02':N,'RL-05':N},purpose='换措辞和中文比例的付款时限反例')
add('H02','reserved',['本合同处于起草阶段，已明确服务范围为数据托管，服务期限为2028年度，固定价款6000元。','双方约定运行验收单在交付后填写，当前仅附未来模板：实际投运日期____年__月__日。','仅乙方转让须甲方同意，未约定客户甲方转让限制。'],{'RL-03':I,'RL-05':[N,'not_applicable']},stage='draft',purpose='客户保护缺项与未来模板空白区分')
add('H03','reserved',['双方均不得在未取得对方事先书面同意时让与合同权利或义务，无其他例外。','本合同引用附件一《服务清单》，当前上传文件只有正文；附件图像内容无法辨认，资料包完整性尚未确认。'],{'RL-03':N,'RL-04':I},purpose='双向同意反例和附件不可辨认，不能声称现实中缺失')
add('H04','reserved',['甲方是数据服务客户，乙方是提供方。客户可自行决定将协议下的权利和履约义务交由其他企业承接，仅通知乙方即可，无须乙方许可。','应付服务费按收益的5%计算；收益口径是含税还是未税尚未约定。','双方约定签署前必须填写本次交付产品名称，当前交付产品名称：【待确定】。'],{'RL-03':F,'RL-02':I,'RL-05':F},purpose='换措辞的真实转让风险、计算基数缺失和必填项占位')
for name,data in [('inputs.jsonl',CASES),('expectations.jsonl',LABELS)]:
    (OUT/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in data))
print(f'{len(CASES)} synthetic cases; {sum(len(x["expected"]) for x in LABELS)} targeted rule checks; not legal gold labels')
