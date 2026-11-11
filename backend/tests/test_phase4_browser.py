"""Phase-four real-browser acceptance (opt-in).

Covers the six flows the fourth round promised: 批量创建 20 片小样、从实验计划发起执行、
搜索并批量绑定多片样品、自定义化学体系、弹窗未保存确认、导入成功/失败就地反馈。
Every write rolls back; originals are redirected into pytest's temporary directory.
Run:  ALE_BROWSER_TEST=1 python3 -m pytest tests/test_phase4_browser.py -v -s
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect
from sqlalchemy import select

from app.config import ROOT
from app.db import engine, metadata, table
from test_phase3_imports import workbook, unique

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8021'
SHOTS = ROOT / 'reports' / 'screenshots'


def database_manifest(connection):
    return {t.name: hashlib.sha256(json.dumps([dict(r) for r in connection.execute(select(t).order_by(*t.primary_key.columns)).mappings()], default=str, sort_keys=True).encode()).hexdigest()
            for t in metadata().tables.values()}


def originals_manifest():
    root = ROOT / 'storage' / 'originals'
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def db():
    with engine().connect() as independent:
        baseline = database_manifest(independent)
    original_baseline = originals_manifest()
    connection = engine().connect()
    tx = connection.begin()
    try:
        yield connection
    finally:
        tx.rollback()
        connection.close()
        with engine().connect() as independent:
            assert database_manifest(independent) == baseline, 'Committed DB changed'
        assert originals_manifest() == original_baseline, 'Production originals changed'
        print('ROLLBACK VERIFIED: %d tables and %d production originals identical' % (len(baseline), len(original_baseline)))


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app.security import limiter
    lock = threading.Lock()
    db.info['browser_lock'] = lock

    def override():
        with lock:
            with db.begin_nested():
                yield db
    app.dependency_overrides[get_db] = override
    limiter.entries.clear()
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def locked(db, statement):
    with db.info['browser_lock']:
        return [dict(r) for r in db.execute(statement).mappings()]


@pytest.fixture
def world(db, actors):
    """Real rows owned by the operator: one deposition batch, parent wafer, six coupons and a two-step plan."""
    uid = actors['operator']['user']['user_id']
    tag = uuid.uuid4().hex[:8]
    batch_code = f'P4B-{tag}'
    bid = db.execute(table('batches').insert().values(batch_code=batch_code, batch_name='第四轮验收批次', owner_user_id=uid)).inserted_primary_key[0]

    def add(code, sample_type, parent=None):
        return db.execute(table('samples').insert().values(
            sample_code=code, batch_id=bid, sample_type=sample_type, parent_sample_id=parent,
            status='available', exclude_from_analysis=False, owner_user_id=uid)).inserted_primary_key[0]

    parent_code = f'P4W-{tag}'
    parent = add(parent_code, 'parent_wafer')
    coupons = [add(f'P4C-{tag}-{i:02d}', 'coupon', parent) for i in range(1, 7)]
    plan_code = f'P4P-{tag}'
    plan = db.execute(table('experiment_plans').insert().values(
        plan_code=plan_code, title='第四轮验收计划', status='draft', priority='normal',
        owner_user_id=uid, batch_id=bid)).inserted_primary_key[0]
    for index, (kind, name) in enumerate([('o3_purge', '自定义暴露步骤'), ('hf_purge', '自定义吹扫步骤')], start=1):
        db.execute(table('experiment_plan_steps').insert().values(
            plan_id=plan, step_index=index, step_kind=kind, step_name=name,
            planned_parameters={'cycles': index * 3}, custom_parameters={'duration_s': {'value': None, 'unit': 's', 'note': None}}))
    return dict(batch_id=bid, batch_code=batch_code, parent=parent, parent_code=parent_code,
                coupons=coupons, coupon_codes=[f'P4C-{tag}-{i:02d}' for i in range(1, 7)],
                plan=plan, plan_code=plan_code, user=uid, tag=tag)


@pytest.fixture
def ui(client, actors, db, world, tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.main import app
    root = tmp_path / 'test_store'
    monkeypatch.setenv('ALE_ORIGINALS_ROOT', str(root))
    SHOTS.mkdir(parents=True, exist_ok=True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8021, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(120):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(8000)
            errors, responses = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('response', lambda r: responses.append((r.request.method, r.url.split('/api/v1/')[-1], r.status)) if '/api/v1/' in r.url else None)
            state = dict(page=page, context=context, actors=actors, client=client, db=db, world=world, errors=errors, responses=responses)
            try:
                yield state
            finally:
                print('JS ERRORS:', errors)
                print('HTTP EVIDENCE:', [r for r in responses if r[0] != 'GET' or r[2] >= 400])
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()
        if root.exists():
            shutil.rmtree(root)


# ---------------------------------------------------------------- helpers

def login(ui):
    p = ui['page']
    p.goto(BASE + '/login')
    p.get_by_label('用户名', exact=True).fill(ui['actors']['operator']['user']['username'])
    p.get_by_label('密码', exact=True).fill('TestPassword123!')
    p.get_by_role('button', name='登录工作台', exact=True).click()
    p.get_by_role('heading', name='工作台概览', exact=True).wait_for()


def capture(ui, name):
    p = ui['page']
    p.wait_for_timeout(400)
    size = p.evaluate('({viewport:innerWidth,body:document.body.scrollWidth,document:document.documentElement.scrollWidth})')
    p.screenshot(path=str(SHOTS / f'phase4-{name}.png'), full_page=True)
    assert max(size['body'], size['document']) <= size['viewport'] + 1, (name, size)
    print('LAYOUT OK', name, size)


def field(ui, scope, label):
    """Locate the control of an el-form-item whose label starts with `label`."""
    return scope.locator('.el-form-item').filter(has=ui['page'].locator('.el-form-item__label', has_text=label)).locator('input,textarea').first


def select_option(ui, control, text):
    """Open an Element Plus select. Clicking the inner input is intercepted by the
    placeholder layer in recent versions, so the wrapper is clicked instead."""
    wrapper = control.locator('xpath=ancestor-or-self::*[contains(concat(" ", normalize-space(@class), " "), " el-select ")][1]')
    (wrapper if wrapper.count() else control).first.click()
    ui['page'].wait_for_timeout(250)
    ui['page'].locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=text).first.click()


def pick_samples(ui, codes):
    """Drive the real SamplePicker: remote search then multi-select."""
    p = ui['page']
    control = p.locator('[data-testid="sample-picker"]:visible').first
    control.click()
    p.wait_for_timeout(300)
    for code in codes:
        control.locator('input').fill(code)
        p.wait_for_timeout(600)
        option = p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=code).first
        option.wait_for()
        option.click()
        p.wait_for_timeout(250)


def in_view(ui, selector):
    """Assert the feedback element is really inside the browser viewport, i.e. the user
    does not have to scroll back to the top of the page to read it."""
    p = ui['page']
    p.wait_for_timeout(700)
    box = p.evaluate('''sel=>{const el=document.querySelector(sel);if(!el)return null;const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,viewport:innerHeight,scrollY:scrollY}}''', selector)
    assert box, f'{selector} missing'
    assert box['bottom'] > 0 and box['top'] < box['viewport'], (selector, box, p.url)
    return box


# ---------------------------------------------------------------- 1. batch create

def test_p4_batch_create_twenty_coupons(ui):
    p, db, w = ui['page'], ui['db'], ui['world']
    login(ui)
    p.goto(BASE + '/batches')
    p.get_by_role('textbox', name='关键词').fill(w['batch_code'])
    p.get_by_role('button', name='查询', exact=True).click()
    p.get_by_role('button', name=w['batch_code'], exact=True).first.click()
    p.get_by_test_id('batch-create-open').wait_for()
    dialog = p.get_by_test_id('batch-create-dialog')
    p.get_by_test_id('batch-create-open').click()
    dialog.wait_for()

    select_option(ui, field(ui, dialog, '母片'), w['parent_code'])
    field(ui, dialog, '编号前缀').fill(f'P4N-{w["tag"]}-')
    field(ui, dialog, '片数').fill('20')
    dialog.get_by_role('button', name='按当前设置重新生成编号预览').click()
    preview = dialog.get_by_test_id('batch-preview').locator('.el-table__body-wrapper tbody tr')
    expect(preview).to_have_count(20)
    expect(dialog.get_by_test_id('batch-submit')).to_contain_text('提交创建 20 份小样')
    capture(ui, 'batch-create-20-preview')

    with p.expect_response(lambda r: r.url.endswith('/samples/batch') and r.request.method == 'POST') as posted:
        dialog.get_by_test_id('batch-submit').click()
    assert posted.value.status == 201, posted.value.text()[:400]
    dialog.wait_for(state='hidden')
    p.wait_for_timeout(400)

    created = locked(db, select(table('samples')).where(table('samples').c.sample_code.like(f'P4N-{w["tag"]}-%')))
    assert len(created) == 20, [c['sample_code'] for c in created]
    assert {c['parent_sample_id'] for c in created} == {w['parent']}, '母片关联未继承'
    assert {c['sample_type'] for c in created} == {'coupon'}
    print('BATCH:', len(created), 'coupons; sample codes', created[0]['sample_code'], '→', created[-1]['sample_code'])
    capture(ui, 'batch-create-20-done')


# ---------------------------------------------------------------- 2. plan → run → multi bind

def test_p4_plan_run_inheritance_and_multi_bind(ui):
    p, db, w = ui['page'], ui['db'], ui['world']
    login(ui)
    p.goto(BASE + '/plans')
    p.get_by_role('textbox', name='关键词').fill(w['plan_code'])
    p.get_by_role('button', name='筛选', exact=True).click()
    p.get_by_role('button', name=w['plan_code'], exact=True).first.click()
    capture(ui, 'plan-detail-run-entry')

    p.get_by_role('button', name='选样品并创建执行', exact=True).click()
    p.wait_for_url(re.compile(r'/processes\?.*create=1'))
    note = p.get_by_test_id('plan-inherit-note')
    note.wait_for()
    expect(note).to_contain_text('已从计划继承步骤与样品范围')
    drawer = p.locator('.el-drawer').filter(has_text='创建实验执行')
    expect(drawer).to_contain_text('映射计划步骤')
    run_code = f'P4RUN-{w["tag"]}'
    field(ui, drawer, '执行编码').fill(run_code)
    pick_samples(ui, w['coupon_codes'][:2])
    expect(drawer.locator('.el-tag').filter(has_text='P4C-')).to_have_count(2)
    capture(ui, 'plan-run-inherited-drawer')

    with p.expect_response(lambda r: r.url.endswith('/processes') and r.request.method == 'POST') as created:
        drawer.get_by_role('button', name='保存实验执行', exact=True).click()
    assert created.value.status == 201, created.value.text()[:400]
    pid = created.value.json()['data']['process_id']
    p.wait_for_timeout(500)

    run = locked(db, select(table('processes')).where(table('processes').c.process_code == run_code))[0]
    assert run['plan_id'] == w['plan'], run
    steps = locked(db, select(table('process_steps')).where(table('process_steps').c.process_id == pid))
    plan_steps = locked(db, select(table('experiment_plan_steps')).where(table('experiment_plan_steps').c.plan_id == w['plan']))
    assert len(steps) == 2, steps
    assert {s['plan_step_id'] for s in steps} == {s['step_id'] for s in plan_steps}, (steps, plan_steps)
    assert {s['step_name'] for s in steps} == {'自定义暴露步骤', '自定义吹扫步骤'}, steps
    print('RUN:', run['process_code'], 'plan', run['plan_id'], 'steps', [(s['step_index'], s['step_name'], s['plan_step_id']) for s in steps])

    # 第二次执行：同一计划可多次执行，历史不受后续编辑影响
    p.goto(BASE + '/plans')
    p.get_by_role('textbox', name='关键词').fill(w['plan_code'])
    p.get_by_role('button', name='筛选', exact=True).click()
    p.get_by_role('button', name=w['plan_code'], exact=True).first.click()
    p.get_by_role('button', name='选样品并创建执行', exact=True).click()
    p.get_by_test_id('plan-inherit-note').wait_for()
    drawer = p.locator('.el-drawer').filter(has_text='创建实验执行')
    second = f'P4RUN2-{w["tag"]}'
    field(ui, drawer, '执行编码').fill(second)
    pick_samples(ui, w['coupon_codes'][2:4])
    with p.expect_response(lambda r: r.url.endswith('/processes') and r.request.method == 'POST') as created2:
        drawer.get_by_role('button', name='保存实验执行', exact=True).click()
    assert created2.value.status == 201
    first_run = locked(db, select(table('processes')).where(table('processes').c.process_id == pid))[0]
    assert first_run['process_code'] == run_code and first_run['row_version'] == run['row_version'], '第二次创建改动了第一次执行'
    assert len(locked(db, select(table('processes')).where(table('processes').c.plan_id == w['plan']))) == 2
    print('SECOND RUN:', second, 'created; first run untouched')

    # 第四轮第 5 项：化学体系属于「执行」而不是「步骤」。这里真实验证执行级关联可保存，
    # 并守住 422 回归：步骤请求体不得再携带 chemistry_system_id（extra='forbid' 会拒绝）。
    system = ui['client'].post('/api/v1/chemistry-systems', headers=ui['actors']['operator']['headers'],
                               json={'system_code': f'P4EX-{w["tag"]}', 'system_name': '执行级化学体系', 'status': 'active'}).json()['data']
    p.goto(BASE + f'/processes?process_id={pid}')
    listing = ui['client'].get('/api/v1/chemistry-systems', headers=ui['actors']['operator']['headers'],
                               params={'size': 200, 'status': 'active'})
    print('CHEMISTRY PROBE:', listing.status_code, [(r['system_code'], r['status']) for r in listing.json().get('data', [])])
    seen = []
    p.on('response', lambda r: seen.append((r.request.method, r.url.split('/api/v1/')[-1], r.status)) if 'chemistry-systems' in r.url else None)
    p.get_by_role('button', name='编辑基本信息', exact=True).click()
    editor = p.locator('.el-drawer').filter(has_text='编辑实验执行')
    editor.wait_for()
    chem_select = editor.get_by_test_id('process-chemistry')
    # Element Plus 的远程/异步选项在首次渲染后可能被替换，点中旧节点不会生效，
    # 因此选中后必须核对控件文本，必要时重试，避免出现"点了但没选上"的假通过。
    for _ in range(3):
        chem_select.click()
        option = p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=system['system_code']).first
        option.wait_for(timeout=8000)
        option.wait_for()
        option.click()
        p.wait_for_timeout(400)
        if system['system_code'] in chem_select.inner_text():
            break
    assert system['system_code'] in chem_select.inner_text(), (chem_select.inner_text(), seen)
    print('CHEMISTRY SELECTED:', chem_select.inner_text()[:80])
    bodies = []
    p.on('request', lambda r: bodies.append((r.method, r.url.split('/api/v1/')[-1], r.post_data)) if r.method == 'PATCH' and '/processes/' in r.url else None)
    with p.expect_response(lambda r: r.request.method == 'PATCH' and r.url.endswith(f'/processes/{pid}')) as patched:
        editor.get_by_role('button', name='保存实验执行', exact=True).click()
    assert patched.value.status == 200, patched.value.text()[:400]
    p.wait_for_timeout(400)
    linked = locked(db, select(table('processes')).where(table('processes').c.process_id == pid))[0]
    assert linked['chemistry_system_id'] == system['system_id'], (linked.get('chemistry_system_id'), bodies)
    print('EXECUTION CHEMISTRY:', run_code, '->', system['system_code'], linked['chemistry_system_id'])
    capture(ui, 'execution-chemistry-linked')

    # 批量绑定：搜索 + 多选，证明旧的 Resource not found 不复现
    p.goto(BASE + f'/processes?process_id={pid}')
    p.get_by_test_id('batch-bind-open').wait_for()
    p.get_by_test_id('batch-bind-open').click()
    bind = p.get_by_test_id('batch-bind-dialog')
    bind.wait_for()
    pick_samples(ui, w['coupon_codes'][4:6])
    field(ui, bind, '腔体位置').fill('P4-CH-2')
    capture(ui, 'batch-bind-multi-select')
    with p.expect_response(lambda r: r.url.endswith('/samples/batch') and r.request.method == 'POST') as bound:
        bind.get_by_test_id('batch-bind-submit').click()
    assert bound.value.status == 201, bound.value.text()[:400]
    bind.wait_for(state='hidden')
    p.wait_for_timeout(400)
    links = locked(db, select(table('process_samples')).where(table('process_samples').c.process_id == pid))
    assert sorted(l['sample_id'] for l in links) == sorted(w['coupons'][:2] + w['coupons'][4:6]), links
    assert {l['chamber_position'] for l in links if l['sample_id'] in w['coupons'][4:6]} == {'P4-CH-2'}
    assert not [r for r in ui['responses'] if r[2] == 404], '界面出现 404（旧的 Resource not found）'
    print('BINDINGS:', len(links), 'samples on', run_code)
    capture(ui, 'process-detail-bindings')


# ---------------------------------------------------------------- 3. chemistry + modal discard

def test_p4_chemistry_system_and_modal_discard(ui):
    p, db, w = ui['page'], ui['db'], ui['world']
    login(ui)

    # 弹窗：有未保存修改时按 Esc 先确认，取消后保留输入
    p.goto(BASE + '/plans')
    p.get_by_role('button', name='新建实验计划', exact=True).click()
    drawer = p.locator('.el-drawer').filter(has_text='创建实验计划')
    drawer.wait_for()
    field(ui, drawer, '计划编码').fill(f'P4DISCARD-{w["tag"]}')
    p.keyboard.press('Escape')
    box = p.locator('.el-message-box').filter(has_text='输入尚未保存')
    box.wait_for()
    box.get_by_role('button', name='继续编辑', exact=True).click()
    p.wait_for_timeout(300)
    expect(drawer).to_be_visible()
    expect(field(ui, drawer, '计划编码')).to_have_value(f'P4DISCARD-{w["tag"]}')
    capture(ui, 'modal-unsaved-keep-editing')

    p.keyboard.press('Escape')
    p.locator('.el-message-box').filter(has_text='输入尚未保存').get_by_role('button', name='放弃修改', exact=True).click()
    expect(drawer).to_be_hidden()
    p.wait_for_timeout(300)

    # 无修改时点击遮罩直接关闭，不弹确认
    p.get_by_role('button', name='新建实验计划', exact=True).click()
    drawer.wait_for()
    p.locator('.el-overlay').first.click(position={'x': 6, 'y': 300})
    expect(drawer).to_be_hidden()
    assert p.locator('.el-message-box').count() == 0, '无修改时不应弹出确认框'
    print('MODAL: dirty Escape kept input, discard closed, clean mask click closed silently')

    # 自定义化学体系：体系 + 物质 + 工艺模板（含自定义步骤名与参数单位）
    p.goto(BASE + '/chemistry')
    p.get_by_test_id('chemistry-page').wait_for()
    p.get_by_role('button', name='新建体系', exact=True).click()
    dialog = p.locator('.el-dialog').filter(has_text='新建化学体系')
    dialog.wait_for()
    field(ui, dialog, '体系编码').fill(f'P4CHEM-{w["tag"]}')
    field(ui, dialog, '体系名称').fill('第四轮通用化学体系')
    with p.expect_response(lambda r: r.url.endswith('/chemistry-systems') and r.request.method == 'POST') as made:
        dialog.get_by_role('button', name='创建体系', exact=True).click()
    assert made.value.status == 201, made.value.text()[:400]
    system_id = made.value.json()['data']['system_id']
    p.get_by_role('button', name='新增物质', exact=True).wait_for()

    p.get_by_role('button', name='新增物质', exact=True).click()
    species = p.locator('.el-dialog').filter(has_text='新增物质')
    species.wait_for()
    field(ui, species, '物质编码').fill('P4SPEC')
    field(ui, species, '物质名称').fill('自定义前驱体')
    select_option(ui, field(ui, species, '角色'), '前驱体')
    field(ui, species, '默认单位').fill('sccm')
    with p.expect_response(lambda r: r.url.endswith('/species') and r.request.method == 'POST') as sp:
        species.get_by_role('button', name='保存物质', exact=True).click()
    assert sp.value.status == 201, sp.value.text()[:400]
    p.wait_for_timeout(300)

    p.get_by_role('button', name='新增工艺模板', exact=True).click()
    template = p.locator('.el-dialog').filter(has_text='新增工艺模板')
    template.wait_for()
    field(ui, template, '模板编码').fill('P4TPL')
    field(ui, template, '模板名称').fill('自定义暴露循环')
    field(ui, template, '步骤名称').fill('自定义暴露')
    select_option(ui, field(ui, template, '步骤类型'), '等待')
    field(ui, template, '循环次数').fill('4')
    capture(ui, 'chemistry-custom-template')
    with p.expect_response(lambda r: r.url.endswith('/step-templates') and r.request.method == 'POST') as tp:
        template.get_by_role('button', name='保存模板', exact=True).click()
    assert tp.value.status == 201, tp.value.text()[:400]
    p.wait_for_timeout(400)

    detail = locked(db, select(table('chemistry_systems')).where(table('chemistry_systems').c.system_id == system_id))[0]
    assert detail['system_name'] == '第四轮通用化学体系' and detail['owner_user_id'] == w['user']
    rows = locked(db, select(table('chemistry_species')).where(table('chemistry_species').c.system_id == system_id))
    assert len(rows) == 1 and rows[0]['role'] == 'precursor' and rows[0]['default_unit'] == 'sccm', rows
    tpl = locked(db, select(table('chemistry_step_templates')).where(table('chemistry_step_templates').c.system_id == system_id))
    assert len(tpl) == 1 and tpl[0]['steps'][0]['name'] == '自定义暴露' and tpl[0]['steps'][0]['kind'] == 'wait', tpl
    print('CHEMISTRY:', detail['system_code'], 'species', rows[0]['species_code'], 'template steps', tpl[0]['steps'])
    capture(ui, 'chemistry-system-detail')


# ---------------------------------------------------------------- 4. import feedback in view

def test_p4_import_feedback_stays_in_view(ui):
    p, db, w = ui['page'], ui['db'], ui['world']
    login(ui)
    p.goto(BASE + '/imports')
    p.get_by_test_id('import-files').set_input_files([
        {'name': 'P4-1.xlsx', 'mimeType': 'application/octet-stream', 'buffer': workbook()},
        {'name': 'P4-unknown.rga', 'mimeType': 'application/octet-stream', 'buffer': b'phase4 unrecognized instrument original'}])
    with p.expect_response(lambda r: '/imports/preview' in r.url and r.request.method == 'POST') as uploaded:
        p.get_by_test_id('upload-preview').click()
    assert uploaded.value.status in (200, 201), uploaded.value.text()[:400]
    job = uploaded.value.json()['data']
    p.get_by_test_id('import-job').wait_for()
    parsed = next(i for i in job['items'] if i['parse_result']['type'] == 'eoptics')
    other = next(i for i in job['items'] if i['item_id'] != parsed['item_id'])
    before = len(locked(db, select(table('measurements'))))

    # 失败反馈：动作已选但必填关联未完成 -> 错误就地出现，指明文件与原因
    p.get_by_test_id(f'select-item-{parsed["item_id"]}').check()
    p.get_by_test_id(f'action-{parsed["item_id"]}').click()
    p.get_by_role('option', name='导入正式测量', exact=True).click()
    p.wait_for_timeout(300)
    p.get_by_role('button', name='下一步：确认提交', exact=True).click()
    card = p.get_by_test_id(f'import-item-{parsed["item_id"]}')
    feedback = card.get_by_test_id(f'readiness-errors-{parsed["item_id"]}')
    expect(feedback).to_contain_text(parsed['filename'] + '：请选择样品')
    expect(feedback).to_contain_text('请选择测量阶段')
    expect(feedback).to_contain_text('请填写阶段序号')
    expect(p.get_by_test_id('import-step3-submit')).to_have_count(0)
    expect(card.get_by_role('combobox', name=parsed['filename'] + '样品', exact=True)).to_be_focused()
    box = in_view(ui, f'[data-testid="import-item-{parsed["item_id"]}"] [data-readiness-field="sample"]')
    assert not any(method == 'POST' and path.endswith('/confirm') for method, path, status in ui['responses'])
    assert len(locked(db, select(table('measurements')))) == before
    print('IMPORT STEP2 READINESS VISIBLE:', box)
    capture(ui, 'import-error-in-view')

    # Complete step-two readiness before advancing to confirmation.
    sample = card.get_by_role('combobox', name=parsed['filename'] + '样品', exact=True)
    sample.fill(w['coupon_codes'][0])
    p.wait_for_timeout(700)
    p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=w['coupon_codes'][0]).first.click()
    p.get_by_test_id('import-stage').click()
    p.get_by_role('option', name='初始', exact=True).click()
    card.get_by_label('阶段序号', exact=True).fill('0')
    expect(card.get_by_role('combobox', name=parsed['filename'] + '执行', exact=True)).to_be_enabled()
    p.get_by_test_id(f'units-{parsed["item_id"]}').check()
    p.get_by_test_id(f'associations-{parsed["item_id"]}').check()
    p.get_by_test_id(f'select-item-{other["item_id"]}').check()
    p.get_by_test_id(f'action-{other["item_id"]}').click()
    p.get_by_role('option', name='仅保存原件', exact=True).click()
    p.wait_for_timeout(300)

    with p.expect_response(lambda r: r.url.endswith('/confirm') and r.request.method == 'POST') as confirmed:
        p.get_by_role('button', name='下一步：确认提交', exact=True).click()
        p.get_by_test_id('import-step3-submit').click()
        p.locator('.el-message-box').get_by_role('button', name='确认所选并提交', exact=True).click()
    assert confirmed.value.status == 200, confirmed.value.text()[:400]
    p.get_by_test_id('confirm-results').wait_for()
    banner = p.get_by_test_id('import-result-banner')
    banner.wait_for()
    expect(banner).to_contain_text('已处理 2 个文件')
    in_view(ui, '[data-testid="import-result-banner"]')
    after = len(locked(db, select(table('measurements'))))
    assert after - before == len(parsed['parse_result']['blocks']), (before, after)
    print('IMPORT: measurements', before, '→', after, 'success banner visible in view')
    capture(ui, 'import-success-in-view')


# ------------------------------------------------- 5. ordinary dialogs, unsaved input

def test_p4_modal_discard_guards(ui):
    """第四轮第 6 项：普通弹窗仍可点灰色遮罩或按 Esc 关闭，但有未保存输入必须先确认。

    覆盖本轮新增/加固的四个弹窗：批量创建小样、新建化学体系、新增工艺模板、修改密码。
    """
    p, db, w = ui['page'], ui['db'], ui['world']
    login(ui)

    # 批量创建小样：Esc 关闭前确认，取消后输入保留，遮罩关闭同样确认
    p.goto(BASE + '/batches')
    p.get_by_role('textbox', name='关键词').fill(w['batch_code'])
    p.get_by_role('button', name='查询', exact=True).click()
    p.get_by_role('button', name=w['batch_code'], exact=True).first.click()
    p.get_by_test_id('batch-create-open').wait_for()
    p.get_by_test_id('batch-create-open').click()
    dialog = p.get_by_test_id('batch-create-dialog')
    dialog.wait_for()
    prefix = field(ui, dialog, '编号前缀')
    prefix.fill(f'P4GUARD-{w["tag"]}-')
    p.keyboard.press('Escape')
    box = p.locator('.el-message-box').filter(has_text='未保存的修改')
    box.wait_for()
    box.get_by_role('button', name='继续编辑', exact=True).click()
    p.wait_for_timeout(250)
    expect(dialog).to_be_visible()
    expect(prefix).to_have_value(f'P4GUARD-{w["tag"]}-')
    capture(ui, 'modal-batch-create-keep-editing')

    p.locator('.el-overlay-dialog').first.click(position={'x': 12, 'y': 12})
    box = p.locator('.el-message-box').filter(has_text='未保存的修改')
    box.wait_for()
    box.get_by_role('button', name='放弃修改', exact=True).click()
    dialog.wait_for(state='hidden')
    p.wait_for_timeout(200)
    guarded = locked(db, select(table('samples')).where(table('samples').c.sample_code.like(f'P4GUARD-{w["tag"]}%')))
    assert guarded == [], '放弃修改后不应写入任何小样'
    print('MODAL BATCH: Esc kept input, mask click confirmed then discarded, nothing written')

    # 化学体系与工艺模板：新建体系弹窗与模板弹窗都受未保存确认保护
    code = f'P4G-{w["tag"]}'
    created = ui['client'].post('/api/v1/chemistry-systems', headers=ui['actors']['operator']['headers'],
                                json={'system_code': code, 'system_name': '弹窗保护验证体系', 'status': 'active'})
    assert created.status_code == 201, created.text[:400]

    p.goto(BASE + '/chemistry')
    p.get_by_test_id('chemistry-page').wait_for()
    p.get_by_label('搜索化学体系').fill(code)
    p.get_by_role('button', name='查询', exact=True).click()
    p.get_by_role('button', name=code, exact=True).click()
    p.get_by_role('button', name='新增工艺模板', exact=True).wait_for()

    p.get_by_role('button', name='新建体系', exact=True).click()
    create = p.locator('.el-dialog').filter(has_text='新建化学体系')
    create.wait_for()
    field(ui, create, '体系编码').fill('P4GUARDCHEM')
    p.keyboard.press('Escape')
    box = p.locator('.el-message-box').filter(has_text='未保存的修改')
    box.wait_for()
    box.get_by_role('button', name='放弃修改', exact=True).click()
    create.wait_for(state='hidden')
    p.wait_for_timeout(200)
    assert locked(db, select(table('chemistry_systems')).where(table('chemistry_systems').c.system_code == 'P4GUARDCHEM')) == []

    p.get_by_role('button', name='新增工艺模板', exact=True).click()
    template = p.locator('.el-dialog').filter(has_text='新增工艺模板')
    template.wait_for()
    field(ui, template, '模板编码').fill('P4GUARDTPL')
    p.keyboard.press('Escape')
    box = p.locator('.el-message-box').filter(has_text='未保存的修改')
    box.wait_for()
    box.get_by_role('button', name='继续编辑', exact=True).click()
    p.wait_for_timeout(250)
    expect(field(ui, template, '模板编码')).to_have_value('P4GUARDTPL')
    template.get_by_role('button', name='取消', exact=True).click()
    box = p.locator('.el-message-box').filter(has_text='未保存的修改')
    box.wait_for()
    box.get_by_role('button', name='放弃修改', exact=True).click()
    template.wait_for(state='hidden')
    p.wait_for_timeout(200)
    assert locked(db, select(table('chemistry_step_templates')).where(table('chemistry_step_templates').c.template_code == 'P4GUARDTPL')) == []
    print('MODAL CHEMISTRY: template form Escape/cancel confirmed, nothing written')

    # 修改密码弹窗：已输入密码时关闭先确认
    p.locator('.user-menu').click()
    p.locator('.el-dropdown-menu').get_by_text('修改密码', exact=True).click()
    password = p.locator('.el-dialog').filter(has_text='修改密码')
    password.wait_for()
    password.get_by_label('当前密码').fill('TestPassword123!')
    p.keyboard.press('Escape')
    box = p.locator('.el-message-box').filter(has_text='未保存的修改')
    box.wait_for()
    box.get_by_role('button', name='继续编辑', exact=True).click()
    p.wait_for_timeout(250)
    expect(password.get_by_label('当前密码')).to_have_value('TestPassword123!')
    password.get_by_role('button', name='取消', exact=True).click()
    box = p.locator('.el-message-box').filter(has_text='未保存的修改')
    box.wait_for()
    box.get_by_role('button', name='放弃修改', exact=True).click()
    password.wait_for(state='hidden')
    assert not ui['errors'], ui['errors']
    print('MODAL PASSWORD: typed password guarded, dialog closed without saving')
