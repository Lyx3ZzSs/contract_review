"""Exact paragraph relocation; this proves a location, not semantic applicability."""
from array import array

MAX_ALIGNMENT_CELLS = 1_000_000


class AnchorError(ValueError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def relocate_anchor(source, blocks, block_id, quote, start, end, *, expected_paragraph=None):
    """Resolve a nonempty exact range in a saved proposed-view document.

    Version-scoped IDs identify only the source paragraph. For a previously
    applied revision the caller supplies its expected paragraph and adjusted
    quote/offsets, after checking the original proposal against its source.
    Repeated paragraphs need an unavoidable, unique ordered alignment; a mere
    possible LCS match is insufficient (one duplicate may have been removed).
    """
    source_indexes = [i for i, b in enumerate(source) if b.get('id') == block_id]
    if not block_id or len(source_indexes) != 1:
        raise AnchorError('invalid_anchor', '建议的原文段落标识无效或不唯一')
    source_index = source_indexes[0]
    expected = source[source_index].get('text') if expected_paragraph is None else expected_paragraph
    if (not isinstance(expected, str) or not isinstance(quote, str) or not quote
            or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(expected) or expected[start:end] != quote):
        raise AnchorError('invalid_anchor', '建议与引用范围不一致，请核对原文')
    old = [b.get('text') for b in source]
    new = [b.get('text') for b in blocks]
    if not all(isinstance(t, str) for t in old + new):
        raise AnchorError('invalid_document', '正文段落结构无效，无法重新定位')
    old[source_index] = expected
    candidates = [i for i, t in enumerate(new) if t == expected]
    if not candidates:
        # Even if quote still occurs, changes elsewhere in the same paragraph
        # may alter its meaning. Never silently narrow the integrity check.
        raise AnchorError('target_changed', '目标条款已变化或删除，请按最新原文复核')
    if old.count(expected) == 1 and len(candidates) == 1:
        index, method = candidates[0], 'unique_paragraph'
    else:
        index = _ordered_target(old, new, source_index, candidates)
        method = 'ordered_context'
    return {'index': index, 'block': blocks[index], 'start': start, 'end': end,
            'method': method, 'source_index': source_index}


def _ordered_target(old, new, target, candidates):
    n, m = len(old), len(new)
    if (n + 1) * (m + 1) > MAX_ALIGNMENT_CELLS:
        raise AnchorError('anchor_scope_too_large', '重复段落的定位范围过大，请缩小范围或重新审查')
    # Typed rows bound memory as well as work. Prefix/suffix scores let us
    # inspect every optimal alignment without enumerating exponential paths.
    prefix = [array('I', [0]) * (m + 1) for _ in range(n + 1)]
    suffix = [array('I', [0]) * (m + 1) for _ in range(n + 1)]
    for i in range(n):
        prev, row = prefix[i], prefix[i + 1]
        for j in range(m):
            row[j + 1] = prev[j] + 1 if old[i] == new[j] else max(prev[j + 1], row[j])
    for i in range(n - 1, -1, -1):
        nxt, row = suffix[i + 1], suffix[i]
        for j in range(m - 1, -1, -1):
            row[j] = nxt[j + 1] + 1 if old[i] == new[j] else max(nxt[j], row[j + 1])
    optimum = prefix[n][m]
    possible = [j for j in candidates if prefix[target][j] + 1 + suffix[target + 1][j + 1] == optimum]
    can_skip = any(prefix[target][j] + suffix[target + 1][j] == optimum for j in range(m + 1))
    if can_skip or len(possible) != 1:
        raise AnchorError('ambiguous_anchor', '原文有重复且上下文无法唯一定位，请人工核对')
    return possible[0]
