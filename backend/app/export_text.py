"""Plain-text normalization shared by report rendering and content assembly."""
from html import unescape
import re


def clean(value, labels=None):
    """Readable text only. Do not reinterpret or fill business conditions."""
    value = unescape(str(value or ''))
    value = re.sub(r'<\s*br\s*/?\s*>', '\n', value, flags=re.I)
    value = re.sub(r'</(?:p|div|li)\s*>', '\n', value, flags=re.I)
    value = re.sub(r'</?(?:p|div|span|li|ul|ol|strong|em|b|i|u|s|del|ins|table|thead|tbody|tr|td|th|a|h[1-6])(?:\s+[^>]*)?\s*>', '', value, flags=re.I)
    value = re.sub(r'`?\bline(\d+)(?:\s*[-–]\s*(?:line)?(\d+))?`?',
                   lambda m: '、'.join((labels or {}).get(f'line{int(n):03}', '相关原文') for n in m.groups() if n), value)
    value = re.sub(r'^\s*#{1,6}\s+', '', value, flags=re.M).replace('**','').replace('\\*','*')
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value)
    return value.strip()

