"""Source identities and evidence checks shared by configured rule evaluators."""
import re
import unicodedata

from .structured_review import Sources, fail


class ReviewEvidence:
    def __init__(self, blocks, bundle=None, *, document_version_id=''):
        self.bundle = bundle or {}
        self.main = Sources(blocks)
        self.reviews = Sources(blocks + [
            block for material in self.bundle.get('materials', [])
            if material.get('parse_status') in ('parsed', 'partial')
            for block in material.get('blocks', [])
        ])
        self.origins = {block['id']: ('document', document_version_id) for block in blocks}
        self.liability_rows = [
            (ref, '', block['id'], '', block['text'])
            for ref, block in self.main.blocks.items()
        ]
        for index, material in enumerate(self.bundle.get('materials', []), 1):
            if material.get('parse_status') not in ('parsed', 'partial'):
                continue
            for position, block in enumerate(material.get('blocks', []), 1):
                if block['id'] in self.origins:
                    raise fail('duplicate_source_block_id')
                self.origins[block['id']] = ('material', material['id'])
                self.liability_rows.append((f'm{index}p{position}', material['id'], block['id'],
                                            material.get('filename') or '附件', block['text']))
        if len(self.origins) != len(self.reviews.blocks):
            raise fail('duplicate_source_block_id')
        self.by_id = {b['id']: b['text'] for b in self.reviews.blocks.values()}

    @property
    def partial(self):
        return self.bundle.get('document_parse_status') == 'partial' or any(
            m.get('parse_status') != 'parsed' for m in self.bundle.get('materials', [])
        )

    def provenance(self, record):
        evidence = {}
        for key in ('evidence', 'content_evidence'):
            for anchor in record.get(key, []):
                block_id = anchor['block_id']
                text = self.by_id.get(block_id)
                start, end = anchor['start'], anchor['end']
                if text is None or not 0 <= start < end <= len(text) or text[start:end] != anchor['quote']:
                    raise fail('review_evidence_outside_snapshot')
                identity = (block_id, start, end)
                kind, version = self.origins[block_id]
                evidence[identity] = {'block_id': block_id, 'start': start, 'end': end,
                                      'source_kind': kind, 'source_version_id': version}
        return list(evidence.values())


def normalized_text(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


EXPLICIT_PAYMENT = re.compile(
    r'(?P<payer>甲方|乙方)(?:(?!甲方|乙方)[^，。；、：]){0,45}'
    r'向(?P<payee>甲方|乙方)(?:(?!甲方|乙方)[^，。；、：]){0,12}(?:支付|退还|返还|赔付|赔偿)'
)


def payment_directions(text):
    return {(m['payer'], m['payee']) for m in EXPLICIT_PAYMENT.finditer(normalized_text(text))}
