"""Real Chromium wizard editing and close/reopen acceptance; all writes roll back."""
import os
import threading
import time
import pytest
from playwright.sync_api import sync_playwright, expect
from test_phase4_browser import db, client, database_manifest, originals_manifest

pytestmark=pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST')!='1',reason='Opt-in browser acceptance')

@pytest.mark.parametrize('width',[1500,390])
def test_wizard_real_edit_resume(client,actors,db,monkeypatch,tmp_path,width):
    import uvicorn
    import app.main as main
    if os.getenv('ALE_TEST_FRONTEND'):
        (tmp_path/'frontend').symlink_to(os.environ['ALE_TEST_FRONTEND'],target_is_directory=True)
        monkeypatch.setattr(main,'ROOT',tmp_path)
    server=uvicorn.Server(uvicorn.Config(main.app,host='127.0.0.1',port=8038,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started
    base='http://127.0.0.1:8038'
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':width,'height':1000})
            page=context.new_page();page.set_default_timeout(15000)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/login')
            page.get_by_label('用户名',exact=True).fill(actors['operator']['user']['username'])
            page.get_by_label('密码',exact=True).fill('TestPassword123!')
            page.get_by_role('button',name='登录工作台',exact=True).click()
            page.get_by_role('heading',name='工作台概览',exact=True).wait_for()
            page.goto(base+'/experiments/new')
            page.get_by_role('heading',name='开始新实验',exact=True).wait_for()
            page.get_by_label('研究目标',exact=True).fill('关闭后恢复目标')
            page.get_by_label('计划标题',exact=True).fill('向导真实浏览器验收')
            page.get_by_role('button',name='保存目标与草稿',exact=True).click()
            page.wait_for_url('**/experiments/new?plan_id=*')
            page.get_by_role('button',name='工艺矩阵：待记录（可跳过）',exact=True).click()
            page.get_by_role('button',name='高级编辑',exact=True).click()
            page.get_by_role('button',name='添加步骤列',exact=True).first.click()
            page.get_by_label('步骤列名称',exact=True).fill('计划脉冲')
            page.get_by_label('计划脉冲 脉冲 时长 值',exact=True).fill('12')
            page.get_by_role('button',name='保存工艺矩阵',exact=True).click()
            expect(page.get_by_role('button',name='工艺矩阵：已保存',exact=True)).to_be_visible()
            saved_url=page.url
            page.close();page=context.new_page();page.set_default_timeout(15000)
            page.goto(saved_url)
            expect(page.get_by_label('研究目标',exact=True)).to_have_value('关闭后恢复目标')
            page.get_by_role('button',name='实际参数：待记录（可跳过）',exact=True).click()
            page.get_by_role('button',name='建立执行并载入空值步骤',exact=True).click()
            page.wait_for_url('**/experiments/new?process_id=*')
            page.get_by_role('button',name='高级编辑',exact=True).click()
            expect(page.get_by_label('计划脉冲 脉冲 时长 值',exact=True)).to_have_value('')
            page.get_by_label('计划脉冲 脉冲 时长 值',exact=True).fill('9')
            page.get_by_role('button',name='保存实际参数',exact=True).click()
            expect(page.get_by_role('button',name='实际参数：已保存',exact=True)).to_be_visible()
            run_url=page.url;page.reload()
            page.get_by_role('button',name='实际参数：已保存',exact=True).click()
            page.get_by_role('button',name='高级编辑',exact=True).click()
            expect(page.get_by_label('计划脉冲 脉冲 时长 值',exact=True)).to_have_value('9')
            page.get_by_role('button',name='测量与分析：待记录（可跳过）',exact=True).click()
            expect(page.get_by_text('尚无本次执行的有效测量，可稍后继续。',exact=True)).to_be_visible()
            page.goto(run_url)
            expect(page.get_by_role('button',name='测量与分析：待记录（可跳过）',exact=True)).to_be_attached()
            assert not errors,errors
            page.screenshot(path=str(tmp_path/f'wizard-{width}.png'),full_page=True)
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10)

# Failure injection forwards the request to the real transaction before dropping
# its response. This distinguishes an uncertain committed write from a rejected one.
from test_round8_workspace_integration_browser import ui, BASE, get
from test_phase5_sample_void import call
import json


def drop_committed_response(page, pattern, attempts):
    def intercept(route):
        if route.request.method != 'POST':
            route.continue_(); return
        body = route.request.post_data_json
        response = route.fetch()
        attempts.append((body, response.status))
        assert response.status == 201, response.text()
        if len(attempts) == 1:
            route.abort('failed')
        else:
            route.fulfill(response=response)
    page.route(pattern, intercept)


@pytest.mark.parametrize('kind', ['plans', 'processes'])
def test_wizard_lost_parent_response_retries_same_identity(ui, kind):
    p = ui['page']
    attempts = []
    drop_committed_response(p, f'**/api/v1/workflow/{kind}', attempts)
    with p.expect_response(lambda r: '/api/v1/workflow/state' in r.url):
        p.goto(BASE + '/experiments/new?stage=1')
    expect(p.locator('.experiment-wizard .el-loading-mask')).to_have_count(0)
    if kind == 'plans':
        p.get_by_label('计划标题', exact=True).fill('响应丢失仍只有一个计划')
    else:
        p.get_by_text('独立执行', exact=True).click()
    p.get_by_role('button', name='保存并建立草稿', exact=True).click()
    expect(p.get_by_text('创建结果尚未确认', exact=False).first).to_be_visible()
    code = attempts[0][0]['plan_code' if kind == 'plans' else 'process_code']
    assert len(code) <= 64
    before = get(ui, f'/{kind}?keyword={code}&size=200')
    assert len([r for r in before if r['plan_code' if kind == 'plans' else 'process_code'] == code]) == 1
    # Changing the editor cannot change an already sent logical create request.
    if kind == 'plans':
        p.get_by_label('计划标题', exact=True).fill('重试期间的本地文字')
    p.get_by_role('button', name='保存并建立草稿', exact=True).click()
    p.wait_for_url(f'**/experiments/new?{"plan_id" if kind == "plans" else "process_id"}=*&stage=1')
    assert len(attempts) == 2 and attempts[0][0] == attempts[1][0]
    after = get(ui, f'/{kind}?keyword={code}&size=200')
    assert len([r for r in after if r['plan_code' if kind == 'plans' else 'process_code'] == code]) == 1
    print(f'PASS {kind}: committed POST response dropped; retry kept {code}; exactly one record; payload identical')


@pytest.mark.parametrize('independent', [False, True])
def test_wizard_matrix_put_503_preserves_draft_after_parent_creation(ui, independent):
    p = ui['page']
    with p.expect_response(lambda r: '/api/v1/workflow/state' in r.url):
        p.goto(BASE + '/experiments/new?stage=1')
    expect(p.locator('.experiment-wizard .el-loading-mask')).to_have_count(0)
    if independent:
        p.get_by_text('独立执行', exact=True).click()
    else:
        p.get_by_label('计划标题', exact=True).fill('首建父记录后矩阵恢复')
    p.get_by_role('button', name='研究目标：待记录（可跳过）', exact=True).click()
    p.get_by_label('研究目标', exact=True).fill('保留目标与执行备注\n第二行 μs')
    p.get_by_role('button', name='工艺矩阵：待记录（可跳过）', exact=True).click()
    p.get_by_role('button', name='高级编辑', exact=True).click()
    p.get_by_role('button', name='添加步骤列', exact=True).first.click()
    p.get_by_label('步骤列名称', exact=True).fill('保留全部输入')
    p.get_by_label('保留全部输入 脉冲 时长 值', exact=True).fill('12.75')
    p.get_by_label('保留全部输入 脉冲 时长 单位', exact=True).fill('μs')
    p.get_by_label('保留全部输入 温度 温度 值', exact=True).fill('105')
    p.get_by_label('总循环数', exact=True).fill('33')
    p.get_by_role('button', name='添加嵌套组', exact=True).first.click()
    p.get_by_label('流程组名称', exact=True).fill('空值组也保留')
    p.get_by_label('组重复次数', exact=True).fill('7')
    before = p.locator('[data-testid="process-grid"] input').evaluate_all('(els)=>els.map(e=>[e.getAttribute("aria-label"),e.value])')
    parents = []; puts = []
    p.on('request', lambda r: parents.append(r.post_data_json) if r.method == 'POST' and '/workflow/' in r.url else None)
    def fail_once(route):
        if route.request.method != 'PUT':
            route.continue_(); return
        puts.append(route.request.post_data_json)
        if len(puts) == 1:
            route.fulfill(status=503, content_type='application/json', body=json.dumps({'code':503,'message':'injected matrix failure'}))
        else:
            route.continue_()
    p.route('**/api/v1/*/*/process-grid', fail_once)
    p.get_by_role('button', name='保存工艺矩阵', exact=True).click()
    expect(p.get_by_text('工艺矩阵尚未确认保存', exact=False).first).to_be_visible()
    expect(p.get_by_text('有未保存修改', exact=True)).to_be_visible()
    assert p.locator('[data-testid="process-grid"] input').evaluate_all('(els)=>els.map(e=>[e.getAttribute("aria-label"),e.value])') == before
    saved_url = p.url
    p.get_by_role('button', name='保存工艺矩阵', exact=True).click()
    expect(p.get_by_role('button', name='工艺矩阵：已保存', exact=True)).to_be_visible()
    expect(p.get_by_text('有未保存修改', exact=True)).to_have_count(0)
    assert len(parents) == 1 and len(puts) == 2 and puts[0] == puts[1]
    assert p.url == saved_url
    from urllib.parse import parse_qs, urlparse
    key = 'process_id' if independent else 'plan_id'
    ident = parse_qs(urlparse(saved_url).query)[key][0]
    row = get(ui, f'/{"processes" if independent else "plans"}/{ident}')
    assert row['notes' if independent else 'objective'] == '保留目标与执行备注\n第二行 μs'
    assert p.locator('[data-testid="process-grid"] input').evaluate_all('(els)=>els.map(e=>[e.getAttribute("aria-label"),e.value])') == before
    print(f'PASS matrix independent={independent}: PUT503 retained all values/units/groups/repeats and dirty flag; retry identical PUT; one parent')


def test_wizard_lost_sample_response_reconciles_without_reposting(ui):
    p = ui['page']
    import uuid
    batch = call(ui['client'], ui['actors'], 'post', '/batches', {'batch_code':'WB-'+uuid.uuid4().hex,'batch_name':'uncertain samples'}, status=201)
    with p.expect_response(lambda r: '/api/v1/workflow/state' in r.url):
        p.goto(BASE + '/experiments/new?stage=1')
    expect(p.locator('.experiment-wizard .el-loading-mask')).to_have_count(0)
    p.get_by_label('计划标题', exact=True).fill('样品响应丢失恢复')
    p.get_by_role('combobox', name='实验批次', exact=True).click()
    p.get_by_role('option', name=batch['batch_code'], exact=True).click()
    p.get_by_role('button', name='参与样品：待记录（可跳过）', exact=True).click()
    p.get_by_label('样品数量', exact=True).fill('3')
    attempts = []
    drop_committed_response(p, '**/api/v1/batches/*/samples/batch', attempts)
    p.get_by_role('button', name='创建样品并选中', exact=True).click()
    expect(p.get_by_role('button', name='核对上次样品创建结果', exact=True)).to_be_visible()
    expect(p.get_by_text('样品任务', exact=False).first).to_be_visible()
    codes = {row['sample_code'] for row in attempts[0][0]['items']}
    # Failed reconciliation must leave the pending group, and send no second POST.
    def unavailable(route):
        route.fulfill(status=503, content_type='application/json', body=json.dumps({'code':503,'message':'injected lookup failure'}))
    p.route('**/api/v1/samples?**', unavailable)
    p.get_by_role('button', name='核对上次样品创建结果', exact=True).click()
    expect(p.get_by_text('injected lookup failure', exact=False).first).to_be_visible()
    assert len(attempts) == 1
    p.unroute('**/api/v1/samples?**', unavailable)
    p.get_by_role('button', name='核对上次样品创建结果', exact=True).click()
    expect(p.get_by_role('button', name='创建样品并选中', exact=True)).to_be_visible()
    expect(p.get_by_role('button', name='绑定所选样品', exact=True)).to_be_enabled()
    assert len(attempts) == 1
    rows = get(ui, f"/samples?batch_id={batch['batch_id']}&size=200")
    assert len(rows) == 3 and {row['sample_code'] for row in rows} == codes
    p.get_by_role('button', name='绑定所选样品', exact=True).click()
    expect(p.get_by_role('button', name='参与样品：已保存', exact=True)).to_be_visible()
    assert len(attempts) == 1
    print('PASS samples: 3 committed rows; response dropped; lookup503 retained pending intent; lookup retry selected same 3; one bulk POST; binding succeeded')

# P0-B: finishing is navigation to the same persisted draft, never completion.
@pytest.mark.parametrize('kind', ['plans', 'processes'])
def test_p0_finish_without_measurement_resume_doubleclick(ui, kind):
    p = ui['page']
    body = {'title': 'P0 finish draft', 'objective': 'saved purpose'} if kind == 'plans' else {'process_mode': 'other', 'notes': 'saved purpose'}
    row = call(ui['client'], ui['actors'], 'post', '/workflow/' + kind, body, status=201)
    key = 'plan_id' if kind == 'plans' else 'process_id'
    ident = row[key]
    creates = []
    p.on('request', lambda r: creates.append(r.url) if r.method == 'POST' and '/workflow/' in r.url else None)
    p.goto(f'{BASE}/experiments/new?{key}={ident}&stage=6')
    finish = p.get_by_role('button', name='保存并查看实验', exact=True)
    expect(finish).to_be_enabled()
    expect(p.get_by_text('实验记录待完善', exact=False)).to_be_visible()
    from app.config import ROOT
    p.screenshot(path=str(ROOT / 'logsreports' / f'product-p0-finish-{kind}.png'), full_page=True)
    finish.evaluate('(e)=>{e.click();e.click()}')
    p.wait_for_url(f'**/{kind}?{key}={ident}')
    assert get(ui, f'/{kind}/{ident}') == row
    assert creates == []
    with p.expect_response(lambda r: '/api/v1/workflow/state' in r.url):
        p.goto(f'{BASE}/experiments/new?{key}={ident}')
    expect(p.locator('.experiment-wizard .el-loading-mask')).to_have_count(0)
    p.get_by_label('研究目标', exact=True).fill('later supplemental goal')
    p.get_by_role('button', name='测量与分析：待记录（可跳过）', exact=True).click()
    p.get_by_role('button', name='保存并查看实验', exact=True).click()
    p.wait_for_url(f'**/{kind}?{key}={ident}')
    saved = get(ui, f'/{kind}/{ident}')
    assert saved['objective' if kind == 'plans' else 'notes'] == 'later supplemental goal'
    assert saved['status' if kind == 'plans' else 'log_status'] == ('draft' if kind == 'plans' else 'unknown')
    assert creates == []
    print(f'P0 FINISH {kind} #{ident}: no measurement; double click; same detail; resume saved; zero creation POSTs; no completion state')


@pytest.mark.parametrize('kind', ['plans', 'processes'])
def test_p0_finish_lost_creation_response(ui, kind):
    p = ui['page']; attempts = []
    drop_committed_response(p, f'**/api/v1/workflow/{kind}', attempts)
    with p.expect_response(lambda r: '/api/v1/workflow/state' in r.url):
        p.goto(BASE + '/experiments/new?stage=1')
    expect(p.locator('.experiment-wizard .el-loading-mask')).to_have_count(0)
    if kind == 'plans':
        p.get_by_label('计划标题', exact=True).fill('P0 response lost')
    else:
        p.get_by_text('独立执行', exact=True).click()
    p.get_by_role('button', name='测量与分析：待记录（可跳过）', exact=True).click()
    p.get_by_role('button', name='保存并查看实验', exact=True).click()
    expect(p.get_by_text('创建结果尚未确认', exact=False).first).to_be_visible()
    if kind == 'plans':
        expect(p.get_by_label('计划标题', exact=True)).to_have_value('P0 response lost')
    p.get_by_role('button', name='测量与分析：待记录（可跳过）', exact=True).click()
    p.get_by_role('button', name='保存并查看实验', exact=True).click()
    p.wait_for_url(f'**/{kind}?*')
    assert len(attempts) == 2 and attempts[0][0] == attempts[1][0]
    code_key = 'plan_code' if kind == 'plans' else 'process_code'
    rows = get(ui, f'/{kind}?keyword={attempts[0][0][code_key]}&size=200')
    assert len(rows) == 1
    assert rows[0]['status' if kind == 'plans' else 'log_status'] == ('draft' if kind == 'plans' else 'unknown')
    print(f'P0 LOST RESPONSE {kind}: identical receipt replay; one record; detail opened; no measurements required')


def test_p0_finish_patch_failure_preserves_all_stages(ui):
    p = ui['page']
    row = call(ui['client'], ui['actors'], 'post', '/workflow/processes', {'process_mode': 'other', 'notes': 'original'}, status=201)
    ident = row['process_id']
    with p.expect_response(lambda r: '/api/v1/workflow/state' in r.url):
        p.goto(f'{BASE}/experiments/new?process_id={ident}')
    expect(p.locator('.experiment-wizard .el-loading-mask')).to_have_count(0)
    p.get_by_label('研究目标', exact=True).fill('retained goal')
    p.get_by_role('button', name='实际参数：待记录（可跳过）', exact=True).click()
    # Existing numeric input label is associated through ExperimentFields.
    control = p.locator('.el-form-item').filter(has_text='R1 温度').locator('input').first
    control.fill('101.25')
    def unavailable(route):
        if route.request.method == 'PATCH':
            route.fulfill(status=503, content_type='application/json', body=json.dumps({'code':503,'message':'P0 injected save failure'}))
        else: route.continue_()
    p.route(f'**/api/v1/processes/{ident}', unavailable)
    p.get_by_role('button', name='测量与分析：待记录（可跳过）', exact=True).click()
    p.get_by_role('button', name='保存并查看实验', exact=True).click()
    expect(p.get_by_text('P0 injected save failure', exact=False).first).to_be_visible()
    expect(p.get_by_label('研究目标', exact=True)).to_have_value('retained goal')
    p.get_by_role('button', name='实际参数：待记录（可跳过）', exact=True).click()
    expect(control).to_have_value('101.25')
    p.unroute(f'**/api/v1/processes/{ident}', unavailable)
    p.get_by_role('button', name='测量与分析：待记录（可跳过）', exact=True).click()
    p.get_by_role('button', name='保存并查看实验', exact=True).click()
    p.wait_for_url(f'**/processes?process_id={ident}')
    saved = get(ui, f'/processes/{ident}')
    assert saved['notes'] == 'retained goal' and saved['r1_temp_c'] == '101.25'
    assert saved['log_status'] == 'unknown'
    print('P0 FAILURE: goal and actual edits across stages retained after503; retry saved same run; no measurement, no completion')
