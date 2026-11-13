export type RiskStatus = 'pending' | 'accepted' | 'ignored'
export type Severity = 'high' | 'medium' | 'low'
export interface Risk {
  id: string; title: string; severity: Severity; chapter: number; clause: string;
  category: string; original: string; suggestion: string; explanation: string;
  rule: string; rationale: string; reference: string; referenceText: string
}
export const contract = {
  title: '功率预测技术服务合同', number: 'RX-2026-1142', version: 'V2',
  client: '北辰新能源有限公司（示例）', supplier: '国能日新科技股份有限公司',
  project: '北辰风电场 · 100 MW', amount: '128,600.00', term: '2027.01.01 — 2027.12.31',
}
export const risks: Risk[] = [
  {
    id: 'r1', title: '电网考核责任未设边界', severity: 'high', chapter: 4, clause: '4.2', category: '责任承担',
    original: '因功率预测不满足电网要求产生的全部考核费用，由乙方承担。',
    suggestion: '经双方确认由乙方原因直接导致的电网考核费用，由乙方在本合同年度服务费总额范围内承担。因甲方数据缺失、通讯中断、电网规则变更或不可抗力导致的考核费用，不属于乙方责任范围。',
    explanation: '“全部考核费用”将预测结果与无限责任直接绑定，未区分数据、通信及调度因素，也未约定赔偿上限。建议限定归责条件、免责情形与责任总额。',
    rule: '责任应与可控制的服务范围相匹配', rationale: '建议谈判口径：仅承担可归责于乙方的直接损失，并约定累计责任上限；具体上限须由业务与法务共同确认。',
    reference: '关联原文 § 2.2 · 数据与通信', referenceText: '甲方负责提供完整、准确、连续的场站运行数据，并保障数据传输网络正常运行。',
  },
  {
    id: 'r2', title: '验收期限及默认通过机制缺失', severity: 'high', chapter: 3, clause: '3.2', category: '交付验收',
    original: '系统安装完成后，乙方提交验收申请，由甲方组织验收，具体验收时间以甲方通知为准。',
    suggestion: '乙方提交验收申请后，甲方应在十个工作日内完成验收并出具书面意见；如有异议，应一次性列明具体问题。甲方逾期未提出书面异议且系统已正常投入使用的，视为验收通过。',
    explanation: '验收由甲方单方决定且没有期限，可能拖延与验收挂钩的付款。建议明确验收时限、异议反馈方式和逾期处理。',
    rule: '交付验收应具备可执行的时间节点', rationale: '建议谈判口径：交付通知、验收标准、书面异议与付款节点应相互衔接。',
    reference: '关联原文 § 5.2 · 付款安排', referenceText: '合同总价的 70% 于验收完成且甲方收到合规发票后支付。',
  },
  {
    id: 'r3', title: '付款节点缺少明确账期', severity: 'high', chapter: 5, clause: '5.2', category: '付款条件',
    original: '合同总价的 70% 于验收完成且甲方收到合规发票后支付，具体支付时间由甲方资金计划安排。',
    suggestion: '合同总价的 70% 于验收完成且甲方收到合规发票后三十日内支付。甲方内部资金计划不影响本合同约定的付款期限。',
    explanation: '付款条件满足后仍由甲方资金计划决定支付时间，实际回款节点无法确定。建议增加明确的付款期限。',
    rule: '付款条件满足后应有确定账期', rationale: '建议谈判口径：把验收、开票、到期支付分别约定，避免付款受单方内部流程无限期影响。',
    reference: '关联原文 § 3.2 · 验收安排', referenceText: '由甲方组织验收，具体验收时间以甲方通知为准。',
  },
  {
    id: 'r4', title: '免费升级范围过宽', severity: 'medium', chapter: 2, clause: '2.3', category: '服务边界',
    original: '乙方应根据甲方需求，免费提供系统所有功能的升级、改造及新增接口服务。',
    suggestion: '乙方在服务期内免费提供本合同既有功能的缺陷修复与常规版本升级。新增功能、定制改造及新增接口由双方另行确认工作范围、费用和交付期限。',
    explanation: '“所有功能”“新增接口”没有边界，可能把额外开发纳入年度服务费。建议区分维护升级与新增需求。',
    rule: '常规维护与新增开发分别约定', rationale: '建议谈判口径：需求变更通过书面变更单确认，新增开发单独报价。',
    reference: '关联原文 § 1.2 · 服务范围', referenceText: '本合同服务范围包括短期及超短期功率预测、运行监测和常规技术支持。',
  },
  {
    id: 'r5', title: '既有算法的知识产权归属不清', severity: 'medium', chapter: 6, clause: '6.1', category: '知识产权',
    original: '乙方履行本合同形成及使用的软件、算法、模型和技术资料等全部知识产权归甲方所有。',
    suggestion: '双方在本合同签订前已拥有的知识产权仍归原权利人所有。乙方通用软件、预测算法与模型及其改进成果归乙方所有，甲方获得服务期内为本项目使用相关交付成果的非独占许可。定制开发成果的权属由双方另行书面约定。',
    explanation: '“形成及使用”可能涵盖乙方原有算法、模型和软件，扩大了权利转让范围。应将既有技术与定制成果区分。',
    rule: '保护既有技术与通用能力的权属', rationale: '建议谈判口径：先明确既有知识产权，再约定交付物许可范围与定制成果权属。',
    reference: '关联原文 § 1.1 · 项目概况', referenceText: '乙方基于自主功率预测系统，为甲方提供风电功率预测服务。',
  },
  {
    id: 'r6', title: '续约通知期限未约定', severity: 'low', chapter: 7, clause: '7.2', category: '续约安排',
    original: '服务期届满后，双方可协商续约；未续约期间乙方应继续提供服务。',
    suggestion: '双方应在服务期届满前三十日协商续约。未达成书面续约协议的，本合同于服务期届满时终止；如需过渡服务，双方应另行约定期限及费用。',
    explanation: '未续约期间继续服务没有期限和费用安排，可能造成无偿服务义务。建议约定提前沟通及过渡服务机制。',
    rule: '续约与过渡服务应有明确期限', rationale: '建议谈判口径：持续服务需与有效合同或书面过渡安排相匹配。',
    reference: '关联原文 § 7.1 · 服务期限', referenceText: '本合同服务期为 2027 年 1 月 1 日至 2027 年 12 月 31 日。',
  },
]
export interface Clause { number: string; text: string; riskId?: string }
export interface Chapter { id: number; title: string; page: number; clauses: Clause[] }
export const chapters: Chapter[] = [
  { id: 1, title: '项目概况与服务范围', page: 1, clauses: [
    { number: '1.1', text: '乙方基于自主功率预测系统，为甲方北辰风电场（装机容量 100 MW）提供风电功率预测服务。双方本着平等、自愿的原则，就本项目技术服务事项达成如下约定。' },
    { number: '1.2', text: '本合同服务范围包括短期及超短期功率预测、运行监测和常规技术支持。详细技术要求以双方签署的《技术服务附件》为准。' },
  ] },
  { id: 2, title: '双方权利与义务', page: 1, clauses: [
    { number: '2.1', text: '乙方应安排具备相应能力的技术人员开展系统部署、运行维护与故障处理，并按约定提供技术支持服务。' },
    { number: '2.2', text: '甲方负责提供完整、准确、连续的场站运行数据，并保障数据传输网络正常运行。甲方应指定项目联系人，协调现场安装和调试工作。' },
    { number: '2.3', text: risks[3].original, riskId: 'r4' },
  ] },
  { id: 3, title: '交付与验收', page: 2, clauses: [
    { number: '3.1', text: '乙方应在合同生效且具备现场实施条件后三十日内完成系统部署及调试，并向甲方提交系统操作说明、部署记录等相关交付资料。' },
    { number: '3.2', text: risks[1].original, riskId: 'r2' },
    { number: '3.3', text: '验收内容包括系统功能、数据接入、预测结果输出及运行稳定性，具体要求以本合同技术附件约定的验收标准为准。' },
  ] },
  { id: 4, title: '服务质量与责任承担', page: 2, clauses: [
    { number: '4.1', text: '乙方应按照本合同及技术附件的约定提供功率预测服务，协助甲方满足项目所在地电网调度机构的预测数据报送要求。' },
    { number: '4.2', text: risks[0].original, riskId: 'r1' },
    { number: '4.3', text: '在服务期间，如系统发生故障，乙方应在接到甲方通知后及时响应，并根据故障情况通过远程或现场方式提供技术支持。' },
  ] },
  { id: 5, title: '合同价款与支付方式', page: 3, clauses: [
    { number: '5.1', text: '本合同含税服务费总额为人民币 128,600.00 元（大写：壹拾贰万捌仟陆佰元整）。合同签订后十个工作日内，甲方向乙方支付合同总价的 30%。' },
    { number: '5.2', text: risks[2].original, riskId: 'r3' },
    { number: '5.3', text: '乙方应根据合同约定提供合法有效的增值税发票，双方开票及收款信息以书面通知为准。' },
  ] },
  { id: 6, title: '知识产权与保密', page: 3, clauses: [
    { number: '6.1', text: risks[4].original, riskId: 'r5' },
    { number: '6.2', text: '双方对履行合同过程中获悉的对方技术信息、经营信息及其他保密信息承担保密义务，未经对方书面同意不得向第三方披露，法律法规另有规定的除外。' },
  ] },
  { id: 7, title: '服务期限与续约', page: 4, clauses: [
    { number: '7.1', text: '本合同服务期为 2027 年 1 月 1 日至 2027 年 12 月 31 日。' },
    { number: '7.2', text: risks[5].original, riskId: 'r6' },
  ] },
  { id: 8, title: '争议解决与其他', page: 4, clauses: [
    { number: '8.1', text: '双方因本合同发生争议，应先协商解决；协商不成的，任何一方可向乙方住所地有管辖权的人民法院提起诉讼。' },
    { number: '8.2', text: '本合同自双方加盖公章或合同专用章之日起生效。本合同一式肆份，甲乙双方各执贰份，具有同等效力。附件为本合同不可分割的组成部分。' },
  ] },
]
export const severityLabel: Record<Severity, string> = {high:'高风险',medium:'中风险',low:'提示'}
export const statusLabel: Record<RiskStatus, string> = {pending:'待处理',accepted:'已采纳',ignored:'已忽略'}
