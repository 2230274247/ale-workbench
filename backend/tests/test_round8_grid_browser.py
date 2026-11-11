"""Round 8 Stage 1 real Chromium + MySQL acceptance for the unified 2D grid.

Run: ALE_BROWSER_TEST=1 python3 -m pytest tests/test_round8_grid_browser.py -q -s

The whole flow runs twice (1500px desktop and 390px narrow) against the real
Vue build served by app.main, with the standard SAVEPOINT fixture plus the
phase-4 manifest fixture that proves 43 tables and 5 production originals are
unchanged. Every write happens inside the outer rollback.
"""
import os
import threading
import time
import uuid

import pytest
from playwright.sync_api import expect, sync_playwright

from test_phase4_browser import db, client, originals_manifest, database_manifest  # noqa: F401
from test_round7_process_grid import snapshot


def snap(kind='自定义处理', value='12', unit='ms', source='Ar'):
    return {'step_type': kind, 'temperature': {'value': None, 'unit': '°C'},
            'groups': [{'name': '源', 'fields': [{'name': '名称', 'value': source, 'unit': None}]},
                       {'name': '脉冲', 'fields': [{'name': '时长', 'value': value, 'unit': unit}]},
                       {'name': '自定义', 'fields': [{'name': '信号', 'value': None, 'unit': 'arb'}]}]}
from app.config import ROOT

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8031'
SHOTS = ROOT / 'reports' / 'screenshots'


def login(page, actors):
    page.goto(BASE + '/login')
    page.get_by_label('用户名', exact=True).fill(actors['operator']['user']['username'])
    page.get_by_label('密码', exact=True).fill('TestPassword123!')
    page.get_by_role('button', name='登录工作台', exact=True).click()
    page.get_by_role('heading', name='工作台概览', exact=True).wait_for()


def api_data(client, actors, path):
    r = client.get('/api/v1' + path, headers=actors['operator']['headers'])
    assert r.status_code == 200, r.text
    return r.json()['data']


def open_grid(page):
    page.get_by_test_id('edit-process-grid').click()
    dialog = page.get_by_role('dialog', name='实际流程网格', exact=True)
    dialog.wait_for()
    return dialog


def cell(dialog, column, group, name, what='值'):
    return dialog.get_by_label(f'{column} {group} {name} {what}', exact=True)


@pytest.mark.parametrize('width,height', [(1500, 1100), (390, 844)], ids=['desktop1500', 'narrow390'])
def test_grid_is_primary_editor_templates_tab_and_reload(client, actors, db, monkeypatch, tmp_path, width, height):
    import uvicorn
    import app.main as main_module
    if os.getenv('ALE_TEST_FRONTEND'):
        (tmp_path / 'frontend').symlink_to(os.environ['ALE_TEST_FRONTEND'], target_is_directory=True)
        monkeypatch.setattr(main_module, 'ROOT', tmp_path)
    from app.main import app

    SHOTS.mkdir(parents=True, exist_ok=True)
    h = actors['operator']['headers']
    run = client.post('/api/v1/processes', headers=h, json={
        'process_code': 'R8UI-' + uuid.uuid4().hex[:10], 'process_mode': 'other',
        'steps': [{'step_index': 1, 'step_kind': '任意分类', 'step_name': '起始步骤',
                   'parameter_snapshot': snap('任意分类', '7', 'ms', 'Ar')}],
    }).json()['data']
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8031, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': width, 'height': height})
            page = context.new_page()
            page.set_default_timeout(20000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            login(page, actors)
            page.goto(BASE + f"/processes?process_id={run['process_id']}")
            page.get_by_role('heading', name=run['process_code'], exact=True).wait_for()

            # Detail view is one read-only grid, with a compact note/mapping list only.
            detail_grid = page.get_by_test_id('process-grid').first
            expect(detail_grid).to_be_visible()
            assert page.locator('.experiment-detail .parameter-editor').count() == 0
            assert page.get_by_role('button', name='添加步骤', exact=True).count() == 0
            assert page.get_by_test_id('step-summary-list').count() == 1

            dialog = open_grid(page)
            assert dialog.get_by_test_id('parameter-groups-editor').count() == 0

            # Three columns: keep the original and add two more.
            dialog.get_by_role('button', name='添加步骤列', exact=True).first.click()
            dialog.get_by_role('button', name='添加步骤列', exact=True).first.click()
            expect(dialog.get_by_label('步骤列名称', exact=True)).to_have_count(3)
            dialog.get_by_label('步骤列名称', exact=True).nth(0).fill('A 步骤')
            dialog.get_by_label('步骤列名称', exact=True).nth(1).fill('B 步骤')
            dialog.get_by_label('步骤列名称', exact=True).nth(2).fill('C 步骤')
            for i, kind in enumerate(['A 类', 'B 类', 'C 类']):
                dialog.get_by_label('步骤列分类', exact=True).nth(i).fill(kind)

            # Custom row across all columns.
            dialog.get_by_label('自定义参数行名称', exact=True).fill('信号')
            dialog.get_by_role('button', name='添加参数行', exact=True).click()
            expect(dialog.get_by_label('A 步骤 自定义 信号 值', exact=True)).to_have_count(1)

            # Values and per-cell units, including a unit change that must not convert the value.
            values = [('A 步骤', '1.5', 'ms'), ('B 步骤', '2.5', 's'), ('C 步骤', '3.5', 'µs')]
            for name, value, unit in values:
                cell(dialog, name, '脉冲', '时长', '值').fill(value)
                cell(dialog, name, '脉冲', '时长', '单位').fill(unit)
                cell(dialog, name, '自定义', '信号', '值').fill('42')
                cell(dialog, name, '自定义', '信号', '单位').fill('arb')
            cell(dialog, 'A 步骤', '脉冲', '时长', '单位').fill('ms')  # same value, new unit label only

            # Source row is free text with suggestions from existing source names, never auto-filled.
            source = cell(dialog, 'A 步骤', '源', '名称', '值')
            assert source.get_attribute('list'), 'source row must offer a datalist'
            options = dialog.locator(f"datalist#{source.get_attribute('list')} option").evaluate_all('(els)=>els.map(e=>e.value)')
            assert 'Ar' in options, options
            expect(source).to_have_value('Ar')

            # Templates: save the current column, then apply a copy to another column.
            bar = dialog.get_by_test_id('grid-template-bar')
            target = bar.get_by_label('模板目标列', exact=True)
            target.select_option(label=next(t for t in target.locator('option').all_text_contents() if t.endswith('A 步骤')))
            bar.get_by_label('模板名称', exact=True).fill('R8 UI 模板')
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/step-parameter-templates')) as saved_t:
                bar.get_by_role('button', name='另存为当前列为模板', exact=True).click()
            assert saved_t.value.status == 201, saved_t.value.text()
            template_id = saved_t.value.json()['data']['template_id']
            template_definition = saved_t.value.json()['data']['definition']
            expect(bar.get_by_label('参数模板', exact=True).locator(f'option[value="{template_id}"]')).to_have_text('R8 UI 模板')
            target.select_option(label=next(t for t in target.locator('option').all_text_contents() if t.endswith('C 步骤')))
            bar.get_by_label('参数模板', exact=True).select_option(str(template_id))
            bar.get_by_role('button', name='应用到当前列', exact=True).click()
            expect(cell(dialog, 'C 步骤', '脉冲', '时长', '值')).to_have_value('1.5')
            expect(cell(dialog, 'C 步骤', '脉冲', '时长', '单位')).to_have_value('ms')
            cell(dialog, 'C 步骤', '脉冲', '时长', '值').fill('3.5')

            # Tab order: value -> unit -> next column value, no tabindex=-1, scroll box focusable.
            assert dialog.locator('.process-grid-scroll').first.get_attribute('tabindex') == '0'
            assert dialog.locator('.matrix-cell input[tabindex="-1"]').count() == 0
            cell(dialog, 'A 步骤', '脉冲', '时长', '值').focus()
            page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.getAttribute("aria-label")') == 'A 步骤 脉冲 时长 单位'
            page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.getAttribute("aria-label")') == 'B 步骤 脉冲 时长 值'
            page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.getAttribute("aria-label")') == 'B 步骤 脉冲 时长 单位'

            if width >= 1000:
                page.screenshot(path=str(SHOTS / 'round8-grid-editor-1500.png'), full_page=True)
            with page.expect_response(lambda r: '/process-grid' in r.url and r.request.method == 'PUT') as saved:
                dialog.get_by_test_id('save-process-grid').click()
            assert saved.value.status == 200, saved.value.text()
            data = saved.value.json()['data']
            assert [s['step_name'] for s in data['steps']] == ['A 步骤', 'B 步骤', 'C 步骤']
            assert [s['parameter_snapshot']['groups'][1]['fields'][0] for s in data['steps']] == [
                {'name': '时长', 'value': '1.5', 'unit': 'ms'},
                {'name': '时长', 'value': '2.5', 'unit': 's'},
                {'name': '时长', 'value': '3.5', 'unit': 'ms'},
            ]
            assert all(s['parameter_snapshot']['groups'][-1]['fields'][0]['unit'] == 'arb' for s in data['steps'])

            # Save -> reload equality of values, units and order.
            page.reload()
            page.get_by_role('heading', name=run['process_code'], exact=True).wait_for()
            dialog = open_grid(page)
            expect(dialog.get_by_label('步骤列名称', exact=True)).to_have_count(3)
            assert dialog.get_by_label('步骤列名称', exact=True).evaluate_all('(els)=>els.map(e=>e.value)') == ['A 步骤', 'B 步骤', 'C 步骤']
            assert cell(dialog, 'A 步骤', '脉冲', '时长', '值').input_value() == '1.5'
            assert cell(dialog, 'A 步骤', '脉冲', '时长', '单位').input_value() == 'ms'
            assert cell(dialog, 'B 步骤', '脉冲', '时长', '值').input_value() == '2.5'
            assert cell(dialog, 'B 步骤', '脉冲', '时长', '单位').input_value() == 's'
            assert cell(dialog, 'C 步骤', '脉冲', '时长', '值').input_value() == '3.5'
            assert cell(dialog, 'C 步骤', '脉冲', '时长', '单位').input_value() == 'ms'
            bar = dialog.get_by_test_id('grid-template-bar')
            expect(bar.get_by_label('参数模板', exact=True).locator(f'option[value="{template_id}"]')).to_have_text('R8 UI 模板')
            stored = api_data(client, actors, f"/processes/{run['process_id']}")
            assert stored['steps'] == data['steps']
            if width >= 1000:
                page.screenshot(path=str(SHOTS / 'round8-grid-reloaded-1500.png'), full_page=True)
            else:
                page.screenshot(path=str(SHOTS / 'round8-grid-narrow-390.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'narrow layout must not overflow'
            assert not errors, errors
            print(f'ROUND8 GRID VERIFIED width={width}: 3 columns, custom row, template {template_id} apply+save, '
                  f'units preserved, tab value->unit->next value, reload equality, no JS errors')
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.parametrize('width,height', [(1500, 1100), (390, 844)], ids=['desktop1500', 'narrow390'])
def test_plan_grid_and_process_create_draft_use_same_editor(client, actors, db, monkeypatch, tmp_path, width, height):
    """Plan detail and the create-run drawer both open the same grid dialog."""
    import uvicorn
    import app.main as main_module
    if os.getenv('ALE_TEST_FRONTEND'):
        (tmp_path / 'frontend').symlink_to(os.environ['ALE_TEST_FRONTEND'], target_is_directory=True)
        monkeypatch.setattr(main_module, 'ROOT', tmp_path)
    from app.main import app

    h = actors['operator']['headers']
    plan = client.post('/api/v1/plans', headers=h, json={'plan_code': 'R8PL-' + uuid.uuid4().hex[:10], 'title': '第八轮计划网格'}).json()['data']
    steps = [{'key': f'k{i}', 'step_kind': f'分类 {i}', 'step_name': f'计划步骤 {i}', 'parameter_snapshot': snap(f'分类 {i}', str(i), 's', f'源 {i}')} for i in range(1, 4)]
    saved = client.put(f"/api/v1/plans/{plan['plan_id']}/process-grid", headers=h, json={
        'expected_row_version': plan['row_version'], 'steps': steps,
        'process_flow': {'version': 1, 'total_cycles': 5, 'children': [{'kind': 'step', 'id': f'n{i}', 'step_id': f'k{i}'} for i in range(1, 4)]},
    })
    assert saved.status_code == 200, saved.text
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8031, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': width, 'height': height})
            page = context.new_page()
            page.set_default_timeout(20000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            login(page, actors)

            # Plan detail: one read-only grid, no vertical parameter editor, no add-step button.
            page.goto(BASE + f"/plans?plan_id={plan['plan_id']}")
            page.get_by_role('heading', name=plan['plan_code'], exact=True).wait_for()
            expect(page.get_by_test_id('process-grid').first).to_be_visible()
            assert page.get_by_role('button', name='添加步骤', exact=True).count() == 0
            assert page.locator('.experiment-detail .parameter-editor').count() == 0
            dialog = page.get_by_role('dialog', name='计划流程网格', exact=True)
            page.get_by_test_id('edit-process-grid').click()
            dialog.wait_for()
            expect(dialog.get_by_label('步骤列名称', exact=True)).to_have_count(3)
            expect(dialog.get_by_label('总循环数', exact=True)).to_have_value('5')
            dialog.get_by_role('button', name='取消', exact=True).click()

            # Create-run drawer from the plan inherits the structure and clears values/repeats.
            page.get_by_role('button', name='选样品并创建执行', exact=True).click()
            drawer = page.get_by_role('dialog', name='创建实验执行', exact=True)
            drawer.wait_for()
            expect(drawer.get_by_test_id('plan-inherit-note')).to_be_visible()
            assert drawer.get_by_role('button', name='添加实际步骤', exact=True).count() == 0
            drawer.get_by_test_id('create-process-grid').click()
            create_grid = page.get_by_role('dialog', name='实际流程网格', exact=True)
            create_grid.wait_for()
            expect(create_grid.get_by_label('步骤列名称', exact=True)).to_have_count(3)
            expect(create_grid.get_by_label('总循环数', exact=True)).to_have_value('')
            for i, name in enumerate(['计划步骤 1', '计划步骤 2', '计划步骤 3']):
                expect(create_grid.get_by_label('步骤列名称', exact=True).nth(i)).to_have_value(name)
                assert cell(create_grid, name, '脉冲', '时长', '值').input_value() == ''
            create_grid.get_by_test_id('save-process-grid').click()
            create_grid.wait_for(state='hidden')
            expect(drawer.get_by_test_id('plan-inherit-note')).to_be_visible()
            # Save the run and confirm the grid structure reached the real record.
            drawer.get_by_label('执行编码', exact=True).fill('R8C-' + uuid.uuid4().hex[:8])
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/processes')) as made:
                drawer.get_by_role('button', name='保存实验执行', exact=True).click()
            assert made.value.status == 201, made.value.text()
            body = made.value.json()['data']
            assert len(body['steps']) == 3
            assert all(s['plan_step_id'] for s in body['steps'])
            assert all(f['value'] is None for s in body['steps'] for g in s['parameter_snapshot']['groups'] for f in g['fields'])
            assert body['process_flow']['total_cycles'] is None
            assert not errors, errors
            print(f'ROUND8 PLAN/CREATE VERIFIED width={width}: shared grid dialog, inherited structure, cleared values, run POST201')
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


from test_round8_nav_dashboard_browser import ui, world  # shared rollback server fixtures


@pytest.mark.parametrize('fail_first', [False, True], ids=['success', 'recover-grid-failure'])
def test_plan_create_grid_groups_rename_and_partial_recovery(ui, fail_first):
    page, actors, client = ui['page'], ui['actors'], ui['client']
    login(page, actors)
    page.goto(BASE + '/plans')
    page.get_by_role('button', name='新建实验计划', exact=True).click()
    drawer = page.get_by_role('dialog', name='创建实验计划', exact=True)
    tag = 'R8NEW-' + uuid.uuid4().hex[:8]
    drawer.get_by_label('计划编码', exact=True).fill(tag)
    drawer.get_by_label('计划标题', exact=True).fill('新建计划群组回归')
    drawer.get_by_label('备注', exact=True).fill('基本信息备注必须保留')
    drawer.get_by_test_id('create-process-grid').click()
    grid = page.get_by_role('dialog', name='计划流程网格', exact=True)
    grid.get_by_role('button', name='高级编辑', exact=True).click()
    grid.get_by_role('button', name='添加步骤列', exact=True).click()
    grid.get_by_label('步骤列名称', exact=True).fill('新建计划 A')
    grid.get_by_label('自定义参数行名称', exact=True).fill('信号')
    grid.get_by_role('button', name='添加参数行', exact=True).click()
    cell(grid, '新建计划 A', '自定义', '信号').fill('123')
    rename = grid.get_by_label('重命名自定义参数行', exact=True)
    rename.fill('重命名信号')
    rename.press('Tab')
    expect(cell(grid, '新建计划 A', '自定义', '重命名信号')).to_have_value('123')
    grid.get_by_label('总循环数', exact=True).fill('7')
    grid.get_by_role('button', name='添加嵌套组', exact=True).first.click()
    grid.get_by_label('流程组名称', exact=True).fill('组合 A')
    grid.get_by_label('组重复次数', exact=True).fill('4')
    grid.get_by_label('移动步骤到组', exact=True).select_option(label='组合 A')
    group = grid.locator('.nested-process-group').first
    group.get_by_role('button', name='复制组', exact=True).click()
    expect(grid.get_by_label('步骤列名称', exact=True)).to_have_count(2)
    expect(grid.get_by_label('组重复次数', exact=True).nth(1)).to_have_value('4')
    grid.locator('.nested-process-group').nth(1).get_by_role('button', name='移除组', exact=True).click()
    group.get_by_role('button', name='移出到上级', exact=True).click()
    expect(grid.locator('.process-grid-group[data-depth="0"] > .process-grid-scroll')).to_be_visible()
    grid.get_by_test_id('save-process-grid').click()
    grid.wait_for(state='hidden')
    calls = []
    def reject_once(route):
        if route.request.method == 'PUT' and not calls:
            calls.append(route.request.post_data_json)
            route.fulfill(status=503, content_type='application/json', body='{"error":{"message":"simulated grid outage"}}')
        else:
            route.continue_()
    if fail_first:
        page.route('**/api/v1/plans/*/process-grid', reject_once)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/plans')) as created:
        drawer.get_by_role('button', name='保存实验计划', exact=True).click()
    assert created.value.status == 201, created.value.text()
    plan = created.value.json()['data']
    if fail_first:
        grid.wait_for()
        expect(grid.locator('.el-alert').first).to_contain_text('基本信息已创建，流程保存失败')
        expect(cell(grid, '新建计划 A', '自定义', '重命名信号')).to_have_value('123')
        assert calls and calls[0]['expected_row_version'] == plan['row_version']
        grid.get_by_test_id('save-process-grid').click()
    grid.wait_for(state='hidden')
    page.get_by_role('heading', name=tag, exact=True).wait_for()
    page.wait_for_timeout(300)
    saved = api_data(client, actors, f"/plans/{plan['plan_id']}")
    assert len(saved['steps']) == 1
    assert saved['notes'] == '基本信息备注必须保留'
    assert saved['process_flow']['total_cycles'] == 7
    assert next(n for n in saved['process_flow']['children'] if n['kind'] == 'group')['repeat'] == 4
    field = next(g for g in saved['steps'][0]['parameter_snapshot']['groups'] if g['name'] == '自定义')['fields'][0]
    assert field['name'] == '重命名信号' and field['value'] == '123'
    matches = api_data(client, actors, '/plans?keyword=' + tag)
    assert len(matches) == 1, 'Recovery must not create a duplicate parent'
    page.screenshot(path=str(SHOTS / ('round8-plan-create-recovered.png' if fail_first else 'round8-plan-create.png')), full_page=True)
    assert not ui['errors']
    print(f'ROUND8 PLAN CREATE VERIFIED recovery={fail_first}: POST once, grid CAS, groups copy/delete/move, rename, notes preserved')


def test_legacy_plan_inheritance_keeps_rows_units_but_clears_actual_values(ui):
    from app.db import table
    page, actors, client, db = ui['page'], ui['actors'], ui['client'], ui['db']
    h = actors['operator']['headers']
    p = client.post('/api/v1/plans', headers=h, json={'plan_code': 'R8OLD-' + uuid.uuid4().hex[:8], 'title': '旧计划继承'}).json()['data']
    db.execute(table('experiment_plan_steps').insert().values(plan_id=p['plan_id'], step_index=1,
        step_kind='o3_purge', step_name='旧步骤', planned_parameters={'pulse_s': '2.5'},
        custom_parameters={'检测信号': {'value': '17', 'unit': 'arb', 'note': '旧说明'}}))
    login(page, actors)
    page.goto(BASE + f"/processes?create=1&plan_id={p['plan_id']}")
    drawer = page.get_by_role('dialog', name='创建实验执行', exact=True)
    drawer.get_by_test_id('create-process-grid').click()
    grid = page.get_by_role('dialog', name='实际流程网格', exact=True)
    expect(cell(grid, '旧步骤', '脉冲', '时长（原始字段 s）')).to_have_value('')
    expect(cell(grid, '旧步骤', '脉冲', '时长（原始字段 s）', '单位')).to_have_value('s')
    expect(cell(grid, '旧步骤', '历史自定义参数', '检测信号')).to_have_value('')
    expect(cell(grid, '旧步骤', '历史自定义参数', '检测信号', '单位')).to_have_value('arb')
    print('ROUND8 LEGACY INHERITANCE VERIFIED: original rows and units preserved; planned values absent from actual draft')
