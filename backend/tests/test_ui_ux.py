"""Extra opt-in UI acceptance; all real API writes use conftest's rollback DB.

Run: ALE_BROWSER_TEST=1 /tmp/ale-repair314/bin/python -m pytest tests/test_ui_ux.py -v
Only 503 failure injection is mocked. Existing database records are never edited.
"""
import os
import threading
import time
import uuid
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8012'
VIEWPORTS = [(1440, 1000), (1366, 768), (1920, 1080), (1024, 768), (390, 844)]


@pytest.fixture
def ui(client, actors, db):
    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.main import app
    from app.config import ROOT

    prefix = 'UX-' + uuid.uuid4().hex[:12]
    headers = actors['operator']['headers']

    def create(kind, payload):
        response = client.post('/api/v1/' + kind, headers=headers, json=payload)
        assert response.status_code == 201, response.text
        return response.json()['data']

    batch = create('batches', {'batch_code': prefix + '-B', 'batch_name': 'UI验收批次（事务回滚）', 'nominal_thickness_nm': '47.500'})
    parent = create('samples', {'sample_code': prefix + '-P', 'batch_id': batch['batch_id'], 'sample_type': 'parent_wafer', 'nominal_thickness_nm': '47.500'})
    child = create('samples', {'sample_code': prefix + '-S', 'batch_id': batch['batch_id'], 'parent_sample_id': parent['sample_id'], 'sample_type': 'coupon', 'nominal_thickness_nm': '47.500'})
    output = ROOT / 'reports' / 'ui-ux-20261015' / 'after'
    output.mkdir(parents=True, exist_ok=True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8012, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started, 'Uvicorn could not start on port 8012'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'], env={**os.environ, 'LD_LIBRARY_PATH': '/tmp/libs/x/usr/lib/x86_64-linux-gnu'})
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                yield {'page': page, 'context': context, 'batch': batch, 'parent': parent, 'child': child,
                       'prefix': prefix, 'output': output, 'actors': actors, 'client': client, 'errors': errors}
            finally:
                if errors:
                    print('Browser page errors:', errors)
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive(), 'Uvicorn did not stop; next test cannot safely reuse 8012'


def login(ui, role='admin'):
    page = ui['page']
    page.goto(BASE + '/login')
    page.get_by_label('用户名', exact=True).fill(ui['actors'][role]['user']['username'])
    page.get_by_label('密码', exact=True).fill('TestPassword123!')
    page.get_by_role('button', name='登录工作台').click()
    page.get_by_role('heading', name='工作台概览', exact=True).wait_for()
    settle(page)


def settle(page):
    page.wait_for_function("!document.querySelector('[aria-label=\"正在加载列表\"]') && !document.querySelector('[aria-label=\"正在加载档案\"]')")
    page.wait_for_timeout(300)  # Element Plus drawer transitions/layout, not network correctness.


def visit(ui, kind):
    page = ui['page']
    page.goto(BASE + '/' + kind)
    page.get_by_role('heading', name='批次管理' if kind == 'batches' else '样品管理', exact=True).wait_for()
    settle(page)


def search(ui, keyword):
    page = ui['page']
    page.get_by_label('搜索关键词', exact=True).fill(keyword)
    with page.expect_response(lambda r: '/api/v1/' in r.url and 'keyword=' in r.url and r.request.method == 'GET') as response:
        page.get_by_role('button', name='查询', exact=True).click()
    assert response.value.status == 200
    settle(page)


def row(ui, code):
    return ui['page'].locator('.el-table__body tr').filter(has=ui['page'].get_by_role('button', name=code, exact=True))


def shot(ui, name):
    ui['page'].screenshot(path=str(ui['output'] / (name + '.png')), full_page=True)


def no_overflow(page, label):
    result = page.evaluate("""() => ({viewport: innerWidth, body: document.body.scrollWidth,
      document: document.documentElement.scrollWidth,
      offenders: [...document.querySelectorAll('body *')].filter(e => {
        const r=e.getBoundingClientRect();
        return r.width && (r.right > innerWidth + 1 || r.left < -1)
          && !e.closest('.el-table, .el-scrollbar, .sidebar, .el-popper');
      }).slice(0, 8).map(e=>({tag:e.tagName, cls:e.className, width:e.getBoundingClientRect().width}))})""")
    assert max(result['body'], result['document']) <= result['viewport'] + 1, f'{label}: body horizontal overflow: {result}'


def close_drawer(page):
    page.locator('.el-drawer:visible').get_by_role('button', name='关闭', exact=True).click()
    page.locator('.el-drawer').wait_for(state='hidden')


@pytest.mark.parametrize('width,height', VIEWPORTS, ids=[f'{w}x{h}' for w, h in VIEWPORTS])
def test_ui_ux_viewports(ui, width, height):
    """Check body widths with real rows, drawers and every requested screenshot."""
    from playwright.sync_api import expect
    page = ui['page']
    page.set_viewport_size({'width': width, 'height': height})
    login(ui)
    checks = []

    def capture(name):
        settle(page)
        shot(ui, f'{width}x{height}-{name}')
        try:
            no_overflow(page, name)
        except AssertionError as error:
            checks.append(str(error))

    capture('01-home')
    visit(ui, 'batches')
    search(ui, ui['batch']['batch_code'])
    expect(row(ui, ui['batch']['batch_code'])).to_have_count(1)
    capture('02-batches')
    page.get_by_role('button', name='新建批次', exact=True).first.click()
    page.get_by_label('批次编码', exact=True).wait_for()
    capture('03-create-batch')
    page.keyboard.press('Escape')
    page.locator('.el-drawer').wait_for(state='hidden')
    row(ui, ui['batch']['batch_code']).get_by_role('button', name='编辑', exact=True).click()
    page.get_by_label('批次名称', exact=True).wait_for()
    capture('04-edit-batch')
    page.keyboard.press('Escape')
    page.locator('.el-drawer').wait_for(state='hidden')
    visit(ui, 'samples')
    search(ui, ui['prefix'])
    expect(row(ui, ui['child']['sample_code'])).to_have_count(1)
    capture('05-samples')
    page.get_by_role('button', name=ui['child']['sample_code'], exact=True).click()
    page.locator('.detail-title h2').filter(has_text=ui['child']['sample_code']).wait_for()
    capture('06-detail-sample')
    close_drawer(page)
    page.get_by_role('button', name='新建样品', exact=True).first.click()
    page.get_by_label('样品编码', exact=True).wait_for()
    capture('07-create-sample')
    page.keyboard.press('Escape')
    page.locator('.el-drawer').wait_for(state='hidden')
    if width == 390:
        toggle = page.get_by_role('button', name='打开导航', exact=True)
        toggle.click()
        expect(page.locator('.sidebar')).to_have_class('sidebar mobile-open')
        capture('08-narrow-navigation')
        page.keyboard.press('Escape')
        expect(toggle).to_be_focused()
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        expect(page.locator('.nav-scrim')).to_have_count(0)
    assert not ui['errors'], ui['errors']
    assert not checks, '\n'.join(checks)


def test_ui_ux_workflows(ui):
    from playwright.sync_api import expect
    page = ui['page']
    login(ui)
    visit(ui, 'batches')
    search(ui, ui['batch']['batch_code'])
    writes = []
    page.on('request', lambda request: writes.append((request.method, urlparse(request.url).path)) if request.method in ('POST', 'PATCH', 'DELETE') else None)
    page.get_by_role('button', name='新建批次', exact=True).first.click()
    page.get_by_label('批次编码', exact=True).fill(ui['prefix'] + '-NEW')
    page.get_by_label('批次名称', exact=True).fill('UI抽屉创建（回滚）')
    page.get_by_label('标称厚度 / nm', exact=True).fill('47.5001')
    page.get_by_role('button', name='保存批次', exact=True).click()
    expect(page.locator('.el-form-item__error')).to_contain_text(['最多 9 位整数、3 位小数。'])
    assert not writes, f'Invalid precision caused writes: {writes}'
    shot(ui, 'workflow-precision-error')
    page.get_by_label('标称厚度 / nm', exact=True).fill('47.500')
    page.locator('.el-drawer:visible').get_by_role('button', name='取消', exact=True).click()
    page.get_by_role('button', name='继续编辑', exact=True).click()
    expect(page.get_by_label('批次编码', exact=True)).to_have_value(ui['prefix'] + '-NEW')
    # Two synchronous clicks model a repeated save before the response is received.
    with page.expect_response(lambda r: urlparse(r.url).path == '/api/v1/batches' and r.request.method == 'POST') as response:
        page.get_by_role('button', name='保存批次', exact=True).evaluate('(button) => {button.click(); button.click()}')
    assert response.value.status == 201, response.value.text()
    page.locator('.el-drawer').wait_for(state='hidden')
    settle(page)
    assert writes.count(('POST', '/api/v1/batches')) == 1, writes
    created = response.value.json()['data']
    search(ui, created['batch_code'])
    expect(row(ui, created['batch_code'])).to_have_count(1)
    # Dirty Escape: keep editing, then discard; database retains saved value.
    row(ui, created['batch_code']).get_by_role('button', name='编辑', exact=True).click()
    page.get_by_label('批次名称', exact=True).fill('未保存的修改')
    page.keyboard.press('Escape')
    page.get_by_role('button', name='继续编辑', exact=True).click()
    expect(page.get_by_label('批次名称', exact=True)).to_have_value('未保存的修改')
    page.locator('.el-drawer:visible').get_by_role('button', name='取消', exact=True).click()
    page.get_by_role('button', name='放弃修改', exact=True).click()
    page.locator('.el-drawer').wait_for(state='hidden')
    record = ui['client'].get(f"/api/v1/batches/{created['batch_id']}", headers=ui['actors']['admin']['headers']).json()['data']
    assert record['batch_name'] == created['batch_name']
    # Real edit and persistence.
    row(ui, created['batch_code']).get_by_role('button', name='编辑', exact=True).click()
    page.get_by_label('批次名称', exact=True).fill('UI已编辑（回滚）')
    shot(ui, 'workflow-edit')
    with page.expect_response(lambda r: r.request.method == 'PATCH' and r.url.endswith(f"/batches/{created['batch_id']}")) as response:
        page.get_by_role('button', name='保存批次', exact=True).click()
    assert response.value.status == 200, response.value.text()
    page.locator('.el-drawer').wait_for(state='hidden')
    expect(page.get_by_text('UI已编辑（回滚）', exact=True)).to_be_visible()
    # Batch -> child -> parent -> batch are real association links.
    search(ui, ui['batch']['batch_code'])
    page.get_by_role('button', name=ui['batch']['batch_code'], exact=True).click()
    page.locator('.el-drawer').get_by_role('button', name=ui['child']['sample_code'], exact=True).click()
    expect(page).to_have_url(f"{BASE}/samples?sample_id={ui['child']['sample_id']}&batch_id={ui['batch']['batch_id']}")
    expect(page.locator('.detail-title h2')).to_have_text(ui['child']['sample_code'])
    page.locator('.detail-grid').get_by_role('button', name='#' + str(ui['parent']['sample_id']), exact=True).click()
    expect(page.locator('.detail-title h2')).to_have_text(ui['parent']['sample_code'])
    page.locator('.detail-grid').get_by_role('button', name=ui['batch']['batch_code'], exact=True).click()
    expect(page.locator('.detail-title h2')).to_have_text(ui['batch']['batch_code'])
    close_drawer(page)
    # Cancel delete makes no request; dependency delete is a real 409.
    search(ui, ui['batch']['batch_code'])
    deletes_before = sum(method == 'DELETE' for method, _ in writes)
    row(ui, ui['batch']['batch_code']).get_by_role('button', name='删除', exact=True).click()
    page.locator('.el-message-box').get_by_role('button', name='取消', exact=True).click()
    assert sum(method == 'DELETE' for method, _ in writes) == deletes_before
    row(ui, ui['batch']['batch_code']).get_by_role('button', name='删除', exact=True).click()
    with page.expect_response(lambda r: r.request.method == 'DELETE') as response:
        page.get_by_role('button', name='确认删除', exact=True).click()
    assert response.value.status == 409, response.value.text()
    expect(page.locator('.el-message--error')).to_be_visible()
    expect(row(ui, ui['batch']['batch_code'])).to_have_count(1)
    shot(ui, 'workflow-delete-dependency')
    # A unique filter, never a global-empty assumption.
    search(ui, ui['prefix'] + '-NO-SUCH-RECORD')
    expect(page.get_by_text('暂无匹配记录', exact=True)).to_be_visible()
    shot(ui, 'workflow-filter-empty')
    page.get_by_role('button', name='清除筛选', exact=True).click()
    settle(page)
    # Exactly one injected failure; subsequent retry must return live data.
    injected = []

    def unavailable(route):
        injected.append(route.request.url)
        route.fulfill(status=503, content_type='text/plain', body='UI acceptance injected 503')

    page.route('**/api/v1/batches?*', unavailable, times=1)
    page.get_by_role('button', name='刷新列表', exact=True).click()
    expect(page.get_by_text('列表加载失败', exact=True)).to_be_visible()
    expect(page.get_by_text('服务暂时不可用，请检查服务状态后重试。', exact=True)).to_be_visible()
    shot(ui, 'workflow-503-failure')
    assert len(injected) == 1
    with page.expect_response(lambda r: '/api/v1/batches?' in r.url) as response:
        page.get_by_role('button', name='重试加载列表', exact=True).click()
    assert response.value.status == 200
    search(ui, ui['batch']['batch_code'])
    expect(row(ui, ui['batch']['batch_code'])).to_have_count(1)
    assert not ui['errors'], ui['errors']


def test_ui_ux_viewer_cannot_write(ui):
    from playwright.sync_api import expect
    page = ui['page']
    # Create as operator through real API, then demote this fixture user to viewer.
    uid = ui['actors']['operator']['user']['user_id']
    changed = ui['client'].patch(f'/api/v1/users/{uid}', headers=ui['actors']['admin']['headers'], json={'role': 'viewer'})
    assert changed.status_code == 200, changed.text
    login(ui, 'operator')
    writes = []
    page.on('request', lambda r: writes.append(r.url) if r.method in ('POST', 'PATCH', 'DELETE') and '/api/v1/auth/' not in r.url else None)
    for kind, noun, code in [('batches', '批次', ui['batch']['batch_code']), ('samples', '样品', ui['child']['sample_code'])]:
        visit(ui, kind)
        search(ui, code)
        expect(row(ui, code)).to_have_count(1)
        expect(page.get_by_role('button', name='新建' + noun, exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='编辑', exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='删除', exact=True)).to_have_count(0)
        page.get_by_role('button', name=code, exact=True).click()
        expect(page.locator('.detail-title h2')).to_have_text(code)
        expect(page.get_by_role('button', name='编辑档案', exact=True)).to_have_count(0)
        shot(ui, 'viewer-' + kind)
        close_drawer(page)
    assert not writes, writes
    # Assert server authorization as well as hidden UI actions, on fixture-owned rows only.
    denied = ui['client'].patch(f"/api/v1/batches/{ui['batch']['batch_id']}", headers=ui['actors']['viewer']['headers'], json={'batch_name': 'forbidden', 'expected_row_version': ui['batch']['row_version']})
    assert denied.status_code == 403, denied.text
    assert not ui['errors'], ui['errors']
