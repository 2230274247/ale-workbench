"""Opt-in real-browser phase-two acceptance; no routes or API responses mocked.

ALE_BROWSER_TEST=1 LD_LIBRARY_PATH=/tmp/libs/x/usr/lib/x86_64-linux-gnu \
/tmp/ale-repair314/bin/python -m pytest tests/test_phase2_browser.py -v -s
Uses conftest's per-request SAVEPOINT override and an outer MySQL rollback.
"""
import os
import threading
import time
import uuid
from urllib.parse import urlparse

import pytest
from sqlalchemy import select
from app.db import engine, metadata, table

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8012'


@pytest.fixture
def db():
    """Same outer transaction as conftest, with post-rollback independent checks."""
    metadata()  # Missing phase-two migrations must fail acceptance, not silently skip.
    connection = engine().connect()
    transaction = connection.begin()
    prefix = 'P2B-' + uuid.uuid4().hex[:12]
    connection.info['phase2_prefix'] = prefix
    try:
        yield connection
    finally:
        # Collect only this transaction's fixture rows, including login/session/audit writes.
        users = table('users')
        user_ids = list(connection.scalars(select(users.c.user_id).where(users.c.username.like('test_%'))))
        # Existing test_* users must never become part of this test's cleanup assertion.
        # Only uncommitted users are invisible to a second connection.
        with engine().connect() as independent:
            committed = set(independent.scalars(select(users.c.user_id).where(users.c.user_id.in_(user_ids))))
        user_ids = [uid for uid in user_ids if uid not in committed]
        owned = {}
        for name, owner in [('users', 'user_id'), ('auth_sessions', 'user_id'), ('audit_log', 'user_id'),
                            ('batches', 'owner_user_id'), ('samples', 'owner_user_id'),
                            ('experiment_plans', 'owner_user_id'), ('processes', 'operator_user_id'),
                            ('sample_transitions', 'operator_user_id')]:
            t = table(name)
            pk = list(t.primary_key)[0]
            owned[name] = list(connection.scalars(select(pk).where(t.c[owner].in_(user_ids))))
        for name, parent, ids in [('experiment_plan_steps', 'plan_id', owned['experiment_plans']),
                                  ('process_steps', 'process_id', owned['processes']),
                                  ('process_samples', 'process_id', owned['processes'])]:
            t = table(name)
            owned[name] = list(connection.scalars(select(list(t.primary_key)[0]).where(t.c[parent].in_(ids))))
        transaction.rollback()
        connection.close()
        with engine().connect() as independent:
            for name, ids in owned.items():
                t = table(name)
                assert not independent.execute(select(list(t.primary_key)[0]).where(list(t.primary_key)[0].in_(ids))).first(), f'Permanent fixture data in {name}'
        print(f'ROLLBACK VERIFIED {prefix}: ' + ', '.join(f'{n}={len(ids)}' for n, ids in owned.items()) + '; new connection finds zero fixture rows')


@pytest.fixture
def ui(client, actors, db):
    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.main import app
    from app.config import ROOT

    prefix = db.info['phase2_prefix']
    def create(kind, payload):
        r = client.post('/api/v1/' + kind, headers=actors['operator']['headers'], json=payload)
        assert r.status_code == 201, r.text
        return r.json()['data']

    batch = create('batches', {'batch_code': prefix + '-B', 'batch_name': '浏览器第二轮验收（回滚）'})
    samples = [create('samples', {'sample_code': prefix + f'-S{i}', 'batch_id': batch['batch_id']}) for i in range(1, 4)]
    output = ROOT / 'reports' / 'screenshots'
    assert output.is_dir(), 'Use existing screenshot directory'
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8012, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started, 'Uvicorn did not start on 8012'
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
            page = context.new_page()
            page.set_default_timeout(8000)
            errors, responses = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('response', lambda r: responses.append((r.request.method, urlparse(r.url).path, r.status)) if '/api/v1/' in r.url else None)
            state = dict(page=page, context=context, client=client, actors=actors, db=db, prefix=prefix,
                         batch=batch, samples=samples, output=output, errors=errors, responses=responses)
            try:
                yield state
            finally:
                if page and not page.is_closed():
                    page.screenshot(path=str(output / f'phase2-{page.viewport_size["width"]}-last.png'), full_page=True)
                print('REAL HTTP EVIDENCE:', [r for r in responses if r[0] != 'GET' or r[2] >= 400])
                print('BROWSER ERRORS:', errors)
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive(), 'Uvicorn thread still running'


def login(ui, role='operator'):
    page = ui['page']
    page.goto(BASE + '/login')
    page.get_by_label('用户名', exact=True).fill(ui['actors'][role]['user']['username'])
    page.get_by_label('密码', exact=True).fill('TestPassword123!')
    page.get_by_role('button', name='登录工作台', exact=True).click()
    page.get_by_role('heading', name='工作台概览', exact=True).wait_for()


def navigate(page, path):
    # Exercise the running Vue router without reloading the document/auth session.
    page.evaluate("path => {history.pushState({}, '', path); window.dispatchEvent(new PopStateEvent('popstate'))}", path)


def capture(ui, name):
    page = ui['page']
    page.wait_for_timeout(200)  # Element Plus transitions only; API waits are explicit.
    size = page.evaluate('({viewport: innerWidth, body: document.body.scrollWidth, document: document.documentElement.scrollWidth})')
    page.screenshot(path=str(ui['output'] / f'phase2-{page.viewport_size["width"]}-{name}.png'), full_page=True)
    assert max(size['body'], size['document']) <= size['viewport'] + 1, f'{name}: {size}'
    print(f'LAYOUT {page.viewport_size["width"]} {name}: {size}')


def write(ui, path, action, status=201):
    page = ui['page']
    with page.expect_response(lambda r: urlparse(r.url).path == '/api/v1' + path and r.request.method == 'POST') as pending:
        action()
    r = pending.value
    assert r.status == status, r.text()
    return r.json()['data']


def get(ui, path):
    r = ui['client'].get('/api/v1' + path, headers=ui['actors']['operator']['headers'])
    assert r.status_code == 200, r.text
    return r.json()['data']


def choose(page, scope, field, option):
    scope.get_by_label(field, exact=True).locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")]').click()
    page.get_by_role('option', name=option, exact=True).click()


def plan_step(ui, index, kind, cycles):
    """Round 8: plan steps are created and edited only in the 2D grid dialog."""
    page = ui['page']
    navigate(page, f'/plans?plan_id={ui["plan"]["plan_id"]}')
    page.get_by_test_id('edit-process-grid').click()
    dialog = page.get_by_role('dialog', name='计划流程网格', exact=True)
    dialog.wait_for()
    dialog.get_by_role('button', name='添加步骤列', exact=True).first.click()
    expect_cols = dialog.get_by_label('步骤列名称', exact=True)
    assert expect_cols.count() == index, expect_cols.count()
    expect_cols.nth(index - 1).fill(kind)
    dialog.get_by_label('步骤列分类', exact=True).nth(index - 1).fill(kind)
    dialog.get_by_label(f'{kind} 温度 温度 值', exact=True).fill('275.00')
    # A custom row replaces the old free parameter group; it is shared by all columns.
    dialog.get_by_label('自定义参数行名称', exact=True).fill('循环数')
    dialog.get_by_role('button', name='添加参数行', exact=True).click()
    dialog.get_by_label(f'{kind} 自定义 循环数 值', exact=True).fill(str(cycles))
    capture(ui, f'plan-step-{index}')
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith('/process-grid')) as saved:
        dialog.get_by_test_id('save-process-grid').click()
    assert saved.value.status == 200, saved.value.text()
    dialog.wait_for(state='hidden')
    steps = get(ui, f'/plans/{ui["plan"]["plan_id"]}')['steps']
    step = next(s for s in steps if s['step_name'] == kind)
    page.locator('.experiment-step').filter(has_text=f'步骤 #{step["step_id"]}').wait_for()
    return step


def new_run(ui, suffix, sample_indices):
    page = ui['page']
    navigate(page, f'/plans?plan_id={ui["plan"]["plan_id"]}')
    page.get_by_role('button', name='选样品并创建执行', exact=True).click()
    drawer = page.get_by_role('dialog', name='创建实验执行', exact=True)
    drawer.get_by_label('执行编码', exact=True).fill(ui['prefix'] + suffix)
    # 第四轮第 3 项起，从计划发起执行会自动继承计划步骤骨架（映射 plan_step_id，不复制计划参数值）。
    # 本用例专门验证“手工新建实际步骤”的旧路径，因此先确认继承确实发生，再逐条移除骨架，
    # 之后由 actual_step 用显式 step_index 重新创建：既覆盖新联动，也不丢失原有覆盖。
    from playwright.sync_api import expect as expect_inherit
    expect_inherit(drawer.get_by_test_id('plan-inherit-note')).to_be_visible()
    # Round 8: inherited drafts are read-only here; clear them inside the grid dialog.
    drawer.get_by_test_id('create-process-grid').click()
    grid = page.get_by_role('dialog', name='实际流程网格', exact=True)
    grid.wait_for()
    assert grid.get_by_label('步骤列名称', exact=True).count() >= 1
    while grid.get_by_role('button', name='移除列', exact=True).count():
        grid.get_by_role('button', name='移除列', exact=True).first.click()
    grid.get_by_test_id('save-process-grid').click()
    grid.wait_for(state='hidden')
    # 第四轮第 4 项把手填样品 ID 改成可搜索多选控件（SamplePicker），
    # 定位方式随之由占位文本改为稳定的 data-testid，断言的不变量保持不变：
    # 仍按真实 sample_code 勾选、仍不装载样品、仍校验绑定集合完全一致。
    picker = drawer.get_by_test_id('sample-picker')
    picker.click()
    for index in sample_indices:
        page.get_by_role('option').filter(has_text=ui['samples'][index]['sample_code']).click()
    page.keyboard.press('Escape')
    capture(ui, 'create-run' + suffix)
    run = write(ui, '/processes', lambda: drawer.get_by_role('button', name='保存实验执行', exact=True).click())
    drawer.wait_for(state='hidden')
    page.get_by_role('heading', name=run['process_code'], exact=True).wait_for()
    assert {s['sample_id'] for s in run['samples']} == {ui['samples'][i]['sample_id'] for i in sample_indices}
    assert all(s['sample']['status'] == 'available' for s in run['samples']), 'Binding must not load samples'
    return run


def actual_step(ui, run, index, planned, kind, temperature=None):
    """Round 8: actual steps are created and edited only in the 2D grid dialog."""
    page = ui['page']
    navigate(page, f'/processes?process_id={run["process_id"]}')
    page.get_by_test_id('edit-process-grid').click()
    dialog = page.get_by_role('dialog', name='实际流程网格', exact=True)
    dialog.wait_for()
    dialog.get_by_role('button', name='添加步骤列', exact=True).first.click()
    cols = dialog.get_by_label('步骤列名称', exact=True)
    assert cols.count() == index, cols.count()
    cols.nth(index - 1).fill(kind)
    dialog.get_by_label('步骤列分类', exact=True).nth(index - 1).fill(kind)
    # The plan mapping is chosen in the grid header (IDs only, no value copy).
    mapping = dialog.get_by_label('映射计划步骤', exact=True).nth(index - 1)
    mapping.select_option(str(planned['step_id']))
    assert dialog.get_by_label(f'{kind} 温度 温度 值', exact=True).input_value() == ''
    if temperature:
        dialog.get_by_label(f'{kind} 温度 温度 值', exact=True).fill(temperature)
    capture(ui, f'actual-step-{index}')
    with page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith('/process-grid')) as saved:
        dialog.get_by_test_id('save-process-grid').click()
    assert saved.value.status == 200, saved.value.text()
    dialog.wait_for(state='hidden')
    steps = get(ui, f'/processes/{run["process_id"]}')['steps']
    step = next(s for s in steps if s['step_name'] == kind and s['step_index'] == index)
    page.locator('.experiment-step').filter(has_text=f'步骤 #{step["step_id"]}').wait_for()
    assert step['plan_step_id'] == planned['step_id'] and step['cycles'] is None
    assert step['actual_temp_c'] is None
    assert step['parameter_snapshot']['temperature']['value'] == temperature
    return step


def event(ui, sample, run, kind, step):
    from playwright.sync_api import expect
    page = ui['page']
    navigate(page, f'/sample-history?sample_id={sample["sample_id"]}&process_id={run["process_id"]}')
    page.get_by_role('button', name='追加流转', exact=True).click()
    drawer = page.get_by_role('dialog', name='追加样品流转', exact=True)
    choose(page, drawer, '事件', '装载' if kind == 'load' else '卸载')
    drawer.get_by_role('button', name='按事件建议目标状态', exact=True).click()
    drawer.get_by_label('实际步骤 ID（可空，需属于此次执行）', exact=True).fill(str(step['step_id']))
    drawer.get_by_label('位置', exact=True).fill(f'节点 {step["step_index"]}')
    drawer.get_by_label('备注', exact=True).fill(f'{run["process_code"]} {kind}')
    capture(ui, f'{run["process_code"].split("-")[-1]}-{sample["sample_code"].split("-")[-1]}-{kind}')
    result = write(ui, f'/samples/{sample["sample_id"]}/transitions', lambda: drawer.get_by_role('button', name='追加流转', exact=True).click())
    drawer.wait_for(state='hidden')
    expect(page.locator('.history-sample')).to_contain_text('当前状态：' + ('加工中' if kind == 'load' else '可用'))
    expect(page.locator('.el-table__body tr').filter(has_text=f'{run["process_code"]} {kind}')).to_have_count(1)
    assert result['step_id'] == step['step_id'] and result['process_id'] == run['process_id']
    assert result['event_at'] is None
    return result


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)], ids=['desktop1440', 'narrow390'])
def test_phase2_browser_end_to_end(ui, width, height):
    from playwright.sync_api import expect
    page = ui['page']
    page.set_viewport_size({'width': width, 'height': height})
    login(ui)
    capture(ui, 'login-home')
    navigate(page, '/plans')
    page.get_by_role('button', name='新建实验计划', exact=True).click()
    drawer = page.get_by_role('dialog', name='创建实验计划', exact=True)
    drawer.get_by_label('计划编码', exact=True).fill(ui['prefix'] + '-PLAN')
    drawer.get_by_label('计划标题', exact=True).fill('第二轮真实浏览器验收')
    from test_phase4_browser import field,select_option
    select_option(ui,field(ui,drawer,'批次（可空）'),ui['batch']['batch_code'])
    capture(ui, 'create-plan')
    ui['plan'] = write(ui, '/plans', lambda: drawer.get_by_role('button', name='保存实验计划', exact=True).click())
    drawer.wait_for(state='hidden')
    planned = [plan_step(ui, 1, 'O₃ / 吹扫', 50), plan_step(ui, 2, 'HF / 吹扫', 20)]
    run = new_run(ui, '-RUN1', [0, 1])
    steps = [actual_step(ui, run, 1, planned[0], 'O₃ / 吹扫'), actual_step(ui, run, 2, planned[1], 'HF / 吹扫', '123.45')]
    # A third sample is bound from the actual binding dialog, rather than seeded by API.
    page.get_by_role('button', name='绑定单个样品（可附加逐条差异）', exact=True).click()
    binding = page.get_by_role('dialog', name='样品绑定', exact=True)
    # 第四轮第 4 项：单条绑定也不再手填样品 ID，改为可搜索选择器。
    binding.get_by_test_id('child-sample-picker').click()
    page.get_by_role('option').filter(has_text=ui['samples'][2]['sample_code']).click()
    binding.get_by_test_id('child-sample-picker').click()
    binding.get_by_label('腔体位置', exact=True).fill('C3')
    write(ui, f'/processes/{run["process_id"]}/samples', lambda: binding.get_by_role('button', name='保存', exact=True).click())
    binding.wait_for(state='hidden')
    expect(page.locator('.experiment-step').filter(has_text=ui['samples'][2]['sample_code'])).to_be_visible()
    capture(ui, 'run-bindings')
    assert len(get(ui, f'/processes/{run["process_id"]}')['samples']) == 3
    events = []
    for sample in ui['samples'][:2]:
        events.append(event(ui, sample, run, 'load', steps[0]))
    events.append(event(ui, ui['samples'][0], run, 'unload', steps[0]))
    assert get(ui, f'/samples/{ui["samples"][1]["sample_id"]}')['status'] == 'in_process'
    events.append(event(ui, ui['samples'][1], run, 'unload', steps[1]))
    second = new_run(ui, '-RUN2', [0])
    second_step = actual_step(ui, second, 1, planned[0], 'O₃ / 吹扫')
    events.append(event(ui, ui['samples'][0], second, 'load', second_step))
    events.append(event(ui, ui['samples'][0], second, 'unload', second_step))
    history = get(ui, f'/samples/{ui["samples"][0]["sample_id"]}/transitions')
    assert [h['event_type'] for h in history] == ['receive', 'load', 'unload', 'load', 'unload']
    assert [h['process_id'] for h in history[1:]] == [run['process_id']] * 2 + [second['process_id']] * 2
    assert [h['transition_id'] for h in history] == sorted(h['transition_id'] for h in history)
    expect(page.locator('.el-table__body tr')).to_have_count(5)
    capture(ui, 'repeat-history')
    # History -> execution -> sample history are genuine page links.
    page.get_by_role('link', name=f'执行 #{run["process_id"]}', exact=True).first.click()
    page.get_by_role('heading', name=run['process_code'], exact=True).wait_for()
    page.locator('.experiment-step').filter(has_text=ui['samples'][0]['sample_code']).get_by_role('button', name='完整历史 / 装卸记录', exact=True).click()
    expect(page.locator('.el-table__body tr')).to_have_count(5)
    capture(ui, 'history-link')
    # Demote the same fixture owner: viewer can still see its own plan/run/history.
    uid = ui['actors']['operator']['user']['user_id']
    r = ui['client'].patch(f'/api/v1/users/{uid}', headers=ui['actors']['admin']['headers'], json={'role': 'viewer'})
    assert r.status_code == 200, r.text
    ui['context'].clear_cookies()
    page.goto(BASE + '/login')  # fresh document clears in-memory access token
    login(ui)
    writes = []
    page.on('request', lambda r: writes.append((r.method, r.url)) if r.method in ('POST', 'PATCH', 'DELETE', 'PUT') and '/api/v1/auth/' not in r.url else None)
    for path, heading, count in [(f'/plans?plan_id={ui["plan"]["plan_id"]}', ui['plan']['plan_code'], 2),
                                  (f'/processes?process_id={run["process_id"]}', run['process_code'], 5)]:
        navigate(page, path)
        page.get_by_role('heading', name=heading, exact=True).wait_for()
        expect(page.locator('.experiment-step')).to_have_count(count)
        for button in ['新建实验计划', '新建实验执行', '添加步骤', '编辑基本信息', '绑定样品', '编辑', '删除', '解除绑定', '选样品并创建执行']:
            expect(page.get_by_role('button', name=button, exact=True)).to_have_count(0)
        capture(ui, 'viewer-' + ('plan' if '/plans?' in path else 'run'))
    navigate(page, f'/sample-history?sample_id={ui["samples"][0]["sample_id"]}')
    expect(page.locator('.el-table__body tr')).to_have_count(5)
    expect(page.get_by_role('button', name='追加流转', exact=True)).to_have_count(0)
    expect(page.get_by_role('link', name='创建执行', exact=True)).to_have_count(0)
    capture(ui, 'viewer-history')
    assert not writes, writes
    # Use the viewer token issued by the real browser login for server-side denial.
    # No fabricated success and no injected page storage.
    denied = page.evaluate('''async ({plan, sample, run}) => {
      const response = await fetch('/api/v1/auth/refresh', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      const token = (await response.json()).data.access_token;
      const headers = {'Content-Type':'application/json',Authorization:'Bearer '+token};
      return await Promise.all([
        fetch('/api/v1/plans/'+plan,{method:'PATCH',headers,body:JSON.stringify({title:'forbidden'})}),
        fetch('/api/v1/processes/'+run+'/steps',{method:'POST',headers,body:JSON.stringify({step_index:9,step_kind:'other'})}),
        fetch('/api/v1/samples/'+sample+'/transitions',{method:'POST',headers,body:JSON.stringify({event_type:'receive',to_status:'available',expected_row_version:1})})
      ]).then(rs=>rs.map(r=>r.status));
    }''', {'plan': ui['plan']['plan_id'], 'sample': ui['samples'][0]['sample_id'], 'run': run['process_id']})
    assert denied == [403, 403, 403], denied
    # Make RUN2 invisible while the sample remains visible; real history API
    # must retain its states and the UI must distinguish redaction from no run.
    runs = table('processes')
    ui['db'].execute(runs.update().where(runs.c.process_id == second['process_id']).values(
        operator_user_id=ui['actors']['other']['user']['user_id']))
    navigate(page, f'/sample-history?sample_id={ui["samples"][0]["sample_id"]}&redaction_check=1')
    expect(page.locator('.el-table__body tr')).to_have_count(5)
    protected = page.locator('.el-table__body tr').filter(has_text='关联信息受权限保护')
    expect(protected).to_have_count(2)
    expect(protected.get_by_text('无关联执行', exact=True)).to_have_count(0)
    expect(protected.get_by_text('未填写备注', exact=True)).to_have_count(0)
    expect(protected.get_by_role('link', name=f'执行 #{second["process_id"]}', exact=True)).to_have_count(0)
    print(f'REDACTION UI VERIFIED {width}: two protected rows, states retained; no misleading empty context')
    assert not ui['errors'], ui['errors']
    unexpected = [r for r in ui['responses'] if r[2] >= 400 and not (r[2] == 403 and r[0] in ('POST', 'PATCH')) and r[1] != '/api/v1/auth/refresh']
    assert not unexpected, unexpected
    print(f'WORKFLOW VERIFIED {width}: plan={ui["plan"]["plan_id"]}, runs={[run["process_id"], second["process_id"]]}, transitions={[e["transition_id"] for e in events]}, viewer_denials={denied}')
