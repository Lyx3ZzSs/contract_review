"""Read native Word structure without changing a single source character."""
import re

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def value(node, path, default=None):
    child = node.find('/'.join(W + part for part in path.split('/'))) if node is not None else None
    return child.get(W + 'val', default) if child is not None else default


def integer(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def chinese(n):
    if not 0 <= n < 10000:
        return None
    digits = '零一二三四五六七八九'
    if n == 0:
        return digits[0]
    out = ''; zero = False
    for power, unit in [(1000, '千'), (100, '百'), (10, '十'), (1, '')]:
        d, n = divmod(n, power)
        if d:
            if zero: out += '零'
            out += digits[d] + unit
            zero = False
        elif out and n:
            zero = True
    return out[1:] if out.startswith('一十') else out


def format_counter(n, fmt):
    if fmt == 'decimal': return str(n)
    if fmt == 'decimalZero': return str(n).zfill(2)
    # These formats are distinct in MS-DOCX 2.4 numFmt; do not substitute
    # ordinary Chinese numbers for ideographTraditional (甲乙丙…).
    if fmt == 'chineseCountingThousand': return chinese(n)
    if fmt == 'chineseCounting' and 0 <= n < 100: return chinese(n)
    if fmt in ('upperLetter', 'lowerLetter') and 1 <= n <= 26:
        # Higher counters need the Word-specific repeated-letter convention.
        # Until covered by renderer fixtures, report a gap instead of Excel A..AA.
        s = chr(64 + n)
        return s if fmt == 'upperLetter' else s.lower()
    if fmt in ('upperRoman', 'lowerRoman') and 0 < n < 4000:
        s = ''
        for size, token in [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]:
            count, n = divmod(n, size); s += token * count
        return s if fmt == 'upperRoman' else s.lower()
    return None


class WordStructure:
    def __init__(self, styles=None, numbering=None):
        self.styles = {s.get(W+'styleId'): s for s in styles.findall(W+'style')} if styles is not None else {}
        self.default_style = next((sid for sid, s in self.styles.items() if s.get(W+'type') == 'paragraph' and s.get(W+'default') == '1'), None)
        self.abstract = {n.get(W+'abstractNumId'): n for n in numbering.findall(W+'abstractNum')} if numbering is not None else {}
        self.nums = {n.get(W+'numId'): n for n in numbering.findall(W+'num')} if numbering is not None else {}
        self.counters = {}

    def style_chain(self, sid):
        seen = set()
        while sid in self.styles and sid not in seen:
            seen.add(sid); s = self.styles[sid]; yield s
            sid = value(s, 'basedOn')

    def level(self, num_id, ilvl, seen=None):
        seen = set() if seen is None else seen
        if num_id in seen: return None
        seen.add(num_id)
        num = self.nums.get(num_id)
        abstract = self.abstract.get(value(num, 'abstractNumId'))
        if abstract is None: return None
        level = abstract.find(f"{W}lvl[@{W}ilvl='{ilvl}']")
        linked_style = value(abstract, 'numStyleLink')
        inherited = None
        if level is None and linked_style:
            for style in self.style_chain(linked_style):
                linked_num = value(style, 'pPr/numPr/numId')
                if linked_num:
                    inherited = self.level(linked_num, ilvl, seen)
                    if inherited: break
        override = num.find(f"{W}lvlOverride[@{W}ilvl='{ilvl}']")
        if override is not None and override.find(W+'lvl') is not None:
            level = override.find(W+'lvl')
        if level is None:
            if inherited and value(override, 'startOverride') is not None:
                inherited = {**inherited, 'start':integer(value(override,'startOverride'), inherited['start'])}
            return inherited
        return {'start': integer(value(override, 'startOverride', value(level, 'start', '1')), 1),
                'format': value(level, 'numFmt', 'decimal'), 'pattern': value(level, 'lvlText', ''),
                'restart': integer(value(level, 'lvlRestart')), 'legal': level.find(W+'isLgl') is not None}

    def paragraph(self, p):
        ppr = p.find(W+'pPr')
        sid = value(ppr, 'pStyle', self.default_style)
        chain = list(self.style_chain(sid))
        properties = [ppr] + [s.find(W+'pPr') for s in chain]
        def inherited(path):
            return next((v for prop in properties if (v := value(prop, path)) is not None), None)
        meta = {}
        if sid: meta['style_id'] = sid
        outline = integer(inherited('outlineLvl'))
        if outline is None:
            for style in chain:
                name = value(style, 'name', '')
                match = re.fullmatch(r'(?:heading\s*|标题\s*)([1-9])', name, re.I)
                if match:
                    outline = int(match[1])-1; break
        if outline is not None and 0 <= outline <= 8:
            meta['heading_level'] = outline + 1
        num_id = inherited('numPr/numId')
        if num_id in (None, '0'): return meta
        ilvl = integer(inherited('numPr/ilvl'), 0)
        meta['automatic_numbering'] = True
        info = {'num_id':num_id, 'level':ilvl, 'resolved':False}
        meta['numbering'] = info
        spec = self.level(num_id, ilvl)
        if not spec or not 0 <= ilvl <= 8:
            info['gap'] = '自动编号定义缺失或层级无效'; return meta
        counters = self.counters.setdefault(num_id, {})
        counters[ilvl] = counters.get(ilvl, spec['start']-1) + 1
        for deeper in list(counters):
            if deeper <= ilvl: continue
            ds = self.level(num_id, deeper)
            restart = ds['restart'] if ds else None
            # lvlRestart is one-based; 0 explicitly means never restart.
            trigger = deeper-1 if restart is None else restart-1
            if restart != 0 and ilvl <= trigger: del counters[deeper]
        info['format'] = spec['format']
        if spec['format'] == 'bullet':
            info.update(resolved=True, label=spec['pattern'], ordered=False); return meta
        unsupported = False
        def substitute(match):
            nonlocal unsupported
            level = int(match[1])-1; s = self.level(num_id, level)
            formatted = format_counter(counters.get(level, s['start']), 'decimal' if spec['legal'] else s['format']) if s else None
            if formatted is None: unsupported = True
            return formatted or match[0]
        label = re.sub(r'%([1-9])', substitute, spec['pattern'])
        if unsupported or not label:
            info['gap'] = '自动编号格式暂不支持'; return meta
        info.update(resolved=True, label=label, ordered=True)
        return meta
