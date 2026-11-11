"""P0-A real Chromium + MySQL rollback acceptance; isolated ALE_TEST_FRONTEND build."""
import os
import uuid
import pytest
from playwright.sync_api import expect
from test_round8_nav_dashboard_browser import ui, world
from test_phase4_browser import db, client
from test_round8_grid_browser import login, open_grid, api_data, cell
from app.config import ROOT

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in real browser')


def create(ui):
    response = ui['client'].post('/api/v1/processes', headers=ui['actors']['operator']['headers'], json={
        'process_code': 'P0-' + uuid.uuid4().hex[:12], 'process_mode': 'other'})
    assert response.status_code == 201, response.text
    return response.json()['data']


def save(page, grid):
    with page.expect_response(lambda r: '/process-grid' in r.url and r.request.method == 'PUT') as response:
        grid.get_by_test_id('save-process-grid').click()
    assert response.value.status == 200, response.value.text()
    grid.wait_for(state='hidden')
    return response.value.json()['data']


@pytest.mark.parametrize('width', [1500, 390])
def test_compact_blank_sparse_roundtrip_and_internal_scroll(ui, width):
    page = ui['page']; page.set_viewport_size({'width': width, 'height': 1000})
    run = create(ui)
    login(page, ui['actors'])
    page.goto(f"http://127.0.0.1:8031/processes?process_id={run['process_id']}")
    grid = open_grid(page)
    matrix = grid.get_by_test_id('compact-process-matrix')
    expect(matrix.locator('tbody tr')).to_have_count(5)
    assert matrix.locator('thead th').all_text_contents() == ['参数', '#1', '#2', '#3', '#4', '#5']
    assert matrix.locator('tbody th').all_text_contents() == ['源', '脉冲 (ms)', '吹扫 (s)', '等待 (s)', '压差 (Pa)']
    assert matrix.locator('input').count() == 25
    assert matrix.locator('input').evaluate_all('(xs)=>xs.every(x=>x.value==="" && !x.placeholder)')
    assert grid.get_by_test_id('grid-template-bar').count() == 0
    assert grid.get_by_label('步骤列名称', exact=True).count() == 0
    assert grid.get_by_role('button', name='复制列', exact=True).count() == 0
    # Merely opening and saving must not create five fictitious steps.
    empty = save(page, grid)
    assert empty['steps'] == [] and empty['process_flow']['children'] == []
    grid = open_grid(page)
    grid.get_by_label('#2 源', exact=True).fill('Ar')
    grid.get_by_label('#2 脉冲 (ms)', exact=True).fill('12.5')
    grid.get_by_label('#5 吹扫 (s)', exact=True).fill('2.500')
    grid.get_by_label('#5 等待 (s)', exact=True).fill('0')
    grid.get_by_label('#5 压差 (Pa)', exact=True).fill('45')
    grid.get_by_label('总循环数', exact=True).fill('7')
    scroll = grid.get_by_test_id('compact-grid-scroll')
    metrics = scroll.evaluate('(e)=>({w:e.clientWidth,scroll:e.scrollWidth})')
    if width == 390:
        assert metrics['scroll'] > metrics['w']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    path = ROOT / 'reports' / f'product-p0-matrix-{width}.png'
    page.screenshot(path=str(path), full_page=True)
    data = save(page, grid)
    assert len(data['steps']) == 2
    assert [n['id'].split('-')[2] for n in data['process_flow']['children']] == ['2', '5']
    assert all(s['step_name'] is None for s in data['steps'])
    def field(step, name):
        return next(g for g in step['parameter_snapshot']['groups'] if g['name'] == name)['fields'][0]
    assert field(data['steps'][0], '脉冲') == {'name': '时长', 'value': '12.5', 'unit': 'ms'}
    assert field(data['steps'][1], '吹扫')['value'] == '2.500'
    assert field(data['steps'][1], '吹扫')['unit'] == 's'
    assert field(data['steps'][1], '等待')['value'] == '0'
    assert field(data['steps'][1], '压差')['unit'] == 'Pa'
    page.reload()
    page.get_by_role('heading', name=run['process_code'], exact=True).wait_for()
    grid = open_grid(page)
    expect(grid.get_by_label('#1 源', exact=True)).to_have_value('')
    expect(grid.get_by_label('#2 脉冲 (ms)', exact=True)).to_have_value('12.5')
    expect(grid.get_by_label('#5 吹扫 (s)', exact=True)).to_have_value('2.500')
    expect(grid.get_by_label('#5 等待 (s)', exact=True)).to_have_value('0')
    expect(grid.get_by_label('#5 压差 (Pa)', exact=True)).to_have_value('45')
    grid.get_by_role('button', name='高级编辑', exact=True).click()
    expect(grid.get_by_test_id('grid-template-bar')).to_be_visible()
    expect(grid.get_by_label('步骤列名称', exact=True)).to_have_count(2)
    expect(grid.get_by_label('other 脉冲 时长 单位', exact=True).first).to_have_value('ms')
    grid.get_by_role('button', name='右移步骤列', exact=True).first.click()
    expect(grid.get_by_role('button', name='收起高级编辑', exact=True)).to_be_disabled()
    reordered = save(page, grid)
    assert [n['id'].split('-')[2] for n in reordered['process_flow']['children']] == ['5', '2']
    grid = open_grid(page)
    assert grid.get_by_test_id('compact-process-matrix').count() == 0
    assert not ui['errors']
    print(f'P0 COMPACT VERIFIED width={width}: blank 25 cells, no fake steps, sparse #2/#5, exact units, reload, advanced, internal scroll')


def test_legacy_seconds_full_view_and_resave_preserves_original_fields(ui):
    h = ui['actors']['operator']['headers']
    response = ui['client'].post('/api/v1/processes', headers=h, json={
        'process_code': 'P0OLD-' + uuid.uuid4().hex[:12], 'process_mode': 'other',
        'steps': [{'step_index': 1, 'step_kind': 'o3_purge', 'step_name': '旧步骤',
                   'pulse_s': '2.500', 'duration_s': '9.000', 'cycles': 5,
                   'custom_parameters': {'signal': {'value': '42', 'unit': 'arb', 'note': '保留说明'}}}]})
    assert response.status_code == 201, response.text
    run = response.json()['data']; page = ui['page']
    login(page, ui['actors'])
    page.goto(f"http://127.0.0.1:8031/processes?process_id={run['process_id']}")
    grid = open_grid(page)
    assert grid.get_by_test_id('compact-process-matrix').count() == 0
    expect(cell(grid, '旧步骤', '脉冲', '时长（原始字段 s）')).to_have_value('2.500')
    expect(cell(grid, '旧步骤', '脉冲', '时长（原始字段 s）', '单位')).to_have_value('s')
    expect(cell(grid, '旧步骤', '历史自定义参数', 'signal')).to_have_value('42')
    original = run['steps'][0]['legacy_parameters']
    data = save(page, grid)
    assert data['steps'][0]['legacy_parameters'] == original
    assert data['steps'][0]['custom_parameters']['signal']['note'] == '保留说明'
    assert api_data(ui['client'], ui['actors'], f"/processes/{run['process_id']}") == data
    assert not ui['errors']
    print('P0 LEGACY VERIFIED: 2.500 seconds and all legacy fields/notes preserved without conversion')


@pytest.mark.parametrize('count,unit', [(6, 'ms'), (1, 's'), (1, 'µs')])
def test_extra_columns_and_nonstandard_units_remain_full_and_exact(ui, count, unit):
    h = ui['actors']['operator']['headers']
    snapshots = [{'step_type': 'custom', 'temperature': {'value': None, 'unit': '°C'},
                  'groups': [{'name': '脉冲', 'fields': [{'name': '时长', 'value': f'{i}.500', 'unit': unit}]}]}
                 for i in range(1, count + 1)]
    response = ui['client'].post('/api/v1/processes', headers=h, json={
        'process_code': 'P0FULL-' + uuid.uuid4().hex[:10], 'process_mode': 'other',
        'steps': [{'step_index': i + 1, 'step_kind': 'custom', 'step_name': f'步骤{i + 1}',
                   'parameter_snapshot': snap} for i, snap in enumerate(snapshots)]})
    assert response.status_code == 201, response.text
    run = response.json()['data']; page = ui['page']
    login(page, ui['actors'])
    page.goto(f"http://127.0.0.1:8031/processes?process_id={run['process_id']}")
    grid = open_grid(page)
    assert grid.get_by_test_id('compact-process-matrix').count() == 0
    expect(grid.get_by_label('步骤列名称', exact=True)).to_have_count(count)
    expect(cell(grid, f'步骤{count}', '脉冲', '时长')).to_have_value(f'{count}.500')
    expect(cell(grid, f'步骤{count}', '脉冲', '时长', '单位')).to_have_value(unit)
    data = save(page, grid)
    assert [s['parameter_snapshot'] for s in data['steps']] == snapshots
    assert not ui['errors']
    print(f'P0 FULL VIEW VERIFIED count={count} unit={unit}: no truncation or conversion, exact snapshots saved')
