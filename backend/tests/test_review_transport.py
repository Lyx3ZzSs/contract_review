import time
import pytest
from app import review_transport as cr
from app.llm import Settings, ExtractionError
from app.revision_proposals import SingleClauseDraft


def invoke_with_retry(call, trace):
    return cr.call_with_retry(call, Settings('test', 'test'), 'm', 'p', SingleClauseDraft,
                              {}, lambda value: value, time.monotonic() + 10, trace)


def test_transport_retry_retries_only_drafting_and_retains_failed_attempt(monkeypatch):
    monkeypatch.setattr(cr.time, 'sleep', lambda _: None)
    calls = []
    def transient(*args):
        calls.append(args[3].__name__)
        if len(calls) == 1:
            raise ExtractionError('gateway_timeout', '生成超时')
        value = SingleClauseDraft(after_text='改文', rationale='依据', missing_context='')
        return value, args[5](value)
    trace = []
    assert invoke_with_retry(transient, trace)[0].after_text == '改文'
    assert calls == ['SingleClauseDraft', 'SingleClauseDraft']
    assert trace[0]['code'] == 'gateway_timeout' and trace[0]['transport_attempt'] == 1


def test_exhausted_transport_retry_preserves_diagnostics(monkeypatch):
    monkeypatch.setattr(cr.time,'sleep',lambda _:None)
    def timeout(*args):raise ExtractionError('gateway_timeout','请求超时')
    with pytest.raises(ExtractionError) as info:invoke_with_retry(timeout, [])
    assert [t['transport_attempt'] for t in info.value.attempts]==[1,2]


def test_invalid_evidence_is_not_retried_as_transport_failure(monkeypatch):
    calls=[]
    def invalid(*args):
        calls.append(1)
        raise ExtractionError('invalid_quote', '原文无法定位')
    with pytest.raises(ExtractionError):invoke_with_retry(invalid, [])
    assert len(calls)==1


def test_stream_transport_retry_uses_new_revision(monkeypatch):
    import time
    monkeypatch.setattr(cr.time,'sleep',lambda _:None)
    revisions=[];attempts=[]
    def stream(kind,**data):revisions.append(data['revision'])
    def invoke(settings,*args):
        attempts.append(1);settings.stream_callback('started',revision=1)
        if len(attempts)==1:raise ExtractionError('gateway_stream_error','流中断')
        return 'ok',None
    result=cr.call_with_retry(invoke,Settings('test','test',stream_callback=stream),'m','p',SingleClauseDraft,{},lambda v:v,time.monotonic()+10,[])
    assert result[0]=='ok' and revisions==[1,3]
