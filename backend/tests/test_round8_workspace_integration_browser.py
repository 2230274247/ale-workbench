"""Workspace integration against current isolated build, real Chromium and MySQL.
All requests use SAVEPOINTs in an outer rollback; DB/original manifests verified.
ALE_BROWSER_TEST=1 ALE_TEST_FRONTEND=<isolated frontend> pytest this_file -v -s
"""
import json
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright
from test_phase4_browser import db, client  # rollback and production originals manifest
from test_phase5_sample_void import call, fresh
from test_round8_lifecycle import create
from test_round8_grid_browser import snap

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in real browser')
BASE = 'http://127.0.0.1:8041'


@pytest.fixture
def ui(client, actors, db, monkeypatch, tmp_path):
    import uvicorn
    import app.main as main
    frontend = os.environ['ALE_TEST_FRONTEND']
    (tmp_path / 'frontend').symlink_to(frontend, target_is_directory=True)
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    server = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=8041, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1500, 'height': 1000})
            page = context.new_page()
            page.set_default_timeout(15000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(BASE + '/login')
            page.get_by_label('用户名', exact=True).fill(actors['operator']['user']['username'])
            page.get_by_label('密码', exact=True).fill('TestPassword123!')
            page.get_by_role('button', name='登录工作台', exact=True).click()
            page.get_by_role('heading', name='工作台概览', exact=True).wait_for()
            yield dict(page=page, client=client, actors=actors, db=db, errors=errors)
            print('JS ERRORS:', errors)
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def get(ui, path):
    return call(ui['client'], ui['actors'], 'get', path)


def visit(ui, kind, row):
    p = ui['page']
    key = 'plan_id' if kind == 'plans' else 'process_id'
    p.goto(f'{BASE}/{kind}?{key}={row[key]}')
    p.get_by_role('heading', name=row['plan_code' if kind == 'plans' else 'process_code'], exact=True).wait_for()
    expect(p.get_by_test_id('detail-workflow').locator('button')).to_have_count(8)


def fixture_record(ui, kind):
    c, a = ui['client'], ui['actors']
    row = create(c, a, kind)
    key = 'plan_id' if kind == 'plans' else 'process_id'
    ident = row[key]
    notes = 'integration notes\n保留换行、单位 μm 与空值'
    row = call(c, a, 'patch', f'/{kind}/{ident}', {'expected_row_version': row['row_version'], 'notes': notes, **({'objective': '已保存研究目标'} if kind == 'plans' else {})})
    row = call(c, a, 'put', f'/{kind}/{ident}/process-grid', {
        'expected_row_version': row['row_version'],
        'steps': [{'key': 'one', 'step_kind': '自定义', 'step_name': '保留步骤', 'parameter_snapshot': snap()}],
        'process_flow': {'version': 1, 'total_cycles': None, 'children': [{'kind': 'step', 'id': 'node-one', 'step_id': 'one', 'children': []}]}})
    from app.db import table
    t = table('experiment_plan_steps' if kind == 'plans' else 'process_steps')
    with ui['db'].info['browser_lock']:
        ui['db'].execute(t.update().where(t.c.step_id == row['steps'][0]['step_id']).values(step_note='保留步骤备注\n第二行'))
    row = get(ui, f'/{kind}/{ident}')
    if kind == 'processes':
        sample = fresh(c, a)
        call(c, a, 'post', f'/{kind}/{ident}/samples/batch', {'sample_ids': [sample['sample_id']], 'sample_role_note': '保留样品角色备注'}, status=201)
        row = get(ui, f'/{kind}/{ident}')
    return row


@pytest.mark.parametrize('width', [1500, 390])
@pytest.mark.parametrize('kind', ['plans', 'processes'])
def test_archive_cancel_apply_restore_void_filter_and_notes(ui, width, kind):
    p = ui['page']; p.set_viewport_size({'width': width, 'height': 1000})
    row = fixture_record(ui, kind)
    key = 'plan_id' if kind == 'plans' else 'process_id'
    path = f'/{kind}/{row[key]}'
    before = get(ui, path)
    visit(ui, kind, row)
    posts = []
    p.on('request', lambda r: posts.append(r.post_data_json) if r.method == 'POST' and '/lifecycle/' in r.url else None)
    p.get_by_test_id('lifecycle-open').click()
    d = p.get_by_test_id('lifecycle-dialog')
    expect(d.get_by_test_id('lifecycle-action-archive')).to_be_visible()
    d.get_by_test_id('lifecycle-submit').click()
    p.locator('.el-message-box').get_by_role('button', name='取消', exact=True).click()
    assert posts == []
    assert get(ui, path) == before
    d.get_by_role('button', name='取消', exact=True).click()
    expect(d).not_to_be_visible()
    p.get_by_test_id('lifecycle-open').click()
    d.get_by_test_id('lifecycle-submit').click()
    p.locator('.el-message-box').get_by_role('button', name='确认归档', exact=True).click()
    expect(d).not_to_be_visible()
    expect(p.locator('.detail-title')).to_contain_text('已归档')
    archived = get(ui, path)
    assert archived['status'] == 'archived' if kind == 'plans' else archived['archived_at']
    for field in ['notes', 'steps', 'process_flow', 'samples' if kind == 'processes' else 'processes']:
        assert archived[field] == before[field], field
    assert posts[0]['preview_token'] and posts[0]['expected_row_version'] == before['row_version']
    p.get_by_test_id('lifecycle-open').click()
    expect(d.get_by_test_id('lifecycle-action-restore')).to_be_visible()
    d.get_by_test_id('lifecycle-submit').click()
    p.locator('.el-message-box').get_by_role('button', name='确认恢复', exact=True).click()
    expect(d).not_to_be_visible()
    restored = get(ui, path)
    for field in ['notes', 'steps', 'process_flow']:
        assert restored[field] == before[field], field
    # Void is correctly unavailable with step dependencies; use an empty row for filter coverage.
    void_row = create(ui['client'], ui['actors'], kind)
    visit(ui, kind, void_row)
    p.get_by_test_id('lifecycle-open').click()
    d.get_by_test_id('lifecycle-action-void').click()
    d.locator('textarea').fill('integration rollback only')
    d.get_by_test_id('lifecycle-submit').click()
    p.locator('.el-message-box').get_by_role('button', name='确认作废', exact=True).click()
    expect(d).not_to_be_visible()
    expect(p.get_by_test_id('detail-voided-badge')).to_be_visible()
    p.get_by_label('关键词', exact=True).fill(void_row['plan_code' if kind == 'plans' else 'process_code'])
    p.get_by_role('button', name='筛选', exact=True).click()
    expect(p.locator('.el-table__body-wrapper .el-table__row')).to_have_count(0)
    with p.expect_response(lambda r: f'/api/v1/{kind}?' in r.url and 'include_voided=true' in r.url):
        p.get_by_test_id('include-voided').check()
    expect(p.locator('.el-table__body-wrapper .el-table__row')).to_have_count(1)
    assert get(ui, path)['notes'] == before['notes']
    p.screenshot(path=str(Path(os.environ['ALE_INTEGRATION_EVIDENCE']) / f'{kind}-lifecycle-{width}.png'), full_page=True)
    print(f'PASS {kind} {width}: archive preview cancel/no write, apply/token, restore, void filter, steps/notes/bindings unchanged')


@pytest.mark.parametrize('width', [1500, 390])
@pytest.mark.parametrize('kind', ['plans', 'processes'])
def test_workflow_states_all_node_urls_and_continue(ui, width, kind):
    p = ui['page']; p.set_viewport_size({'width': width, 'height': 1000})
    row = fixture_record(ui, kind)
    key = 'plan_id' if kind == 'plans' else 'process_id'
    before = get(ui, f'/{kind}/{row[key]}')
    expected = get(ui, f'/workflow/state?{key}={row[key]}')['stages']
    names = ['研究目标', '选择计划', '工艺矩阵', '参与样品', '执行记录', '实际参数', '测量与分析']
    for stage, name in enumerate(names):
        visit(ui, kind, row)
        buttons = p.get_by_test_id('detail-workflow').locator('nav button')
        for i, fact in enumerate(expected):
            assert ('saved' in (buttons.nth(i).get_attribute('class') or '')) == (fact['status'] == 'saved')
        buttons.nth(stage).click()
        p.wait_for_url('**/experiments/new?**')
        q = parse_qs(urlparse(p.url).query)
        assert q == {key: [str(row[key])], 'stage': [str(stage)]}
        p.get_by_role('heading', name='开始新实验', exact=True).wait_for()
        expect(p.locator('.wizard-stage h2')).to_have_text(('计划工艺矩阵' if kind == 'plans' else '独立执行工艺矩阵') if stage == 2 else name)
        print(f'NODE {kind} {width} {name}: {p.url}')
    visit(ui, kind, row)
    p.get_by_test_id('workflow-continue').click()
    p.wait_for_url('**/experiments/new?**')
    missing = next((i for i, s in enumerate(expected) if s['status'] != 'saved'), 0)
    assert parse_qs(urlparse(p.url).query)['stage'] == [str(missing)]
    assert get(ui, f'/{kind}/{row[key]}') == before
    print(f'PASS {kind} {width}: backend states={json.dumps(expected)}, seven URLs + continue, record untouched')


@pytest.mark.parametrize('kind', ['plans', 'processes'])
def test_destination_honors_requested_stage(ui, kind):
    row = create(ui['client'], ui['actors'], kind)
    visit(ui, kind, row)
    ui['page'].get_by_test_id('detail-workflow').locator('nav button').nth(3).click()
    ui['page'].wait_for_url('**/experiments/new?**')
    expect(ui['page'].locator('.wizard-stage h2')).to_have_text('参与样品', timeout=1500)


@pytest.mark.parametrize('kind', ['plans', 'processes'])
def test_delete_is_preview_only_and_clears_detail(ui, kind):
    row = create(ui['client'], ui['actors'], kind)
    key = 'plan_id' if kind == 'plans' else 'process_id'
    p = ui['page']
    # Permanent deletion is admin-only according to the preview contract.
    p.context.clear_cookies()
    p.goto(BASE + '/login')
    p.get_by_label('用户名', exact=True).fill(ui['actors']['admin']['user']['username'])
    p.get_by_label('密码', exact=True).fill('TestPassword123!')
    p.get_by_role('button', name='登录工作台', exact=True).click()
    p.get_by_role('heading', name='工作台概览', exact=True).wait_for()
    visit(ui, kind, row)
    requests = []
    p.on('request', lambda r: requests.append((r.method, r.url)) if r.method in ('DELETE', 'POST') and '/api/v1/' in r.url else None)
    p.get_by_test_id('lifecycle-open').click()
    d = p.get_by_test_id('lifecycle-dialog')
    d.get_by_test_id('lifecycle-action-delete').click()
    d.get_by_test_id('lifecycle-submit').click()
    p.locator('.el-message-box').get_by_role('button', name='取消', exact=True).click()
    assert not requests
    assert get(ui, f'/{kind}/{row[key]}')[key] == row[key]
    d.get_by_test_id('lifecycle-submit').click()
    p.locator('.el-message-box').get_by_role('button', name='确认删除', exact=True).click()
    expect(d).not_to_be_visible()
    expect(p.locator('.experiment-detail')).to_have_count(0)
    assert len(requests) == 1 and requests[0] == ('POST', f'{BASE}/api/v1/lifecycle/{kind}/{row[key]}/apply')
    call(ui['client'], ui['actors'], 'get', f'/{kind}/{row[key]}', status=404)
    print(f'PASS {kind}: delete cancel is read-only; confirmed deletion uses preview apply; detail cleared')


@pytest.mark.parametrize('query', ['', '&stage=-1', '&stage=7', '&stage=1.5', '&stage=invalid', '&stage=3&stage=4'])
def test_invalid_stage_is_safe_and_read_only(ui, query):
    row = create(ui['client'], ui['actors'], 'plans')
    path = f"/plans/{row['plan_id']}"
    before = get(ui, path)
    p = ui['page']
    p.goto(f"{BASE}/experiments/new?plan_id={row['plan_id']}{query}")
    expect(p.locator('.wizard-stage h2')).to_have_text('研究目标')
    assert get(ui, path) == before


def test_stage_query_watch_preserves_draft_and_saved_facts(ui):
    row = create(ui['client'], ui['actors'], 'plans')
    p = ui['page']
    p.goto(f"{BASE}/experiments/new?plan_id={row['plan_id']}&stage=0")
    p.get_by_label('研究目标', exact=True).fill('仅本地草稿')
    # Vue Router navigation within the mounted view, including its draft guard.
    def route(stage):
        p.evaluate("""stage => {
          const router = document.querySelector('#app').__vue_app__.config.globalProperties.$router;
          void router.replace({path:'/experiments/new',query:{...router.currentRoute.value.query,stage}});
        }""", stage)
        p.locator('.el-message-box').get_by_role('button', name='放弃修改', exact=True).click()
    route('3')
    expect(p.locator('.wizard-stage h2')).to_have_text('参与样品')
    route('bad')
    expect(p.locator('.wizard-stage h2')).to_have_text('研究目标')
    expect(p.get_by_label('研究目标', exact=True)).to_have_value('仅本地草稿')
    assert get(ui, f"/workflow/state?plan_id={row['plan_id']}")['stages'][0]['status'] == 'empty'
