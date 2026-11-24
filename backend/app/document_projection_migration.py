"""Repair v2 derived text/coordinates from XML, retaining original audit payloads.

DOCX bytes, version IDs, review wording and operation states do not change. No
fuzzy matching: a coordinate is translated only against its exact v2 source.
"""
import json
from hashlib import sha256
from .parser import W, PROPERTY_TAGS, PARSER_VERSION, parse_docx, namespace_parsed, text
from .proposal_document import document


def paragraph_projection(paragraph):
    old, current, offsets = [], [], [0]

    def walk(node, properties=False):
        if node.tag in (W+'del', W+'moveFrom'):
            return
        properties = properties or node.tag in PROPERTY_TAGS
        value = (node.text or '') if node.tag == W+'t' else '\t' if node.tag == W+'tab' else '\n' if node.tag in (W+'br', W+'cr') else None
        if value is not None:
            for char in value:
                old.append(char)
                if not properties:
                    current.append(char)
                offsets.append(len(current))
            return
        for child in node:
            walk(child, properties)

    walk(paragraph)
    assert ''.join(current) == text(paragraph)
    return {'old': ''.join(old), 'text': ''.join(current), 'offsets': offsets}


def projections(content, version):
    root, _ = document(content)
    result = {}
    for i, paragraph in enumerate(root.iter(W+'p'), 1):
        projection = paragraph_projection(paragraph)
        if projection['old'] != projection['text']:
            result[f'{version}:p{i}'] = projection
    return result


def translate_payload(value, mapping):
    if isinstance(value, list):
        return [translate_payload(item, mapping) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: translate_payload(item, mapping) for key, item in value.items()}
    if value.get('parser_version') == 'docx-paragraphs-v2' and isinstance(value.get('blocks'), list):
        result['parser_version'] = PARSER_VERSION
    block_id = value.get('block_id') or value.get('blockId') or value.get('id')
    projection = mapping.get(block_id) if isinstance(block_id, str) else None
    if projection:
        old, new, offsets = projection['old'], projection['text'], projection['offsets']
        for key in ('text', 'paragraph'):
            if value.get(key) == old:
                result[key] = new
        start, end, quote = value.get('start'), value.get('end'), value.get('quote')
        if type(start) is int and type(end) is int and isinstance(quote, str):
            # Invalid historical anchors remain invalid. Never repair by guessing.
            if 0 <= start <= end <= len(old) and old[start:end] == quote:
                start, end = offsets[start], offsets[end]
                result.update(start=start, end=end, quote=new[start:end])
    anchor = value.get('anchor')
    if isinstance(anchor, dict) and value.get('before_text') == anchor.get('quote'):
        result['before_text'] = result['anchor']['quote']
    if 'expected_blocks' in value and isinstance(value.get('target'), dict):
        target, updated = value['target'], result['target']
        old_expected = [b['text'] for b in target['blocks']]
        new_expected = [b['text'] for b in updated['blocks']]
        index = next(i for i, b in enumerate(target['blocks']) if b['id'] == target['blockId'])
        if value['mode'] != 'COMMENT':
            old_expected[index] = target['paragraph'][:target['start']] + value['after_text'] + target['paragraph'][target['end']:]
            new_expected[index] = updated['paragraph'][:updated['start']] + value['after_text'] + updated['paragraph'][updated['end']:]
        if value['expected_blocks'] != old_expected:
            raise ValueError('Cannot migrate inconsistent proposal operation: ' + str(value.get('id')))
        result['expected_blocks'] = new_expected
    return result


def migrate_projection(db):
    db.execute('''CREATE TABLE IF NOT EXISTS document_projection_backups(
        table_name TEXT NOT NULL, row_id INTEGER NOT NULL, column_name TEXT NOT NULL,
        original TEXT NOT NULL, replacement_sha256 TEXT NOT NULL,
        PRIMARY KEY(table_name,row_id,column_name))''')

    def replace(table, rowid, column, original, value):
        updated = json.dumps(value, ensure_ascii=False)
        if json.loads(original) == value:
            return
        db.execute('INSERT INTO document_projection_backups VALUES(?,?,?,?,?)',
                   (table, rowid, column, original, sha256(updated.encode()).hexdigest()))
        # All SQL identifiers below are internal constants.
        db.execute(f'UPDATE {table} SET {column}=? WHERE rowid=?', (updated, rowid))

    mapping = {}
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for row in db.execute('SELECT rowid AS migration_rowid,* FROM versions').fetchall():
        previous = json.loads(row['parsed'])
        if previous.get('parser_version') == PARSER_VERSION:
            continue
        local = projections(row['content'], row['id'])
        for block in previous['blocks']:
            if block['id'] in local and block['text'] != local[block['id']]['old']:
                raise ValueError('Stored source does not match legacy XML: ' + block['id'])
        mapping.update(local)
        parsed = {**previous, **namespace_parsed(parse_docx(row['content']), row['id'])}
        if [b['id'] for b in previous['blocks']] != [b['id'] for b in parsed['blocks']]:
            raise ValueError('Parser migration would change block identities: ' + row['id'])
        replace('versions', row['migration_rowid'], 'parsed', row['parsed'], parsed)
    materials = db.execute('SELECT rowid AS migration_rowid,* FROM material_versions').fetchall() if 'material_versions' in tables else []
    for row in materials:
        value = json.loads(row['payload'])
        if value.get('parse_status') not in ('parsed', 'partial'):
            continue
        mapping.update(projections(row['content'], row['id']))
    # Active derived snapshots and their coordinate references. Exported artifacts
    # and historical legal-case records are left as originally issued.
    for table in ('material_versions', 'material_bundles', 'runs', 'results', 'extractions',
                  'review_execution_states', 'review_execution_events', 'review_checkpoints',
                  'proposal_operations', 'proposal_rechecks', 'import_requests'):
        if table not in tables:
            continue
        for row in db.execute(f'SELECT rowid AS migration_rowid,payload FROM {table}').fetchall():
            value = translate_payload(json.loads(row['payload']), mapping)
            replace(table, row['migration_rowid'], 'payload', row['payload'], value)
