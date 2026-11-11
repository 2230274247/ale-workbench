"""Round-six browser acceptance: real MySQL rollback + real provider adapter/MockTransport."""
import json
import os
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from app import ai
from app.ai_provider import Provider
from app.config import ROOT
from app.db import table
from test_ai import setup_ai, response, PUBLIC
from test_phase4_browser import db, client, world, database_manifest, originals_manifest

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8026'


@pytest.fixture
def ui(client, actors, db, world, setup_ai, monkeypatch):
    import uvicorn
    from app.main import app
    seen=[]; mode={'value':'ok'}
    # Dependencies and endpoint execute on separate worker invocations; the
    # scientific fixture lock already spans get_db through endpoint delivery.

    @contextmanager
    def transaction():
        with db.begin_nested():
            yield db
    monkeypatch.setattr(ai,'ai_transaction',transaction)
    def handler(req):
        seen.append((req.url.path, json.loads(req.content) if req.content else None))
        if req.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':'fixture-model'},{'id':'discovered-choice'}]})
        if mode['value']=='key': return httpx.Response(401,json={'error':'fixture-secret-only'})
        if mode['value']=='timeout': raise httpx.ReadTimeout('hidden key upstream')
        body=json.loads(req.content)
        if not body.get('tools'): return httpx.Response(200,json=response('通用问候'))
        if body['messages'][-1]['role']=='user':
            return httpx.Response(200,json=response(None,[{'id':'lookup','type':'function','function':{'name':'record_detail','arguments':json.dumps({'kind':'sample','id':world['parent']})}}]))
        return httpx.Response(200,json=response('当前记录已核对。<img src=x onerror=alert(1)> https://evil.example/\n请检查来源。'))
    provider=Provider(httpx.MockTransport(handler),PUBLIC)
    app.dependency_overrides[ai.get_provider]=lambda:provider
    # Serialize HTTP requests over the single rollback connection, including
    # status (which deliberately has no scientific get_db dependency).
    import asyncio
    from starlette.applications import Starlette
    from starlette.middleware.base import BaseHTTPMiddleware
    serial_lock=asyncio.Lock()
    class Serial(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            async with serial_lock:
                return await call_next(request)
    served=Starlette()
    served.mount('/',app)
    served.add_middleware(Serial)
    server=uvicorn.Server(uvicorn.Config(served,host='127.0.0.1',port=8026,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(150):
        if server.started:break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
            ctx=browser.new_context(viewport={'width':1440,'height':1000})
            page=ctx.new_page();page.set_default_timeout(15000)
            errors=[];requests=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:requests.append((r.method,r.url,r.post_data)) if '/ai/' in r.url else None)
            yield dict(page=page,context=ctx,actors=actors,db=db,world=world,seen=seen,mode=mode,requests=requests)
            assert not errors,errors
            print('PROVIDER CALLS',len(seen),'JS ERRORS',errors)
            ctx.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=5);assert not thread.is_alive()


def login(ui,role='operator'):
    p=ui['page'];p.goto(BASE+'/login')
    p.get_by_label('用户名',exact=True).fill(ui['actors'][role]['user']['username'])
    p.get_by_label('密码',exact=True).fill('TestPassword123!')
    p.get_by_role('button',name='登录工作台',exact=True).click()
    p.get_by_role('heading',name='工作台概览',exact=True).wait_for()
    p.wait_for_load_state('networkidle')


def shot(ui,name):
    p=ui['page'];p.screenshot(path=str(ROOT/'reports/screenshots'/f'round6-ai-{name}-{p.viewport_size["width"]}.png'),full_page=True)
    assert p.evaluate('document.documentElement.scrollWidth <= innerWidth+1')


def open_ai(ui):
    p=ui['page'];p.get_by_role('button',name='研究助手',exact=True).click()
    drawer=p.locator('.ai-drawer');expect(drawer).to_be_visible();return drawer


def send(drawer,text):
    drawer.get_by_label('你的问题',exact=True).fill(text)
    drawer.get_by_role('button',name='发送问题',exact=True).click()
    expect(drawer.locator('.ai-answer').last).to_contain_text('当前记录已核对')


@pytest.mark.parametrize('width',[1440,390])
def test_assistant_context_memory_sources_failure_and_viewer(ui,width):
    p=ui['page'];p.set_viewport_size({'width':width,'height':1000 if width==1440 else 844});login(ui)
    scientific={k:v for k,v in database_manifest(ui['db']).items() if not k.startswith('ai_') and k not in ('auth_sessions','audit_logs')}
    p.goto(BASE+f'/samples?sample_id={ui["world"]["parent"]}')
    drawer=open_ai(ui)
    consent=drawer.get_by_label('允许本次会话发送问题和最小记录摘要给已配置模型服务',exact=True)
    drawer.get_by_label('你的问题',exact=True).fill('核对当前记录')
    expect(drawer.get_by_role('button',name='发送问题',exact=True)).to_be_disabled()
    assert not ui['seen']
    consent.check();drawer.get_by_label(f'附带当前样品 #{ui["world"]["parent"]}',exact=True).check()
    send(drawer,'核对当前记录')
    expect(drawer.locator('.ai-answer img')).to_have_count(0)
    expect(drawer.locator('.ai-answer a[href^="http"]')).to_have_count(0)
    expect(drawer.locator('.ai-sources a').first).to_have_attribute('href',f'/samples?sample_id={ui["world"]["parent"]}')
    drawer.locator('summary').first.click();expect(drawer).to_contain_text('当前页面记录');expect(drawer).to_contain_text('模型发起查询');drawer.get_by_text('查看本次用量',exact=True).click();expect(drawer).to_contain_text('缓存命中 60 / 未命中 140');shot(ui,'context-tools')
    drawer.get_by_label(f'附带当前样品 #{ui["world"]["parent"]}',exact=True).uncheck()
    send(drawer,'刚才那个样品有哪些记录？')
    payloads=[json.loads(x[2]) for x in ui['requests'] if x[0]=='POST' and x[1].endswith('/chat')]
    assert payloads[0]['context']=={'kind':'sample','id':ui['world']['parent']}
    assert payloads[1]['context']=={'kind':'none'}
    assert payloads[1]['conversation_id']
    upstream=ui['seen'][-1][1]['messages']
    assert '核对当前记录' in json.dumps(upstream,ensure_ascii=False)
    assert any(m['role']=='user' and 'prior_plan_reexecuted' in m.get('content','') for m in upstream)
    assert not any(m['role']=='assistant' and any(c['id'].startswith('prior_') or c['id']=='current_context' for c in m.get('tool_calls',[])) for m in upstream)
    assert not any(m.get('content') and 'evil.example' in m['content'] for m in upstream)
    assert payloads[0]['request_id']!=payloads[1]['request_id']
    expect(drawer.locator('.ai-question')).to_have_count(2);shot(ui,'multi-turn')
    ui['mode']['value']='key'
    drawer.get_by_label('你的问题',exact=True).fill('保留失败问题');drawer.get_by_role('button',name='发送问题',exact=True).click()
    expect(drawer).to_contain_text('API Key、余额')
    expect(drawer).to_contain_text('保留失败问题')
    shot(ui,'provider-key-error')
    ui['mode']['value']='timeout'
    drawer.get_by_role('button',name='重新提问（新请求）',exact=True).last.click()
    expect(drawer).to_contain_text('保守估算')
    expect(drawer.locator('.ai-question')).to_have_count(4)
    assert not any('/ai/config' in x[1] or '/ai/usage' in x[1] for x in ui['requests'])
    # Network outcome uncertainty must preserve exact request, even if route selection changes.
    ui['mode']['value']='ok'
    p.route('**/api/v1/ai/chat',lambda route:route.abort())
    drawer.get_by_label('你的问题',exact=True).fill('断连保留原请求');drawer.get_by_role('button',name='发送问题',exact=True).click()
    expect(drawer.get_by_role('button',name='使用原请求 ID 查询结果')).to_be_visible()
    last=json.loads([x[2] for x in ui['requests'] if x[0]=='POST' and x[1].endswith('/chat')][-1])
    p.unroute('**/api/v1/ai/chat')
    drawer.get_by_role('button',name='使用原请求 ID 查询结果').click()
    expect(drawer.locator('.ai-answer').last).to_contain_text('当前记录已核对')
    assert json.loads([x[2] for x in ui['requests'] if x[0]=='POST' and x[1].endswith('/chat')][-1])==last
    drawer.get_by_role('button',name='关闭研究助手').click()
    p.goto(BASE+'/measurements?sample_id='+str(ui['world']['parent']))
    drawer=open_ai(ui);expect(drawer.get_by_label('当前页面没有选定记录')).to_be_disabled()
    drawer.get_by_role('button',name='关闭研究助手').click()
    current={k:v for k,v in database_manifest(ui['db']).items() if k in scientific}
    assert scientific==current,'Scientific CRUD state changed by assistant'
    # Logout resets UI and viewers never call hidden admin endpoints.
    if width==390:
        p.get_by_role('button',name='打开导航',exact=True).click()
        p.get_by_role('link',name='工作台概览',exact=True).click()
    p.locator('.user-menu').click();p.get_by_text('退出登录',exact=True).click();p.get_by_role('button',name='登录工作台',exact=True).wait_for()
    login(ui,'viewer');drawer=open_ai(ui);expect(drawer.locator('.ai-question')).to_have_count(0);expect(drawer.get_by_label('允许本次会话发送问题和最小记录摘要给已配置模型服务',exact=True)).not_to_be_checked()
    drawer.get_by_role('button',name='关闭研究助手').click();p.goto(BASE+'/ai-settings');p.wait_for_url(BASE+'/')
    assert not any('/ai/config' in x[1] or '/ai/usage' in x[1] for x in ui['requests'])
    print('SCIENTIFIC FINGERPRINTS IDENTICAL',len(scientific))


@pytest.mark.parametrize('width',[1440,390])
def test_admin_staged_config_dirty_usage_test_and_budget(ui,width):
    p=ui['page'];p.set_viewport_size({'width':width,'height':1000 if width==1440 else 844});login(ui,'admin');p.goto(BASE+'/ai-settings')
    p.get_by_role('heading',name='AI 设置',exact=True).wait_for()
    key=p.get_by_label('新 API Key（只写）',exact=False);expect(key).to_have_value('')
    key.fill('new-fixture-secret');p.get_by_role('button',name='停用并清空模型以修改连接').click()
    p.get_by_role('button',name='保存设置',exact=True).click();expect(key).to_have_value('')
    expect(p.get_by_label('启用研究助手',exact=True)).to_be_disabled()
    p.get_by_role('button',name='发现模型',exact=True).click();expect(p.get_by_text('发现 2 个模型。请选择后保存启用。')).to_be_visible()
    p.get_by_label('已发现的模型',exact=True).select_option('discovered-choice');p.get_by_label('启用研究助手',exact=True).check()
    p.get_by_label('输入价格（每百万 Token）',exact=True).fill('2.50000001')
    p.get_by_role('button',name='保存设置',exact=True).click();expect(p.get_by_text('设置已保存。',exact=True)).to_be_visible()
    p.get_by_label('允许发送通用问候给已配置模型服务（不含实验数据，计入预算）',exact=True).check();p.get_by_role('button',name='发送通用测试',exact=True).click()
    expect(p.get_by_text('连接测试完成',exact=False)).to_be_visible()
    expect(p.locator('.ai-test-result')).to_contain_text('通用问候')
    expect(p.locator('.ai-test-result')).to_contain_text('输入 100 / 输出 10')
    expect(p.locator('.ai-test-result')).to_contain_text('缓存命中 30 / 未命中 70')
    expect(p.locator('.ai-test-result')).to_contain_text('服务商调用 1 次')
    expect(p.locator('.ai-test-result')).to_contain_text('请求 ID：')
    expect(p.locator('.ai-setup')).to_contain_text('本页已收到通用测试回复')
    assert 'fixture-secret-only' not in p.locator('body').inner_text()
    assert 'new-fixture-secret' not in p.locator('body').inner_text()
    shot(ui,'admin-settings')
    saved=len([x for x in ui['requests'] if x[0]=='PUT' and x[1].endswith('/config')])
    p.get_by_label('输入价格（每百万 Token）',exact=True).fill('0')
    p.get_by_role('button',name='保存设置',exact=True).click()
    expect(p.get_by_role('alert')).to_contain_text('输入及输出价格须大于 0')
    assert len([x for x in ui['requests'] if x[0]=='PUT' and x[1].endswith('/config')])==saved
    p.get_by_label('输入价格（每百万 Token）',exact=True).fill('2.50000001')
    expect(p.get_by_text('扣除已记账及预留后剩余',exact=False)).to_be_visible()
    expect(p.get_by_text('按当前表单预估：',exact=False)).to_be_visible()
    assert ui['seen'][-1][1]['messages'][-1]['content']=='Say hello briefly. Do not access scientific data.'
    p.get_by_label('服务商名称',exact=True).fill('未保存')
    if width==390:p.get_by_role('button',name='打开导航',exact=True).click()
    p.get_by_role('link',name='工作台概览',exact=True).click();p.get_by_role('button',name='继续编辑',exact=True).click();expect(p.get_by_role('heading',name='AI 设置',exact=True)).to_be_visible()
    if width==390:p.get_by_role('button',name='打开导航',exact=True).click()
    p.get_by_role('link',name='工作台概览',exact=True).click();p.get_by_role('button',name='放弃修改',exact=True).click();p.wait_for_url(BASE+'/')
    # Force a budget boundary without provider calls; UI explains the reservation block.
    with ui['db'].info['browser_lock']:
        t=table('ai_config');row=ui['db'].execute(select(t)).mappings().one();cfg=dict(row['settings']);cfg['monthly_budget']='0.00000001';ui['db'].execute(t.update().values(settings=cfg))
    drawer=open_ai(ui);drawer.get_by_label('允许本次会话发送问题和最小记录摘要给已配置模型服务',exact=True).check();drawer.get_by_label('你的问题',exact=True).fill('预算边界');drawer.get_by_role('button',name='发送问题',exact=True).click();expect(drawer).to_contain_text('预算或 Token 上限');shot(ui,'budget-limit')


def test_pending_id_context_whitelist_and_stale_logout(ui):
    p=ui['page'];login(ui)
    for path,label in [(f'/batches?batch_id={ui["world"]["batch_id"]}',f'附带当前批次 #{ui["world"]["batch_id"]}'),(f'/plans?plan_id={ui["world"]["plan"]}',f'附带当前计划 #{ui["world"]["plan"]}'),('/processes?process_id=123','附带当前执行 #123'),('/measurements?id=123','附带当前测量 #123'),('/measurements?measurement_id=123','附带当前测量 #123')]:
        p.goto(BASE+path);d=open_ai(ui);expect(d.get_by_label(label,exact=True)).to_be_enabled();expect(d.get_by_label(label,exact=True)).not_to_be_checked();d.get_by_role('button',name='关闭研究助手').click()
    p.goto(BASE+'/');d=open_ai(ui);d.get_by_label('允许本次会话发送问题和最小记录摘要给已配置模型服务',exact=True).check()
    pending=[]
    def pend(route):
        body=route.request.post_data_json;pending.append(body)
        route.fulfill(json={'code':0,'data':{'status':'pending','request_id':body['request_id'],'answer':None,'sources':[],'tool_trace':[],'error':{'code':'request_in_progress'}}})
    p.route('**/api/v1/ai/chat',pend)
    d.get_by_label('你的问题',exact=True).fill('待处理');d.get_by_role('button',name='发送问题',exact=True).click();expect(d.get_by_role('button',name='使用原请求 ID 查询结果')).to_be_visible()
    d.get_by_role('button',name='使用原请求 ID 查询结果').click();expect(d.get_by_role('button',name='使用原请求 ID 查询结果')).to_be_enabled()
    assert len(pending)==2 and pending[0]==pending[1]
    expect(d.get_by_role('button',name='新会话',exact=True)).to_be_disabled()
    p.unroute('**/api/v1/ai/chat');d.get_by_role('button',name='使用原请求 ID 查询结果').click();expect(d.locator('.ai-answer').last).to_contain_text('当前记录已核对')
    # Lose delivery AFTER server settlement, then recover the same answer for free.
    def lost_completed(route):
        result=route.fetch().json()
        assert result['data']['status']=='completed'
        route.abort()
    p.route('**/api/v1/ai/chat',lost_completed)
    d.get_by_label('你的问题',exact=True).fill('已完成但响应丢失')
    d.get_by_role('button',name='发送问题',exact=True).click()
    expect(d.get_by_role('button',name='使用原请求 ID 查询结果')).to_be_visible()
    settled_calls=len(ui['seen'])
    p.unroute('**/api/v1/ai/chat')
    d.get_by_role('button',name='使用原请求 ID 查询结果').click()
    expect(d.locator('.ai-answer').last).to_contain_text('当前记录已核对')
    assert len(ui['seen'])==settled_calls
    expect(d.locator('.ai-answer').last.get_by_role('button',name='重新提问（新请求）')).to_have_count(0)
    # A completed HTTP response is deliberately delivered after logout/login.
    held=[]
    def hold(route):
        result=route.fetch().json()
        result['data']['sources'] += [{'kind':'sample','id':1,'href':'https://evil.example/'},{'kind':'sample','id':1,'href':'//evil.example/'},{'kind':'sample','id':1,'href':'/samples?sample_id=1&external=1'}]
        held.append((route,result))
    p.route('**/api/v1/ai/chat',hold)
    d.get_by_label('你的问题',exact=True).fill('过期身份响应');d.get_by_role('button',name='发送问题',exact=True).click()
    
    for _ in range(100):
        if held:break
        p.wait_for_timeout(100)
    assert held
    d.get_by_role('button',name='关闭研究助手').click();p.locator('.user-menu').click();p.get_by_text('退出登录',exact=True).click();p.get_by_role('button',name='登录工作台',exact=True).wait_for();login(ui,'viewer')
    for route,result in held:route.fulfill(json=result)
    p.unroute('**/api/v1/ai/chat');d=open_ai(ui)
    expect(d.locator('.ai-question')).to_have_count(0);expect(d.get_by_label('允许本次会话发送问题和最小记录摘要给已配置模型服务',exact=True)).not_to_be_checked()
    # Exercise source validation independently of model answer text.
    d.get_by_label('允许本次会话发送问题和最小记录摘要给已配置模型服务',exact=True).check()
    def injected(route):
        result=route.fetch().json();result['data']['status']='completed';result['data']['answer']='当前记录已核对（来源校验测试）';result['data']['error']=None;result['data']['sources'] += [{'kind':'sample','id':1,'href':'https://evil.example/'},{'kind':'sample','id':1,'href':'/samples?sample_id=1&external=1'}];route.fulfill(json=result)
    p.route('**/api/v1/ai/chat',injected)
    send(d,'只看授权记录');expect(d.locator('.ai-sources a[href^="http"]')).to_have_count(0);expect(d.locator('.ai-sources a[href*="external"]')).to_have_count(0)
    shot(ui,'viewer-stale-guard')


@pytest.mark.parametrize('width',[1440,390])
def test_deepseek_endpoint_selects_and_locks_nonthinking(ui,width):
    p=ui['page'];p.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
    login(ui,'admin');p.goto(BASE+'/ai-settings')
    p.get_by_role('heading',name='AI 设置',exact=True).wait_for()
    toggle=p.get_by_label('显式关闭 thinking（服务商支持时）',exact=True)
    expect(toggle).to_be_enabled();expect(toggle).not_to_be_checked()
    p.get_by_label('HTTPS 接口地址',exact=True).fill('https://api.deepseek.com/v1')
    expect(toggle).to_be_checked();expect(toggle).to_be_disabled()
    expect(p.get_by_text('当前地址为 DeepSeek 官方 api.deepseek.com：',exact=False)).to_be_visible()
    p.get_by_role('button',name='保存设置',exact=True).click()
    expect(p.get_by_text('设置已保存。',exact=True)).to_be_visible()
    p.reload();expect(toggle).to_be_checked();expect(toggle).to_be_disabled()
    shot(ui,'protocol-deepseek-settings')
    p.get_by_label('HTTPS 接口地址',exact=True).fill('https://other.example/v1')
    expect(toggle).to_be_enabled();toggle.uncheck()
    p.get_by_role('button',name='保存设置',exact=True).click()
    expect(p.get_by_text('设置已保存。',exact=True)).to_be_visible()
    assert not ui['seen'], 'Changing settings must not call a provider'


@pytest.mark.parametrize('width',[1440,390])
def test_recovery_accounting_unknown_delivery_and_own_pending_lookup(ui,width):
    from test_ai import expire
    p=ui['page'];p.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
    login(ui,'admin')
    # Seed an interrupted request using the service reservation and dispatch ledger;
    # no provider network request is made by this seed.
    import uuid
    body=ai.TestBody(request_id=uuid.uuid4())
    with ui['db'].info['browser_lock']:
        held,_=ai.reserve(ui['actors']['admin']['user'],body,'test')
        ai.before_outbound(ui['actors']['admin']['user'],held,[],str(body.request_id))
        expire(ui['db'],body)
    p.goto(BASE+'/ai-settings');expect(p.locator('.ai-request').filter(has_text=str(body.request_id))).to_contain_text('中断已恢复')
    card=p.locator('.ai-request').filter(has_text=str(body.request_id));expect(card).to_contain_text('费用未知')
    p.get_by_role('button',name='恢复过期请求',exact=True).click();expect(p.get_by_text('已恢复 0 个过期请求',exact=False)).to_be_visible()
    card.get_by_role('button',name='凭服务商账单核对',exact=True).click()
    form=p.locator('.ai-reconcile')
    form.get_by_label('核对原因（至少10字）',exact=True).fill('服务商正式账单已核实这一笔中断请求')
    form.get_by_label('服务商账单证据（至少10字）',exact=True).fill('离线验收凭证编号 fixture-20261017，输入100输出10')
    form.get_by_label('实际输入 Token',exact=True).fill('100');form.get_by_label('实际输出 Token',exact=True).fill('10');form.get_by_label('实际缓存命中 Token',exact=True).fill('30');form.get_by_label('实际费用（原请求币种）',exact=True).fill('0.00011')
    expect(form.get_by_role('button',name='确认调整账务',exact=True)).to_be_disabled()
    form.get_by_label('确认凭证与原请求一致，调整本地账务并保留审计记录；不会再次调用模型',exact=True).check()
    submitted=[]
    def lost(route):
        submitted.append(route.request.post_data_json)
        response=route.fetch();assert response.status==200
        route.abort()
    p.route('**/api/v1/ai/requests/*/reconcile',lost)
    form.get_by_role('button',name='确认调整账务',exact=True).click()
    expect(form.get_by_text('上次核对结果未知，原 UUID 和凭证已锁定。',exact=True)).to_be_visible()
    expect(form.get_by_label('实际费用（原请求币种）',exact=True)).to_be_disabled()
    shot(ui,'closeout-reconcile-unknown')
    p.unroute('**/api/v1/ai/requests/*/reconcile')
    form.get_by_role('button',name='使用原 UUID 重试核对',exact=True).click()
    expect(card).to_contain_text('已核对账务');expect(card.get_by_role('button',name='凭服务商账单核对')).to_have_count(0)
    all_posts=[json.loads(x[2]) for x in ui['requests'] if x[0]=='POST' and x[1].endswith('/reconcile')]
    assert len(all_posts)==2 and all_posts[0]==all_posts[1]==submitted[0]
    assert not ui['seen'],'Recovery and reconciliation must not call provider'
    with ui['db'].info['browser_lock']:
        row=ui['db'].execute(select(table('ai_requests')).where(table('ai_requests').c.request_id==str(body.request_id))).mappings().one()
        assert len(row['result']['_server']['reconciliations'])==1
    shot(ui,'closeout-reconciled')
    # Own pending request: original ID GET triggers recovery and releases the UI.
    p.locator('.user-menu').click();p.get_by_text('退出登录',exact=True).click();p.get_by_role('button',name='登录工作台',exact=True).wait_for();login(ui,'operator');ui['requests'].clear()
    drawer=open_ai(ui);drawer.get_by_label('允许本次会话发送问题和最小记录摘要给已配置模型服务',exact=True).check()
    pending=[]
    def interrupted(route):
        payload=route.request.post_data_json;pending.append(payload)
        with ui['db'].info['browser_lock']:
            chatbody=ai.ChatBody(**payload)
            held,_=ai.reserve(ui['actors']['operator']['user'],chatbody,'chat')
            ai.before_outbound(ui['actors']['operator']['user'],held,[],payload['request_id'])
            expire(ui['db'],chatbody)
        route.fulfill(json={'code':0,'data':{'status':'pending','request_id':payload['request_id'],'conversation_id':held['conversation_id'],'answer':None,'sources':[],'tool_trace':[]}})
    p.route('**/api/v1/ai/chat',interrupted)
    drawer.get_by_label('你的问题',exact=True).fill('中断后查询原请求状态');drawer.get_by_role('button',name='发送问题',exact=True).click()
    expect(drawer.get_by_role('button',name='新会话',exact=True)).to_be_disabled()
    drawer.get_by_role('button',name='使用原请求 ID 查询结果',exact=True).click()
    expect(drawer).to_contain_text('中断请求已恢复');expect(drawer).to_contain_text('费用未知，保守记账')
    expect(drawer.get_by_role('button',name='新会话',exact=True)).to_be_enabled()
    assert len(pending)==1 and not ui['seen']
    assert any(x[0]=='GET' and x[1].endswith('/requests/'+pending[0]['request_id']) for x in ui['requests'])
    assert not any('/ai/config' in x[1] or '/ai/usage' in x[1] or '/ai/recover' in x[1] or '/reconcile' in x[1] for x in ui['requests'])
    shot(ui,'closeout-own-recovered');drawer.get_by_role('button',name='新会话',exact=True).click();expect(drawer.locator('.ai-question')).to_have_count(0)
