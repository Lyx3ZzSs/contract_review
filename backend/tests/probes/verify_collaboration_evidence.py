"""Verify the real browser-run DOCX artifacts, not a mocked editor."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
from defusedxml import ElementTree as ET

NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def inspect(path):
    with ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
        result = {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                  'text':''.join(root.itertext()),
                  'authors':sorted({e.attrib.get('{'+NS['w']+'}author','') for e in root.findall('.//w:ins',NS)}),
                  'insertions':len(root.findall('.//w:ins',NS))}
        if 'word/comments.xml' in z.namelist():
            result['comments'] = ''.join(ET.fromstring(z.read('word/comments.xml')).itertext())
        return result


def verify(output):
    before = inspect(output/'snapshot-1.docx')
    bypass = inspect(output/'snapshot-2.docx')
    normal = inspect(output/'normal-flow/snapshot-1.docx')
    frozen = inspect(output/'bridge-flow/snapshot-1.docx')
    sealed = inspect(output/'bridge-flow/snapshot-2.docx')
    assert before['insertions'] == 2
    assert bypass['insertions'] == 0
    assert all(marker in normal['text'] for marker in ('ALICE-P0-', 'BOB-P0-', 'CAROL-P0-'))
    assert len(normal['authors']) == 3
    assert 'BOB 批注：请确认服务期限。' in normal['comments']
    assert 'B-WHILE-A-FROZEN-' in frozen['text']
    assert '中文组合输入' in sealed['text']
    events = json.loads((output/'bridge-flow/events.json').read_text())['events']
    assert any(e['payload'].get('status')==6 for e in events)
    assert any(e['payload'].get('status')==2 for e in events)
    result = {'artifacts_verified':True, 'production_collaboration_accepted':False,
              'review_groups_sdk_bypass_observed':True,
              'exports':{'before':before,'after_sdk_accept':bypass,'normal':normal,'frozen':frozen,'sealed':sealed}}
    (output/'artifact-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = verify(args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='exports'},ensure_ascii=False))
