import json
import time
import httpx
import pytest
from pydantic import BaseModel
from app.review_stream import display_fields, DisplayStream
from app.structured_review import extract_call
from app.llm import Settings, ExtractionError


@pytest.mark.parametrize('ascii',[True,False])
def test_every_prefix_escapes_and_surrogates(ascii):
    value={'explanation':'中文 "引用"\n换行\\路径 😀','related_refs':['不应显示'],
           'edits':[{'before_text':'保密原文','after_text':'新条款 😀','rationale':'仅供协商'}]}
    text=json.dumps(value,ensure_ascii=ascii)
    expected={'explanation':value['explanation'],'edit:0:after_text':'新条款 😀','edit:0:rationale':'仅供协商'}
    previous={}
    for end in range(len(text)+1):
        fields=display_fields(text[:end])
        for key,v in fields.items():
            assert expected[key].startswith(v)
            assert v.startswith(previous.get(key,''))
            assert not any(0xD800<=ord(c)<=0xDFFF for c in v)
        previous=fields
    assert previous==expected


def test_batched_deltas_reconstruct_content():
    events=[];stream=DisplayStream(lambda kind,**data:events.extend(data['changes']))
    text=json.dumps({'explanation':'中文😀风险','edits':[{'after_text':'修改建议','rationale':'说明'}]},ensure_ascii=False)
    for char in text:stream.feed(char,force=True)
    fields={}
    for event in events:
        old=fields.get(event['field'],'');assert len(old)==event['offset']
        fields[event['field']]=old+event['text']
    assert fields==display_fields(text)


def test_empty_replacement_only_announces_deletion_after_string_closes():
    prefix='{"edits":[{"after_text":"'
    assert 'edit:0:after_text' not in display_fields(prefix)
    events=[];stream=DisplayStream(lambda kind,**data:events.extend(data['changes']))
    stream.feed(prefix,force=True)
    stream.feed('"',force=True)
    assert events==[{'field':'edit:0:after_text','offset':0,'text':''}]


class Assessment(BaseModel):
    explanation:str


def test_real_sse_protocol_excludes_reasoning_and_validates(monkeypatch):
    real_client=httpx.Client;callbacks=[];requests=[]
    def handle(request):
        requests.append(json.loads(request.content))
        chunks=[{'choices':[{'delta':{'reasoning_content':'must never be displayed'}}]},
                {'choices':[{'delta':{'content':'{"explanation":"中'}}]},
                {'choices':[{'delta':{'content':'文"}'},'finish_reason':'stop'}]}]
        return httpx.Response(200,text=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n')
    monkeypatch.setattr(httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    s=Settings('https://test','secret',stream_callback=lambda kind,**data:callbacks.append((kind,data)))
    value,result=extract_call(s,'deepseek-flash','JSON',Assessment,{},lambda x:x.explanation,time.monotonic()+10,[])
    assert result=='中文' and requests[0]['stream'] is True
    assert callbacks[0]==('started',{'revision':1}) and callbacks[-1][0]=='validating'
    assert 'must never' not in repr(callbacks) and 'secret' not in repr(callbacks)


def test_truncated_stream_retries_with_new_revision_not_success(monkeypatch):
    real_client=httpx.Client;events=[]
    def handle(request):
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':'{"explanation":"未完成'}}]})+'\n\n')
    monkeypatch.setattr(httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    with pytest.raises(ExtractionError,match='重试'):
        extract_call(Settings('https://test','secret',stream_callback=lambda kind,**d:events.append((kind,d))),
                     'deepseek-flash','JSON',Assessment,{},lambda x:x,time.monotonic()+10,[])
    assert [d['revision'] for kind,d in events if kind=='started']==[1,2]
    assert not any(kind=='validating' for kind,d in events)


def test_token_limit_has_specific_diagnostics_even_without_visible_content(monkeypatch):
    real_client=httpx.Client;trace=[]
    def handle(request):
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'length'}],
            'usage':{'completion_tokens':2600}})+'\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    with pytest.raises(ExtractionError):
        extract_call(Settings('https://test','secret',stream_callback=lambda *args,**kw:None),
                     'deepseek-flash','JSON',Assessment,{},lambda x:x,time.monotonic()+10,trace)
    assert len(trace)==2
    assert all(t['finish_reason']=='length' and t['usage']['completion_tokens']==2600 and
               t['diagnostics']==[{'type':'incomplete_output','finish_reason':'length','done':True}] for t in trace)

def test_card_stream_exposes_public_paragraphs_and_plan_without_unverified_refs():
    from app.review_stream import display_fields
    fields=display_fields('{"risk_paragraphs":[{"text":"风险说明","refs":["b99"]}],"modification_plan":"修改方')
    assert fields=={'risk:0:text':'风险说明','modification_plan':'修改方'}


def test_process_feedback_stream_exposes_only_public_text():
    from app.review_stream import display_fields
    fields = display_fields('{"checks":[{"title":"合法性","text":"法规引用待核实","refs":["b1"],"status":"checked"}]}')
    assert fields == {'check:0:title':'合法性', 'check:0:text':'法规引用待核实'}


@pytest.mark.parametrize('mode', ['slow_valid','heartbeat','gap','total','invalid','truncated'])
def test_background_stream_requires_timely_content_and_valid_complete_output(monkeypatch,mode):
    from types import SimpleNamespace
    from app import structured_review
    real_client = httpx.Client
    clock = [0.]
    def data(content,finish=None):
        return ('data: '+json.dumps({'choices':[{'delta':{'content':content},'finish_reason':finish}]})+'\n\n').encode()
    def chunks():
        clock[0]+=1
        if mode=='heartbeat':
            clock[0]+=90
            yield b': heartbeat\n\n'
            return
        yield data('{"explanation":')
        clock[0]+=91 if mode=='gap' else 50
        yield data('"ok"')
        clock[0]+=50
        yield data('}' if mode!='invalid' else '??','stop')
        if mode!='truncated':
            yield b'data: [DONE]\n\n'
    def handle(request):
        return httpx.Response(200,headers={'x-request-id':'test-request'},content=chunks())
    monkeypatch.setattr(structured_review,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr(httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    events=[];trace=[]
    settings=Settings('http://test','secret',timeout=90,progress_only_stream=True,
                      stream_callback=lambda kind,**d:events.append(kind))
    def invoke():
        return extract_call(settings,'model','JSON',Assessment,{},lambda v:v.explanation,80 if mode=='total' else 400,trace)
    if mode=='slow_valid':
        assert invoke()[1]=='ok'
        assert trace[0]['elapsed_seconds']==101 and trace[0]['first_content_seconds']==1
        assert events==['started','receiving','validating']
    else:
        with pytest.raises(ExtractionError):invoke()
        assert not any(a['status']=='validated' for a in trace)
    assert trace[0]['gateway_request_id']=='test-request'


def test_fact_stream_preserves_display_order_and_hides_unverified_references():
    from app.review_stream import display_fields

    prefix = '{"amount":{"refs":["b14"],"value":"暂估价"},"payment":{"value":"验收后付'
    assert display_fields(prefix) == {
        'section:2:title':'金额及其性质', 'section:2:text':'暂估价',
        'section:3:title':'付款条件', 'section:3:text':'验收后付'}


@pytest.mark.parametrize('repair_succeeds',[True,False])
def test_overview_keeps_verified_sections_when_one_reference_needs_repair(repair_succeeds):
    import json
    from app.llm import Settings
    from app.review_stream import DisplayStream
    from app.transaction_display import stream_overview

    topics = ['交易概况','履约安排','验收与质量','款项与结算']
    events, requests = [], []
    def call(settings, model, prompt, schema, payload, validate, deadline, trace):
        requested = payload['requested_sections']
        requests.append(requested)
        rows = [dict(title=topic,text='合同原文',refs=['b1' if topic!=topics[-1] or len(requests)>1 and repair_succeeds else 'unknown']) for topic in requested]
        stream = DisplayStream(settings.stream_callback, settings.section_callback)
        body = json.dumps({'sections':rows},ensure_ascii=False)
        if len(requests)==1:
            partial = body.index('合同原文') + 2
            stream.feed(body[:partial],force=True)
            assert events[-1][0]=='analysis_delta'
            assert events[-1][1]['changes'][-1]=={'field':'section:0:text','offset':0,'text':'合同'}
        else:
            partial = 0
        split = body.index('}')+1
        stream.feed(body[partial:split],force=True)
        if len(requests)==1:
            assert [d['section']['title'] for k,d in events if k=='analysis_section']==topics[:1]
        stream.feed(body[split:],force=True)
        value = schema(sections=rows)
        return value, validate(value)
    stream_overview(Settings('local','test'),'m',[dict(id='orig',text='合同原文')],'乙方',call,
                    lambda kind,**data:events.append((kind,data)))
    assert requests==[topics,topics[-1:]]
    published=[d['section'] for k,d in events if k=='analysis_section']
    assert [s['title'] for s in published]==(topics if repair_succeeds else topics[:-1])
    assert all(s['evidence'][0]['block_id']=='orig' for s in published)
    assert [k for k,d in events].count('analysis_started')==1
    assert next(data for kind,data in events if kind=='analysis_validating')['clear_preview']
    assert events[-1][0]==('analysis_completed' if repair_succeeds else 'analysis_failed')
    if not repair_succeeds:
        assert '引用的段落编号' in events[-1][1]['message']
