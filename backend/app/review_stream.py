"""Display-only JSON prefixes. Final schema/evidence validation remains mandatory."""
import json
import time

FACT_LABELS = {'transaction':'交易类型及我方立场','obligations':'双方主要义务','amount':'金额及其性质',
               'payment':'付款条件','period':'履约周期','uncertainties':'待确认事项'}

FACT_SECTIONS = {key: (index, label) for index, (key, label) in enumerate(FACT_LABELS.items())}


class Incomplete(Exception):
    pass


def display_fields(text, on_section=None):
    """Parse a JSON prefix, exposing only allowlisted string values, never keys/reasoning."""
    fields = {}
    n = len(text)
    def space(i):
        while i < n and text[i].isspace(): i += 1
        return i
    def string(i):
        start = i
        i += 1
        while i < n:
            if text[i] == '"': return json.loads(text[start:i+1]), i+1, True
            if text[i] == '\\':
                if i+1 >= n: break
                if text[i+1] == 'u':
                    if i+6 > n: break
                    # Do not expose half of an escaped surrogate pair.
                    code = int(text[i+2:i+6], 16)
                    if 0xD800 <= code <= 0xDBFF:
                        if i+12 > n: break
                        i += 12
                        continue
                    i += 6
                    continue
                i += 2
            else: i += 1
        return json.loads(text[start:i]+'"'), i, False
    def value(i, path, depth=0):
        if depth > 12: raise ValueError('JSON nesting limit')
        i = space(i)
        if i >= n: raise Incomplete()
        if text[i] == '"':
            s, end, complete = string(i)
            if len(path) == 2 and path[0] in FACT_SECTIONS and path[1] == 'value':
                index, label = FACT_SECTIONS[path[0]]
                fields[f'section:{index}:title'] = label
                fields[f'section:{index}:text'] = s[:5000]
            if path == ('explanation',): fields['explanation'] = s[:1800]
            if path == ('modification_plan',): fields['modification_plan'] = s[:1800]
            if len(path) == 3 and path[0] == 'risk_paragraphs' and isinstance(path[1], int) and path[1] < 6 and path[2] == 'text':
                fields[f'risk:{path[1]}:text'] = s[:5000]
            if len(path) == 3 and path[0] == 'sections' and isinstance(path[1], int) and path[1] < 6 and path[2] in ('title', 'text'):
                fields[f'section:{path[1]}:{path[2]}'] = s[:5000 if path[2] == 'text' else 100]
            if len(path) == 3 and path[0] == 'checks' and isinstance(path[1], int) and path[1] < 3 and path[2] in ('title', 'text'):
                fields[f'check:{path[1]}:{path[2]}'] = s[:5000 if path[2] == 'text' else 100]
            if len(path) == 3 and path[0] == 'findings' and isinstance(path[1], int) and path[1] < 12 and path[2] in ('title', 'explanation'):
                key='text' if path[2]=='explanation' else 'title'
                fields[f'section:{path[1]}:{key}'] = s[:1800 if key=='text' else 120]
            if (s or complete) and len(path) == 3 and path[0] == 'edits' and isinstance(path[1], int) and path[1] < 5 and path[2] in ('after_text', 'rationale'):
                fields[f'edit:{path[1]}:{path[2]}'] = s[:6500 if path[2] == 'after_text' else 900]
            if not complete: raise Incomplete()
            return end
        if text[i] in '{[':
            start = i
            obj = text[i] == '{'; close = '}' if obj else ']'; i += 1; index = 0
            while True:
                i = space(i)
                if i >= n: raise Incomplete()
                if text[i] == close: break
                if obj:
                    if text[i] != '"': raise ValueError('Expected object key')
                    key, i, complete = string(i)
                    if not complete: raise Incomplete()
                    i = space(i)
                    if i >= n: raise Incomplete()
                    if text[i] != ':': raise ValueError('Expected colon')
                    i += 1
                else: key = index
                i = space(value(i, path+(key,), depth+1)); index += 1
                if i >= n: raise Incomplete()
                if text[i] == close: break
                if text[i] != ',': raise ValueError('Expected comma')
                i += 1
            if on_section and obj and len(path)==2 and path[0]=='sections' and isinstance(path[1],int) and path[1]<6:
                on_section(path[1], text[start:i+1])
            return i+1
        while i < n and text[i] not in ',}]': i += 1
        if i >= n: raise Incomplete()
        return i
    try: value(0, ())
    except (Incomplete, ValueError, json.JSONDecodeError): pass
    return fields


class DisplayStream:
    def __init__(self, callback, section_callback=None):
        self.section_callback = section_callback
        self.finished_sections = set()
        self.callback = callback
        self.text = ''
        self.sent = {}
        self.last = 0
    def feed(self, chunk, force=False):
        self.text += chunk
        if len(self.text) > 160000: raise ValueError('Review output limit')
        now = time.monotonic()
        if not force and now-self.last < .15: return
        changes = []
        def completed(index, raw):
            if index not in self.finished_sections:
                self.finished_sections.add(index)
                self.section_callback(json.loads(raw))
        for key, text in display_fields(self.text, completed if self.section_callback else None).items():
            old = self.sent.get(key, '')
            if text.startswith(old) and (text != old or key not in self.sent):
                changes.append({'field':key, 'offset':len(old), 'text':text[len(old):]})
                self.sent[key] = text
        if changes: self.callback('delta', changes=changes)
        self.last = now
