"""Bounded transport retry for checkpointed model calls."""
import time
from dataclasses import replace

from .llm import ExtractionError

TRANSPORT_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 1


def transport_retry_window(request_timeout):
    return TRANSPORT_ATTEMPTS * request_timeout + (TRANSPORT_ATTEMPTS - 1) * RETRY_DELAY_SECONDS


def call_with_retry(call, settings, model, prompt, schema, payload, validate, deadline, trace):
    """Retry one read-only model call once without repeating successful stages."""
    for attempt in range(TRANSPORT_ATTEMPTS):
        start = len(trace)
        try:
            current = settings
            if settings.stream_callback:
                # The extractor has two schema attempts per transport attempt.
                # A retry must start a new display revision, never append offsets
                # to a truncated stream from the previous transport.
                def callback(kind, **data):
                    if 'revision' in data:data['revision'] += attempt * 2
                    settings.stream_callback(kind, **data)
                current = replace(settings, stream_callback=callback)
            return call(current, model, prompt, schema, payload, validate, deadline, trace)
        except ExtractionError as exc:
            deadline += getattr(exc, 'queue_wait_seconds', 0)
            retryable = exc.code in ('gateway_timeout', 'gateway_unreachable', 'gateway_stream_error') or (
                exc.code == 'gateway_http_error' and getattr(exc, 'status_code', None) in (429, 500, 502, 503, 504))
            if len(trace) == start:
                trace.extend(getattr(exc, 'attempts', []) or [{'stage':schema.__name__, 'status':'failed', 'code':exc.code}])
            exc.attempts = trace
            if (settings.section_callback or attempt + 1 == TRANSPORT_ATTEMPTS or not retryable
                    or time.monotonic() + RETRY_DELAY_SECONDS >= deadline):
                raise
            time.sleep(RETRY_DELAY_SECONDS)
        finally:
            for entry in trace[start:]:entry['transport_attempt'] = attempt + 1
