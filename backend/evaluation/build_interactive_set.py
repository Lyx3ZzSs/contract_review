"""Engineering fixtures, separate expectations, plus original-only corpus observations."""
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTEXT = {'contract_type': '技术服务合同', 'our_party': '乙方，服务提供方；甲方为客户', 'stage': 'pre_sign'}
BASE = ['甲方为客户，乙方为服务提供方。', '双方转让合同权利义务均须事先取得对方书面同意，无例外。']
NO = ['no_flag_for_target_rule', 'not_applicable']
PENDING = ['insufficient_evidence']


def blocks(prefix, texts):
    return [{'id': f'{prefix}:p{i}', 'text': text} for i, text in enumerate(texts, 1)]


def material(mid, name, texts, status='parsed'):
    return {'id': mid, 'filename': name, 'parse_status': status, 'blocks': blocks(mid, texts)}


def main():
    cases, labels = [], []
    def add(cid, name, texts, statuses, materials=None, assertions=None, links=None, extra=None, count=None, parent=None):
        bundle = {'id': f'bundle:{cid}', 'document_version_id': 'doc:three' if cid in ('I09','I10') else f'doc:{cid}',
                  'materials': materials or [], 'assertions': assertions or [], 'links': links or []}
        case = {'case_id': cid, 'scenario': name, 'blocks': blocks('three' if cid in ('I09','I10') else cid, BASE + texts),
                'context': CONTEXT, 'bundle': bundle, 'operations': [{'action': 'review', 'bundle_id': bundle['id']}]}
        if parent: case['operations'].insert(0, {'action': 'supplement', 'parent_case_id': parent, 'material_version_ids': [m['id'] for m in bundle['materials']]})
        check = {'rule_id': 'RL-04', 'statuses': statuses}
        if count is not None: check['issue_count'] = count
        cases.append(case)
        labels.append({'case_id': cid, 'provenance': 'synthetic', 'approved_for_scoring': False,
                       'expected_checks': [check] + (extra or []), 'basis': '工程验收矩阵，非逐项法务裁定'})
    add('I01','无附件引用',['服务范围：预测系统维护，服务期限一年。'],NO,count=0)
    add('I02','引用未见',['技术标准详见附件一《技术协议》。'],PENDING)
    add('I03','只有标题',['技术标准详见附件一《技术协议》。','附件一 技术协议'],PENDING)
    tech = ['附件一 技术协议','预测系统每15分钟更新预测数据，准确率按双方约定的月度统计口径考核。']
    add('I04','内嵌完整技术附件',['技术标准详见附件一《技术协议》。']+tech,NO)
    add('I05','同名不同版本',['技术标准以《技术协议》V2版为准。'],PENDING,
        [material('tech-v1','技术协议.docx',['技术协议 V1版','旧版本技术要求：每小时更新数据。'])])
    add('I06','技术计价双用途',['技术要求和合同费用明细均以附件一《技术协议》为准。'],NO,
        [material('mixed','技术协议.docx',tech+['本项目含税人民币费用：系统服务60000元，维护服务40000元，合计100000元。'])],
        extra=[{'rule_id':'RL-02','statuses':NO}])
    add('I07','未来确认单模板',['附件一《验收确认单》为未来验收后填写的模板，签署本合同时无需填写或签字。','附件一 验收确认单','验收日期：____；验收签字：____。'],NO,
        extra=[{'rule_id':'RL-05','statuses':NO}])
    add('I08','用户称线下提供',['技术标准详见附件一《技术协议》。'],PENDING,
        assertions=[{'id':'assert:offline','statement':'技术协议已经在线下提供给客户。','origin':'user_statement'}])
    three=['技术标准见附件一《技术协议》；合同价款明细见附件二《报价清单》；部署范围见附件三《实施方案》。']
    add('I09','三附件待补',three,PENDING,count=3)
    add('I10','三附件补齐一份',three,PENDING,[material('tech','技术协议.docx',tech)],count=2,parent='I09')
    add('I11','图片不可读',['技术标准详见附件一《技术协议》。'],PENDING,[material('image','技术协议.png',[],'unsupported')])
    add('I12','损坏DOCX',['技术标准详见附件一《技术协议》。'],PENDING,[material('broken','技术协议.docx',[],'failed')])
    price=['本项目含税人民币合同总价100000元，分项详见附件《报价清单》，签署时必须填明服务地点。']
    add('I13','计价附件补充前',price,PENDING)
    add('I14','补充计价不一致及必填空白',price,NO,[material('price','报价清单.docx',[
        '报价清单','本项目含税人民币费用：系统服务60000元，维护服务50000元，合同合计100000元。','签署时必须填写服务地点。服务地点：____。'])],
        extra=[{'rule_id':'RL-02','statuses':['flag','insufficient_evidence']},{'rule_id':'RL-05','statuses':['flag','insufficient_evidence']}],parent='I13')
    corpus = ROOT / 'analysis/legal-corpus/draft-v0.1'
    original_cases=[json.loads(line) for line in (corpus/'cases.inputs.jsonl').read_text().splitlines()]
    original_labels={l['case_id']:l for l in map(json.loads,(corpus/'cases.labels.jsonl').read_text().splitlines())}
    for sid in ['S02','S04']:
        doc=json.loads((corpus/f'inputs/{sid}.json').read_text())
        related=[c['case_id'] for c in original_cases if c.get('document_ref')==f'inputs/{sid}.json']
        cid=f'REAL-{sid}'
        cases.append({'case_id':cid,'source_ref':f'analysis/legal-corpus/draft-v0.1/inputs/{sid}.json',
                      'source_sha256':doc['source_sha256'],'view':doc['view'],'limitations':doc['limitations'],
                      'blocks':[{'id':b['block_id'],'text':b['text']} for b in doc['blocks']],
                      'context':CONTEXT | {'stage':'unknown','contract_type':'历史合同重建正文'},
                      'bundle':{'id':f'bundle:{cid}','document_version_id':sid,'materials':[],'assertions':[],'links':[]},
                      'operations':[{'action':'review'}]})
        labels.append({'case_id':cid,'provenance':'historical','approved_for_scoring':False,
                       'expected_checks':[],'linked_case_ids':related,
                       'label_ref':'analysis/legal-corpus/draft-v0.1/cases.labels.jsonl',
                       'original_approval_flags':{c:original_labels[c]['approved_for_scoring'] for c in related},
                       'reason':'原始案例未逐项批准，且没有同五规则直接对应的已确认预期；仅观察'})
    attachment_states = {'I01': [], 'I02':['missing'], 'I03':['title_only'], 'I04':['matched'], 'I05':['version_conflict'], 'I06':['matched'], 'I07':['future_template'], 'I08':['missing'], 'I09':['missing']*3, 'I10':['matched','missing','missing'], 'I11':['unreadable'], 'I12':['unreadable'], 'I13':['missing'], 'I14':['matched']}
    for label in labels:
        if label['case_id'] in attachment_states:
            label['expected_attachment_states'] = attachment_states[label['case_id']]
    for filename,rows in [('interactive.inputs.jsonl',cases),('interactive.expectations.jsonl',labels)]:
        (HERE/filename).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))

if __name__=='__main__': main()
