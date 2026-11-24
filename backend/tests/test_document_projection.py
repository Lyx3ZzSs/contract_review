import json
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
import pytest
from app.parser import parse_docx, namespace_parsed, W
from app.proposal_document import document, paragraph_evidence
from app.document_projection_migration import paragraph_projection, translate_payload
from app.store import Store


def package(body):
    stream = BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('word/document.xml', f'<w:document xmlns:w="{W[1:-1]}"><w:body>{body}</w:body></w:document>')
    return stream.getvalue()


PROPERTIES = '<w:pPr><w:tabs><w:tab w:val="clear" w:pos="420"/><w:tab w:val="left" w:pos="5295"/></w:tabs></w:pPr>'
BODY = '<w:r><w:t>😀验收</w:t><w:tab/><w:t>尾</w:t></w:r>'


def test_tab_stops_are_not_body_characters_but_real_tabs_and_unicode_are():
    blob = package('<w:p>'+PROPERTIES+BODY+'</w:p>')
    assert parse_docx(blob)['blocks'][0]['text'] == '😀验收\t尾'
    root, _ = document(blob)
    projection = paragraph_projection(next(root.iter(W+'p')))
    assert projection == {'old': '\t\t😀验收\t尾', 'text': '😀验收\t尾', 'offsets': [0, 0, 0, 1, 2, 3, 4, 5]}
    changed = translate_payload({'block_id':'v:p1','start':3,'end':5,'quote':'验收'}, {'v:p1':projection})
    assert changed == {'block_id':'v:p1','start':1,'end':3,'quote':'验收'}


def test_saved_evidence_and_parser_ignore_properties_and_preserve_real_body_tab_offsets():
    blob = package('<w:p>'+PROPERTIES+'<w:r><w:tab/></w:r>'
        '<w:bookmarkStart w:id="1" w:name="target"/><w:commentRangeStart w:id="2"/>'
        '<w:del w:id="3"><w:r><w:delText>旧文</w:delText></w:r></w:del>'
        '<w:ins w:id="4"><w:r><w:t>😀新文</w:t></w:r></w:ins>'
        '<w:commentRangeEnd w:id="2"/><w:bookmarkEnd w:id="1"/></w:p>')
    assert parse_docx(blob)['blocks'][0]['text'] == '\t😀新文'
    root, _ = document(blob)
    marks, comments, revisions = paragraph_evidence(next(root.iter(W+'p')))
    assert marks['target'] == comments['2'] == (1, 4)
    assert [(r[0],r[2],r[3],r[4]) for r in revisions] == [('del','旧文',1,1),('ins','😀新文',1,4)]


def legacy_store(tmp_path, corrupt=False):
    path = tmp_path/'legacy.sqlite3'
    store = Store(path)
    blob = package('<w:p>'+PROPERTIES+BODY+'</w:p>')
    parsed = namespace_parsed(parse_docx(blob), 'v')
    parsed['parser_version'] = 'docx-paragraphs-v2'
    parsed['blocks'][0]['text'] = '\t\t😀验收\t尾'
    parsed['source_document'] = {'filename':'original.doc','format':'doc','sha256':'original'}
    anchor = {'block_id':'v:p1','start':3,'end':5,'quote':'验收'}
    proposal = {'id':'p','before_text':'验收','after_text':'已验收','anchor':anchor,'rationale':'保留审查意见'}
    run = {'id':'r','revision_proposals':[proposal], 'evidence':[anchor], 'document_version_id':'v'}
    target = {'version':'v','blockId':'v:p1','paragraph':'\t\t😀验收\t尾', 'quote':'验收','start':3,'end':5,'blocks':[{'id':'v:p1','text':'\t\t😀验收\t尾'}]}
    op = {'id':'o','state':'prepared','mode':'ALL','target':target,'after_text':'已验收','expected_blocks':['错误' if corrupt else '\t\t😀已验收\t尾']}
    with store.connect() as db:
        db.execute('INSERT INTO contracts VALUES(?,?,?)', ('c','{}','now'))
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)', ('v','c',1,sha256(blob).hexdigest(),'c.docx',blob,json.dumps(parsed),'now'))
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)', ('r','c','v','idem','hash','completed',json.dumps(run),'now'))
        db.execute('INSERT INTO proposal_operations VALUES(?,?,?,?,?,?)', ('o','c','r','p',json.dumps(op),'now'))
        db.execute('INSERT INTO review_execution_events VALUES(?,?,?)', ('r',1,json.dumps({'evidence':[anchor]})))
        db.execute('PRAGMA user_version=10')
    return path, blob, parsed, run, op


def test_migration_repairs_existing_anchors_operations_events_and_preserves_audit_and_bytes(tmp_path):
    path, blob, old_parsed, old_run, old_op = legacy_store(tmp_path)
    store = Store(path)
    with store.connect() as db:
        version = db.execute('SELECT * FROM versions').fetchone()
        assert version['id'] == 'v' and version['revision'] == 1 and version['content'] == blob
        assert version['sha256'] == sha256(blob).hexdigest()
        parsed = json.loads(version['parsed'])
        assert parsed['parser_version'] == 'docx-paragraphs-v3'
        assert parsed['blocks'][0]['text'] == '😀验收\t尾'
        assert parsed['source_document'] == old_parsed['source_document']
        run = json.loads(db.execute('SELECT payload FROM runs').fetchone()[0])
        assert run['revision_proposals'][0]['anchor'] == {'block_id':'v:p1','start':1,'end':3,'quote':'验收'}
        assert run['revision_proposals'][0]['rationale'] == '保留审查意见'
        op = json.loads(db.execute('SELECT payload FROM proposal_operations').fetchone()[0])
        assert op['state'] == 'prepared'
        assert op['target']['start'] == 1 and op['target']['end'] == 3
        assert op['expected_blocks'] == ['😀已验收\t尾']
        event = json.loads(db.execute('SELECT payload FROM review_execution_events').fetchone()[0])
        assert event['evidence'][0]['start'] == 1
        originals = {r['table_name']:json.loads(r['original']) for r in db.execute('SELECT * FROM document_projection_backups')}
        assert originals['versions'] == old_parsed and originals['runs'] == old_run and originals['proposal_operations'] == old_op
        count = db.execute('SELECT count(*) FROM document_projection_backups').fetchone()[0]
    with Store(path).connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 12
        assert db.execute('SELECT count(*) FROM document_projection_backups').fetchone()[0] == count


def test_inconsistent_operation_rolls_back_entire_migration(tmp_path):
    path, _, parsed, _, _ = legacy_store(tmp_path, corrupt=True)
    with pytest.raises(ValueError, match='inconsistent proposal operation'):
        Store(path)
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 10
        assert json.loads(db.execute('SELECT parsed FROM versions').fetchone()[0]) == parsed
        assert db.execute('SELECT count(*) FROM document_projection_backups').fetchone()[0] == 0


def test_no_fuzzy_repair_of_invalid_anchors_and_real_body_tabs_are_not_removed():
    blob = package('<w:p>'+PROPERTIES+'<w:r><w:tab/></w:r>'+BODY+'</w:p>')
    root, _ = document(blob)
    projection = paragraph_projection(next(root.iter(W+'p')))
    assert projection['text'] == '\t😀验收\t尾'
    invalid = {'block_id':'v:p1','start':0,'end':2,'quote':'验收'}
    assert translate_payload(invalid, {'v:p1':projection}) == invalid
