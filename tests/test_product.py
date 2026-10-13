import json
import threading
from http.server import ThreadingHTTPServer
import requests
import pytest
from rag_app.web import Workspace, handler_for
from rag_app.config import Config, load_config
from rag_app.export import save_run, mark_review, export_submission

@pytest.fixture
def web(tmp_path):
    ws=Workspace(Config(), tmp_path)
    server=ThreadingHTTPServer(('127.0.0.1',0), handler_for(ws))
    worker=threading.Thread(target=server.serve_forever, daemon=True);worker.start()
    yield ws, f'http://127.0.0.1:{server.server_port}'
    server.shutdown();server.server_close();worker.join()

def test_ui_and_local_request_boundary(web):
    ws,url=web
    assert requests.get(url).status_code==200
    assert '论文问答' in requests.get(url).text
    assert requests.get(url+'/api/state').json()['token']==ws.token
    assert requests.post(url+'/api/index',json={}).status_code==403
    assert requests.get(url+'/api/state',headers={'Host':'evil.example'}).status_code==403
    assert requests.get(url+'/download?run=../../outside&file=run.json').status_code==400
    assert requests.get(url+'/download?run=valid&file=../../secret').status_code==400
    assert requests.post(url+'/api/answer',json={'questions':['']},headers={'X-Workspace-Token':ws.token}).status_code==400

def test_busy_does_not_overwrite_work(web):
    ws,url=web
    ws.lock.acquire()
    try:
        r=requests.post(url+'/api/answer',json={'questions':['问题']},headers={'X-Workspace-Token':ws.token})
        assert r.status_code==400 and '进行' in r.json()['error']
    finally: ws.lock.release()

def test_missing_explicit_configuration(tmp_path):
    with pytest.raises(FileNotFoundError):load_config(tmp_path/'missing.json')

def valid_result(i):
    return {'id':f'q{i}','question':'问题','answer':'事实','status':'answered',
        'claims':[{'text':'事实','evidence':[{'chunk_id':'C1','quote':'原文'}]}],
        'missing_information':[], 'retrieved_chunks':[{'chunk_id':'C1','text':'原文',
        'pdf_pages':[1],'printed_pages':[151],'char_start':0,'char_end':2,'token_count':2,'rank':1,'score':0.8}],
        'citation_check':'passed','content_review':'pending','error':None}

def test_review_and_export_revalidate_evidence(tmp_path):
    path=tmp_path/'run.json';save_run({'results':[valid_result(i) for i in range(1,4)]},path)
    with pytest.raises(ValueError):export_submission(path)
    for i in range(1,4):mark_review(path,f'q{i}','passed','已检查')
    result=export_submission(path)
    assert len(json.loads(result.read_text(encoding='utf-8')))==3
    run=json.loads(path.read_text(encoding='utf-8'));run['results'][0]['claims'][0]['evidence'][0]['quote']='伪造';save_run(run,path)
    with pytest.raises(ValueError,match='重新校验'):export_submission(path)
    with pytest.raises(ValueError):mark_review(path,'q1','anything','')

def test_retry_preserves_success_and_review(tmp_path,monkeypatch):
    import rag_app.web as module
    ws=Workspace(Config(),tmp_path)
    run={'run_id':'test-run','questions':['一','二'],'compare':False,'results':[valid_result(1)]}
    run['results'][0]['content_review']='passed'
    save_run(run,ws.path('test-run'))
    class Service:
        def answer(self,q,*args):
            assert q=='二'
            return valid_result(2)
    ws.service=Service();ws.lock.acquire();ws.work('retry',{'run_id':'test-run'})
    final=ws.read('test-run')
    assert len(final['results'])==2
    assert final['results'][0]['content_review']=='passed'
    assert ws.job['state']=='done'

def test_citation_repair_cannot_turn_failure_into_refusal(monkeypatch):
    import rag_app.service as module
    from rag_app.schemas import ModelAnswer, Hit
    hit=Hit.model_validate(valid_result(1)['retrieved_chunks'][0])
    wrong=ModelAnswer.model_validate({'status':'answered','claims':[{'text':'事实','evidence':[{'chunk_id':'C1','quote':'伪造'}]}],'missing_information':[]})
    refusal=ModelAnswer(status='insufficient',claims=[],missing_information=['无法修复引用'])
    responses=iter([(wrong,{}),(refusal,{})])
    monkeypatch.setattr(module,'retrieve',lambda *a:[hit])
    monkeypatch.setattr(module,'generate',lambda *a:next(responses))
    service=module.RagService.__new__(module.RagService)
    service.config=Config();service.index=None;service.embedder=None
    result=service.answer('问题')
    assert result['citation_check']=='failed'
    assert result['status']=='answered'
    assert result['error'] is not None

def test_doctor_reports_unavailable_service(monkeypatch,capsys):
    import rag_app.__main__ as cli
    monkeypatch.setattr(cli,'validate_index',lambda c:{'chunk_count':1,'embedding_dimension':1})
    def fail(c):raise RuntimeError('offline')
    monkeypatch.setattr(cli,'list_models',fail)
    assert cli.doctor(Config())==1

def test_chat_answers_before_next_prompt(monkeypatch,tmp_path):
    import rag_app.__main__ as cli
    import sys
    events=[]
    questions=iter(['问题',':quit'])
    def prompt(text):
        events.append('input')
        return next(questions)
    class Service:
        def __init__(self,c):pass
        def answer(self,*a):events.append('answer');return valid_result(1)
    monkeypatch.setattr('builtins.input',prompt)
    monkeypatch.setattr(sys,'argv',['rag_app','chat'])
    monkeypatch.setattr(cli,'RagService',Service)
    monkeypatch.setattr(cli,'output_dir',lambda _:tmp_path/'run')
    monkeypatch.setattr(cli,'new_run',lambda *a:{'results':[]})
    assert cli.main()==0
    assert events==['input','answer','input']
    assert (tmp_path/'run'/'run.json').exists()

def test_baseline_failure_keeps_valid_rag_answer(monkeypatch):
    import rag_app.service as module
    from rag_app.schemas import ModelAnswer, Hit
    hit=Hit.model_validate(valid_result(1)['retrieved_chunks'][0])
    good=ModelAnswer.model_validate(valid_result(1))
    calls=[]
    def generate(*a):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('对比超时')
        return good,{}
    monkeypatch.setattr(module,'retrieve',lambda *a:[hit])
    monkeypatch.setattr(module,'generate',generate)
    service=module.RagService.__new__(module.RagService)
    service.config=Config();service.index=None;service.embedder=None
    result=service.answer('问题',compare=True)
    assert result['error'] is None and result['citation_check']=='passed'
    assert result['baseline_error']=='对比超时'

def test_failed_run_has_nonzero_exit_code(tmp_path):
    from rag_app.__main__ import run_exit_code
    path=tmp_path/'run.json';r=valid_result(1)
    save_run({'results':[r]},path);assert run_exit_code(path)==0
    r['error']={'message':'失败'};save_run({'results':[r]},path);assert run_exit_code(path)==1

def test_explicit_missing_facts_downgrade_completeness_only():
    from rag_app.schemas import ModelAnswer
    r=valid_result(1);r['missing_information']=['未知属性']
    a=ModelAnswer.model_validate(r)
    assert a.status=='partial'
    assert a.claims[0].text=='事实' and a.missing_information==['未知属性']
    assert r['status']=='answered'
