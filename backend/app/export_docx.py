"""Word report layout. Contract exports never pass through this renderer."""
from difflib import SequenceMatcher
from io import BytesIO
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .export_text import clean
from .tianyancha import RISKS


def document_base(title, snapshot):
    doc=Document();section=doc.sections[0]
    section.page_width=Inches(8.5);section.page_height=Inches(11)
    section.top_margin=section.bottom_margin=Inches(.72)
    section.left_margin=section.right_margin=Inches(.78)
    for name,size in [('Normal',11),('Title',22),('Heading 1',16),('Heading 2',13),('Heading 3',11)]:
        s=doc.styles[name];s.font.name='Arial';s.font.size=Pt(size);s.font.color.rgb=RGBColor(0,0,0)
        s.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Noto Sans CJK SC')
        s.paragraph_format.space_after=Pt(7);s.paragraph_format.line_spacing=1.25
        if name.startswith('Heading'):s.paragraph_format.keep_with_next=True
    doc.add_paragraph(title,'Title')
    para(doc,snapshot['contract_title'])
    para(doc,f"导出时间：{snapshot['display_time']}\n审查立场：{snapshot['position'] or '未指定'}")
    para(doc,f"依据版本：第 {snapshot['base_revision']} 版　当前文档：第 {snapshot['current_revision']} 版" + (f"\n审查轮次：第 {snapshot['round_number']} 轮" if snapshot['round_number'] else ''))
    footer=section.footer.paragraphs[0];footer.alignment=2
    footer.add_run('第 ')
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    footer.add_run(' 页')
    doc.core_properties.title=title;doc.core_properties.subject=snapshot['contract_title'];doc.core_properties.author=''
    doc.core_properties.comments=f"导出记录 {snapshot['id']}；审查版本 {snapshot['base_version_id']}；当前版本 {snapshot['document_version_id']}"
    return doc


def para(parent,value,style=None):
    p=parent.add_paragraph(style=style)
    p.add_run(clean(value));return p


def comparison(doc,before,after,operation=None):
    # A long legal clause reads better at full width than in a narrow table cell.
    if max(len(before),len(after))>900:
        para(doc,'原文','Heading 3');para(doc,before or '（新增位置）')
        para(doc,'修改后','Heading 3');p=doc.add_paragraph();diff(p,before,after)
        return
    table=doc.add_table(rows=2, cols=2);table.autofit=False
    for col in table.columns:col.width=Inches(3.45)
    for i,title in enumerate(['原文','修改对照']):
        cell=table.cell(0,i);cell.text=title
        tcPr=cell._tc.get_or_add_tcPr();fill=OxmlElement('w:shd');fill.set(qn('w:fill'),'F0F2F5');tcPr.append(fill)
        cell.paragraphs[0].runs[0].bold=True
    repeat=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(repeat)
    table.cell(1,0).text=before or '（新增位置）'
    diff(table.cell(1,1).paragraphs[0],before,after)
    para(doc,'')


def diff(p,before,after):
    if not before and not after:p.add_run('（无文本）');return
    # Bound the quadratic worst case for unusually large clauses.
    ops=SequenceMatcher(None,before,after,autojunk=False).get_opcodes() if len(before)*len(after)<2_000_000 else [('replace',0,len(before),0,len(after))]
    for tag,a,b,c,d in ops:
        if tag=='equal':p.add_run(before[a:b]);continue
        if b>a:
            r=p.add_run(before[a:b]);r.font.strike=True;r.font.color.rgb=RGBColor.from_string('185ABD')
        if d>c:
            r=p.add_run(after[c:d]);r.font.color.rgb=RGBColor.from_string('C52D35');r.font.underline=True
    if not after:p.add_run('（删除上述文字）')


def generate(snapshot):
    full=snapshot['kind']=='opinions'
    doc=document_base('合同审查意见书' if full else '合同修改说明',snapshot)
    content=snapshot['report']
    if full:
        para(doc,f"本文件汇总本轮保留的 {len(content['risks'])} 项审查意见及 {len(content['revisions'])} 条修改建议。人工处理结论与正文应用状态分别列示。")
        if snapshot['run'].get('module_errors'):
            para(doc,'本轮部分检查未返回结果，以下仅汇总已生成的意见。')
            for error in snapshot['run']['module_errors']:para(doc,clean(error.get('message') or '检查未返回结果'))
        if content['analysis']:
            doc.add_heading('交易概况与关注点',1)
            for section in content['analysis']:
                doc.add_heading(section['title'] or '交易分析',2);para(doc,section['text'])
        categories=list(dict.fromkeys(r['category'] for r in content['risks']))
        for category in categories:
            doc.add_heading(category,1)
            for risk in [r for r in content['risks'] if r['category']==category]:
                doc.add_heading(f"{risk['number']:02} {risk['title']}",2)
                para(doc,'风险说明','Heading 3');para(doc,risk['explanation'])
                if risk['plan']:para(doc,'修改方案','Heading 3');para(doc,risk['plan'])
                for e in risk['evidence']:
                    para(doc,f"依据 {e['location']}：{e['quote']}")
                para(doc,'处理结论：'+risk['decision']+(f"\n处理说明：{risk['note']}" if risk['note'] else ''))
                if risk['proposals']:para(doc,'配套修改：'+'、'.join(risk['proposals'])+'，详见后文统一修改建议。')
        if content.get('confirmation_checks'):
            doc.add_heading('待核实事项',1)
            for check in content['confirmation_checks']:
                para(doc,check['title'],'Heading 2')
                para(doc,check['text'])
        elif not content['risks']:para(doc,'本轮未列出需处理意见，请结合审查范围及执行结果核对。')
        if content['revisions']:doc.add_heading('统一修改建议',1)
        for p in content['revisions']:
            doc.add_heading(f"{p['number']} {p['location']}",2)
            if p['risks']:para(doc,'关联风险：'+'、'.join(f'{i:02}' for i in p['risks']))
            para(doc,'正文状态：'+p['state'])
            if p['rationale']:para(doc,p['rationale'])
            comparison(doc,p['before'],p['after'],p['operation'])
            if p['confirmation']:
                para(doc,'待确认事项','Heading 3')
                for t in p['confirmation']:para(doc,'• '+t)
    else:
        changes=snapshot['changes'];mods=changes['modifications'];comments=changes['comments'];removed=changes['removed_comments']
        para(doc,f"相对依据版本，当前正文有 {len(mods)} 处文本、编号或表格位置修改，新增或调整批注 {len(comments)} 条，删除批注 {len(removed)} 条。正文对比采用包含新增文字、不含删除文字的当前拟稿。")
        para(doc,'本说明覆盖主文档段落、表格文字及批注；字体、图片、页眉页脚等请结合合同文件核对。')
        if changes.get('other_changes'):
            doc.add_heading('其他文档变化',1)
            for t in changes['other_changes']:para(doc,t)
        if mods:doc.add_heading('正文修改',1)
        for i,m in enumerate(mods,1):
            doc.add_heading(f"{i:02} {m['location']}",2);para(doc,'修改来源：'+m['source'])
            if m['format_note']:para(doc,m['format_note'])
            comparison(doc,m['before'],m['after'])
            for p in [p for p in content['revisions'] if p['id'] in m['proposal_ids']]:
                if p['rationale']:para(doc,'关联修改依据：'+p['rationale'])
                for t in p['confirmation']:para(doc,'待确认：'+t)
        for title,rows in [('新增或调整批注',comments),('已删除批注',removed)]:
            if rows:doc.add_heading(title,1)
            for i,c in enumerate(rows,1):
                doc.add_heading(f"{i:02} {c['location']}",2)
                if c['quote']:para(doc,'对应原文：'+c['quote'])
                para(doc,c['text'])
                if c['author']:para(doc,'批注作者：'+c['author'])
    if full and snapshot.get('subjects'):
        doc.add_heading('主体核查',1)
        for subject in snapshot['subjects']:
            doc.add_heading(subject['name'],2)
            para(doc,'来源：天眼查；查询时间：'+subject['queried_at'])
            para(doc,'企业匹配：'+('已匹配' if subject['matched'] else '待核对'))
            basic=subject['basic']
            if basic['state']=='ready':
                for key,label in [('name','登记名称'),('creditCode','统一社会信用代码'),('regStatus','经营状态'),('legalPersonName','法定代表人'),('regCapital','注册资本'),('businessScope','经营范围')]:
                    para(doc,label+'：'+str(basic['data'].get(key) or '未提供'))
            else:para(doc,basic['message'])
            for key,module in subject['modules'].items():
                doc.add_heading(module['label'],3)
                state=module['state']
                if module.get('last_attempt_at') or module.get('queried_at'):
                    para(doc,'最近查询时间：'+str(module.get('last_attempt_at') or module.get('queried_at')))
                if state not in ('ready','empty'):
                    para(doc,module.get('message') or '尚未查询')
                    if module.get('pages'):
                        para(doc,'以下为此前已获取的记录，获取时间：'+str(module.get('queried_at') or '未提供'))
                if state=='empty':para(doc,'本次查询未发现相关记录。')
                pages=[page for _,page in sorted(module.get('pages',{}).items(),key=lambda item:int(item[0]))]
                if key in RISKS:
                    records=[record for page in pages for record in page.get('records',[])]
                    if records:
                        total=(module.get('data') or {}).get('total','未知')
                        para(doc,f'已加载 {len(records)} / {total} 条，以下仅列出已获取记录；当前或历史状态以记录字段为准。')
                    for record in records:
                        para(doc,record['title'],'Heading 3')
                        for field in record['fields']:para(doc,field['label']+'：'+field['value'])
                        detail=module.get('details',{}).get(record.get('detail_id'))
                        if detail:
                            para(doc,'案件详情查询时间：'+str(detail.get('queried_at','未提供')))
                            if detail['state']=='ready':
                                for field in detail['data']['record']['fields']:para(doc,field['label']+'：'+field['value'])
                            else:para(doc,detail.get('message') or '案件详情未返回')
                elif key=='scale' and state=='ready':para(doc,str(module['data']))
                elif key=='ownership' and state=='ready':para(doc,{1:'中央企业',2:'地方国有企业',3:'中央部委',4:'地方政府',5:'民营企业',6:'其他',7:'事业单位',8:'个体工商户'}.get(module['data'].get('companyType'),'未提供'))
                elif key=='shareholders':
                    items=[item for page in pages for item in page.get('items',[])]
                    if items:para(doc,f"工商登记来源；已加载 {len(items)} / {module['data']['total']} 条，以下为已获取记录。")
                    for item in items:
                        para(doc,item.get('name','未提供'),'Heading 3')
                        for field,label in [('capital','认缴'),('capitalActl','实缴')]:
                            para(doc,label+'：'+'；'.join(' / '.join(str(v.get(k) or '未提供') for k in ('amomon','percent','time')) for v in item.get(field,[])))
            decision=subject.get('decision')
            if decision:para(doc,'核查记录：'+{'confirmed':'已确认企业匹配','reviewed':'已核实','needs_material':'待补材料'}.get(decision['action'],decision['action'])+'；'+decision.get('note',''))
    doc.add_heading('文件来源',1)
    para(doc,f"导出编号：{snapshot['id']}\n依据文档版本：{snapshot['base_version_id']}\n当前文档版本：{snapshot['document_version_id']}\n审查任务：{(snapshot['run'] or {}).get('id') or '未发起审查'}")
    para(doc,'本文件按导出时固定的数据生成。导出不改变意见处理状态或正文内容。')
    out=BytesIO();doc.save(out);return out.getvalue()
