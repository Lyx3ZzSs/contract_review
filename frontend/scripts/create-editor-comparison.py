"""Create an isolated synthetic DOCX contract for the development comparison page.

Run from the repository root. Requires python-docx and httpx in the chosen Python.
No review job/model is started. The returned test contract is retained for manual inspection.
"""
import argparse
import json
from pathlib import Path

import httpx
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8011/api/v1')
    parser.add_argument('--output', type=Path, default=Path('.local/editor-comparison'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    document = Document()
    style = document.styles['Normal']
    style.font.name = 'SimSun'
    style.font.size = Pt(12)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
    document.add_heading('合成服务合同 · 阅读引擎验证', 0)
    for i in range(1, 19):
        if i == 4:
            document.add_paragraph('')
        if i in (3, 12):
            text = '付款应以验收合格为前提。付款应以验收合格为前提。'
        elif i == 6:
            text = '第六条 交付清单 🧾：甲方应在验收后十五日内付款；乙方提供交付证明。'
        elif i == 9:
            text = '第九条 证据核对。' + '甲乙双方应保存交付记录，并就争议事项进行书面确认。' * 35
        else:
            text = f'第{i}条 服务约定。双方应按合同约定履行义务。交付与验收记录由双方分别保存，发生争议时共同核对相关证据。'
        document.add_paragraph(text)
        if i == 14:
            table = document.add_table(rows=2, cols=2)
            table.style = 'Table Grid'
            for cell, value in zip([c for row in table.rows for c in row.cells], ['付款阶段', '触发条件', '尾款', '验收合格后支付']):
                cell.text = value
    file = args.output / 'synthetic.docx'
    document.save(file)
    with httpx.Client(base_url=args.api, timeout=60) as client:
        result = client.post('/contracts', json={'title': 'EigenPal合成只读对照', 'contract_type': '服务合同', 'our_party': '甲方', 'data_purpose': 'test'})
        result.raise_for_status()
        cid = result.json()['id']
        # Record immediately so a failed upload still leaves a recoverable test-contract ID.
        manifest = args.output / 'fixture.json'
        manifest.write_text(json.dumps({'cid': cid}), encoding='utf-8')
        result = client.post(f'/contracts/{cid}/versions', files={'file': ('synthetic.docx', file.read_bytes(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
        result.raise_for_status()
        manifest.write_text(json.dumps({'cid': cid, 'version': result.json()}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'EigenPal: http://127.0.0.1:5176/editor-comparison.html?id={cid}')
    print(f'OnlyOffice: http://127.0.0.1:5175/editor-comparison.html?id={cid}&engine=onlyoffice')


if __name__ == '__main__':
    main()
