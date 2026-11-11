"""Round 8 Stage 3: grouped navigation and homepage, real Chromium + MySQL rollback.

The app is served from a temporary copy whose `frontend` entry points at the
current source build, so the test never touches the shared production dist.
"""
import hashlib
import json
import os
import threading
import time
import uuid

import pytest
from playwright.sync_api import expect

from sqlalchemy import select

from app.config import ROOT
from app.db import table
from test_phase4_browser import db, client  # noqa: F401  (rollback + originals manifest fixtures)

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8031'
SHOTS = ROOT / 'reports' / 'screenshots'


def code(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:12]}'


def make_batch(db, actors, role='operator', name='第八轮导航批次'):
    return db.execute(table('batches').insert().values(
        batch_code=code('R8NB'), batch_name=name,
        owner_user_id=actors[role]['user']['user_id'])).inserted_primary_key[0]


def make_sample(db, actors, bid, role='operator'):
    return db.execute(table('samples').insert().values(
        sample_code=code('R8NS'), batch_id=bid, sample_type='coupon',
        owner_user_id=actors[role]['user']['user_id'])).inserted_primary_key[0]


def make_plan(db, actors, bid, status='draft', when='2031-01-01 10:00:00', title=None, role='operator'):
    return db.execute(table('experiment_plans').insert().values(
        plan_code=code('R8NP'), title=title or '第八轮导航计划', status=status, priority='normal',
        owner_user_id=actors[role]['user']['user_id'], batch_id=bid, updated_at=when)).inserted_primary_key[0]


def make_process(db, actors, bid=None, plan_id=None, log_status='unknown', when='2031-01-01 10:00:00', role='operator'):
    return db.execute(table('processes').insert().values(
        process_code=code('R8NR'), process_mode='other', operator_user_id=actors[role]['user']['user_id'],
        batch_id=bid, plan_id=plan_id, log_status=log_status, updated_at=when)).inserted_primary_key[0]


def make_measurement(db, sid, quality='ok', when='2031-01-01 10:00:00'):
    return db.execute(table('measurements').insert().values(
        measurement_code=code('R8NM'), sample_id=sid, stage='initial', quality_flag=quality,
        is_current=1, updated_at=when)).inserted_primary_key[0]


def make_source(db, name, status='parsed', sid=None):
    return db.execute(table('source_files').insert().values(
        file_sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(), file_name=name,
        file_role='instrument_raw', parse_status=status, sample_id=sid)).inserted_primary_key[0]


def make_job(db, actors, when='2031-01-01 10:00:00'):
    job = db.execute(table('import_jobs').insert().values(
        owner_user_id=actors['operator']['user']['user_id'], created_at=when)).inserted_primary_key[0]
    db.execute(table('import_items').insert().values(
        job_id=job, filename=f'{code("f")}.xlsx', sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        storage_key=code('k'), status='pending', parse_result={'status': 'parsed'}))
    return job


@pytest.fixture
def world(db, actors):
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    plan = make_plan(db, actors, bid, 'draft', '2031-02-01 10:00:00', '首页真实计划')
    run = make_process(db, actors, bid, None, 'unknown', '2031-02-02 10:00:00')
    measure = make_measurement(db, sid, 'suspect', '2031-02-03 10:00:00')
    source = make_source(db, '第八轮真实原件.xlsx', 'failed', sid)
    job = make_job(db, actors, '2031-02-04 10:00:00')
    other_bid = make_batch(db, actors, 'other', '他人导航批次')
    make_plan(db, actors, other_bid, 'draft', '2031-02-05 10:00:00', '他人首页计划', role='other')
    return dict(batch=bid, sample=sid, plan=plan, run=run, measure=measure, source=source, job=job,
                other_batch=other_bid)


@pytest.fixture
def ui(client, actors, db, world, tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import sync_playwright
    import app.main as main_module
    from app.main import app
    frontend = os.getenv('ALE_TEST_FRONTEND')
    if frontend:
        (tmp_path / 'frontend').symlink_to(frontend, target_is_directory=True)
        monkeypatch.setattr(main_module, 'ROOT', tmp_path)
    SHOTS.mkdir(parents=True, exist_ok=True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8031, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(160):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            page.set_default_timeout(12000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            state = dict(page=page, context=context, actors=actors, client=client, db=db, world=world, errors=errors)
            try:
                yield state
            finally:
                print('JS ERRORS:', errors)
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def login(page, actors, role='admin'):
    page.goto(BASE + '/login')
    page.get_by_label('用户名', exact=True).fill(actors[role]['user']['username'])
    page.get_by_label('密码', exact=True).fill('TestPassword123!')
    page.get_by_role('button', name='登录工作台', exact=True).click()
    page.get_by_role('heading', name='工作台概览', exact=True).wait_for()
    page.wait_for_load_state('networkidle')


def open_nav(page, width):
    if width == 390 and not page.locator('.sidebar').evaluate("e=>e.classList.contains('mobile-open')"):
        page.get_by_role('button', name='打开导航', exact=True).click()


def scroll_state(page):
    """Returns every element that can scroll vertically inside the sidebar."""
    return page.evaluate("""() => {
      const sidebar = document.querySelector('#workspace-sidebar')
      const out = []
      for (const el of [sidebar, ...sidebar.querySelectorAll('*')]) {
        const style = getComputedStyle(el)
        const scrollable = ['auto', 'scroll'].includes(style.overflowY) && el.scrollHeight > el.clientHeight + 1
        out.push({tag: el.tagName, cls: el.className || '', id: el.id || '', scrollable})
      }
      return {all: out, scrollable: out.filter(e => e.scrollable)}
    }""")


def test_nav_accordion_active_group_persistence_and_single_scroll(ui):
    page = ui['page']
    page.set_viewport_size({'width': 1440, 'height': 1000})
    login(page, ui['actors'])
    nav = page.locator('#workspace-nav')
    # All existing routes and admin-only items remain present.
    expected = ['/', '/batches', '/samples', '/chemistry', '/plans', '/processes', '/sample-history',
                '/imports', '/measurements', '/source-files', '/analysis', '/instruments/ellipsometry',
                '/users', '/ai-settings']
    assert set(nav.locator('a').evaluate_all('(els)=>els.map(e=>e.getAttribute("href"))')) == set(expected)
    # Homepage group is open and every other group is closed (accordion default).
    expect(nav.get_by_role('button', name='收起工作空间', exact=True)).to_have_attribute('aria-expanded', 'true')
    for group in ('材料管理', '实验管理', '数据分析', '管理设置'):
        expect(nav.get_by_role('button', name=f'展开{group}', exact=True)).to_have_attribute('aria-expanded', 'false')
        expect(nav.locator('#' + {'材料管理': 'nav-group-materials', '实验管理': 'nav-group-experiments',
                                   '数据分析': 'nav-group-analysis', '管理设置': 'nav-group-admin'}[group])).to_be_hidden()
    # Opening another group closes the previous one.
    nav.get_by_role('button', name='展开材料管理', exact=True).click()
    expect(nav.get_by_role('button', name='收起材料管理', exact=True)).to_have_attribute('aria-expanded', 'true')
    # The homepage group belongs to the current page, so it stays expanded and
    # highlighted by design; only the previously *selected* group closes.
    expect(nav.get_by_role('button', name='收起工作空间', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.locator('#nav-group-workplace')).to_be_visible()
    # Only the active page's group carries the highlight.
    assert page.locator('.nav-group.is-current').count() == 1
    assert page.locator('.nav-group.is-current').get_attribute('aria-label') == '工作空间'
    expect(nav.locator('a[href="/batches"]')).to_be_visible()
    nav.get_by_role('button', name='展开实验管理', exact=True).click()
    expect(nav.get_by_role('button', name='收起实验管理', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.get_by_role('button', name='展开材料管理', exact=True)).to_have_attribute('aria-expanded', 'false')
    expect(nav.locator('a[href="/plans"]')).to_be_visible()
    expect(nav.locator('a[href="/batches"]')).to_be_hidden()
    # Navigating into a page forces its group open, highlighted, and visible,
    # even though another group is the stored selection.
    page.goto(BASE + '/samples')
    page.wait_for_load_state('networkidle')
    expect(nav.get_by_role('button', name='收起材料管理', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.locator('a[href="/samples"]')).to_have_attribute('aria-current', 'page')
    expect(nav.locator('a[href="/samples"]')).to_be_visible()
    # Clicking the active group's header makes it the only expanded group.
    nav.get_by_role('button', name='收起材料管理', exact=True).click()
    expect(nav.get_by_role('button', name='展开实验管理', exact=True)).to_have_attribute('aria-expanded', 'false')
    expect(nav.locator('a[href="/plans"]')).to_be_hidden()
    expect(nav.locator('a[href="/samples"]')).to_be_visible()
    assert page.locator('.nav-group.is-current').count() == 1
    assert page.locator('.nav-group.is-current').locator('a[href="/samples"]').count() == 1
    # The active group is open even when another group is the stored selection.
    nav.get_by_role('button', name='展开管理设置', exact=True).click()
    expect(nav.get_by_role('button', name='收起材料管理', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.locator('a[href="/samples"]')).to_be_visible()
    # Persistence across reload: the explicit selection survives, the active group stays visible.
    page.reload()
    page.wait_for_load_state('networkidle')
    expect(nav.get_by_role('button', name='收起管理设置', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.get_by_role('button', name='收起材料管理', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.locator('a[href="/samples"]')).to_be_visible()
    # Old saved shape ({groups: {id: false}}) is tolerated and interpreted as expanded.
    key = f"ale:nav:v1:user:{ui['actors']['admin']['user']['user_id']}"
    page.evaluate('(key)=>localStorage.setItem(key, JSON.stringify({collapsed:false, groups:{materials:false, experiments:true, workplace:true, analysis:true, admin:true}}))', key)
    page.reload()
    page.wait_for_load_state('networkidle')
    expect(nav.get_by_role('button', name='收起材料管理', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.locator('a[href="/batches"]')).to_be_visible()
    # Malformed storage never blocks navigation.
    page.evaluate('(key)=>localStorage.setItem(key,"{broken")', key)
    page.reload()
    page.wait_for_load_state('networkidle')
    expect(nav.locator('a[href="/samples"]')).to_be_visible()
    # Exactly one scroll container in the sidebar at desktop height.
    page.set_viewport_size({'width': 1440, 'height': 620})
    page.wait_for_timeout(150)
    state = scroll_state(page)
    scrollable = [item for item in state['scrollable'] if item['tag'] != 'BODY']
    assert len(scrollable) == 1, scrollable
    assert 'sidebar-scroll' in scrollable[0]['cls']
    assert all(not (item['tag'] == 'NAV') for item in state['scrollable'])
    # Active item stays inside the scroll container's visible band.
    page.goto(BASE + '/ai-settings')
    page.wait_for_load_state('networkidle')
    visible = page.evaluate("""() => {
      const box = document.querySelector('.sidebar-scroll').getBoundingClientRect()
      const item = document.querySelector('#workspace-nav a[aria-current="page"]').getBoundingClientRect()
      return item.top >= box.top - 1 && item.bottom <= box.bottom + 1
    }""")
    assert visible
    page.screenshot(path=str(SHOTS / 'round8-nav-1440.png'), full_page=True)
    assert not ui['errors'], ui['errors']


def test_collapsed_rail_icons_names_and_active_visible(ui):
    page = ui['page']
    page.set_viewport_size({'width': 1440, 'height': 1000})
    login(page, ui['actors'])
    page.goto(BASE + '/samples')
    page.wait_for_load_state('networkidle')
    page.get_by_role('button', name='折叠侧边栏', exact=True).click()
    expect(page.locator('.app-shell')).to_have_class('app-shell sidebar-collapsed')
    nav = page.locator('#workspace-nav')
    # Every route is still rendered with an accessible name.
    links = nav.locator('a')
    assert links.count() == 14
    for link in links.all():
        assert link.get_attribute('aria-label')
        expect(link).to_be_visible()
    # The active item is visible and distinguishable in the rail.
    active = nav.locator('a[aria-current="page"]')
    expect(active).to_be_visible()
    expect(active).to_have_attribute('aria-label', '样品管理')
    assert active.evaluate("e => e.classList.contains('active')")
    # In the rail every group is expanded, so group headers are not rendered;
    # group boundaries stay visible as dividers and no item is hidden.
    assert nav.get_by_role('button', name='收起材料管理', exact=True).count() == 0
    expect(active).to_be_visible()
    # Rail has no horizontal scrollbar and only the single scroll container.
    assert page.evaluate("document.querySelector('.sidebar').scrollWidth <= document.querySelector('.sidebar').clientWidth + 1")
    state = scroll_state(page)
    assert len([item for item in state['scrollable'] if item['tag'] != 'BODY']) <= 1
    page.screenshot(path=str(SHOTS / 'round8-nav-rail-1440.png'), full_page=True)
    page.get_by_role('button', name='展开侧边栏', exact=True).click()
    expect(page.locator('.app-shell')).not_to_have_class('app-shell sidebar-collapsed')
    assert not ui['errors'], ui['errors']


def test_mobile_390_accordion_escape_focus_and_scroll(ui):
    page = ui['page']
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, ui['actors'])
    open_nav(page, 390)
    sidebar = page.locator('#workspace-sidebar')
    expect(sidebar).to_have_class('sidebar mobile-open')
    nav = page.locator('#workspace-nav')
    nav.get_by_role('button', name='展开实验管理', exact=True).click()
    expect(nav.get_by_role('button', name='收起实验管理', exact=True)).to_have_attribute('aria-expanded', 'true')
    # The active page's own group stays expanded alongside the explicit selection.
    expect(nav.get_by_role('button', name='收起工作空间', exact=True)).to_have_attribute('aria-expanded', 'true')
    nav.locator('a[href="/processes"]').click()
    page.wait_for_url(BASE + '/processes')
    expect(sidebar).not_to_have_class('sidebar mobile-open')
    # Escape closes the drawer and returns focus to the trigger.
    open_nav(page, 390)
    page.keyboard.press('Escape')
    expect(sidebar).not_to_have_class('sidebar mobile-open')
    expect(page.get_by_role('button', name='打开导航', exact=True)).to_be_focused()
    # Overlay click also closes.
    open_nav(page, 390)
    page.locator('.nav-scrim').click(position={'x': 370, 'y': 120})
    expect(sidebar).not_to_have_class('sidebar mobile-open')
    # Single scroll container, no horizontal page overflow.
    open_nav(page, 390)
    state = scroll_state(page)
    scrollable = [item for item in state['scrollable'] if item['tag'] != 'BODY']
    # Never more than one scroll container; when the drawer content fits, none is scrollable.
    assert len(scrollable) <= 1, scrollable
    if scrollable:
        assert 'sidebar-scroll' in scrollable[0]['cls']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(SHOTS / 'round8-nav-390.png'), full_page=True)
    page.keyboard.press('Escape')
    assert not ui['errors'], ui['errors']


def test_user_switch_does_not_inherit_fold_state(ui):
    page = ui['page']
    page.set_viewport_size({'width': 1440, 'height': 1000})
    login(page, ui['actors'])
    nav = page.locator('#workspace-nav')
    nav.get_by_role('button', name='展开管理设置', exact=True).click()
    expect(nav.get_by_role('button', name='收起管理设置', exact=True)).to_have_attribute('aria-expanded', 'true')
    page.locator('.user-menu').hover()
    page.get_by_role('menuitem', name='退出登录').click()
    expect(page.get_by_role('button', name='登录工作台', exact=True)).to_be_visible()
    login(page, ui['actors'], 'viewer')
    nav = page.locator('#workspace-nav')
    # Viewer has no admin group and no admin/chemistry routes.
    assert nav.locator('a[href="/users"],a[href="/ai-settings"],a[href="/chemistry"]').count() == 0
    # Homepage group open by default; admin's saved selection did not leak.
    expect(nav.get_by_role('button', name='收起工作空间', exact=True)).to_have_attribute('aria-expanded', 'true')
    expect(nav.get_by_role('button', name='展开管理设置', exact=True)).to_have_count(0)
    page.goto(BASE + '/batches')
    page.wait_for_load_state('networkidle')
    # Viewer keeps own (empty) scope but the page renders without errors.
    expect(page.get_by_role('heading', name='批次管理', exact=True)).to_be_visible()
    assert not ui['errors'], ui['errors']


def test_homepage_real_counts_todo_recent_and_navigation(ui):
    page = ui['page']
    world = ui['world']
    page.set_viewport_size({'width': 1440, 'height': 1400})
    login(page, ui['actors'])
    page.wait_for_load_state('networkidle')
    # Primary action exists and points at the Stage 4 route.
    start = page.get_by_role('link', name='开始新实验', exact=True)
    expect(start).to_be_visible()
    assert start.get_attribute('href') == '/experiments/new'
    # Real counts from the API, not hardcoded numbers.
    summary = ui['client'].get('/api/v1/dashboard/summary', headers=ui['actors']['admin']['headers']).json()['data']
    stats = page.locator('.stat-card')
    assert stats.count() == 5
    for label, key in [('批次', 'batch_count'), ('样品', 'sample_count'), ('实验计划', 'plan_count'),
                       ('实验执行', 'process_count'), ('当前测量', 'measurement_count')]:
        card = stats.filter(has=page.get_by_text(label, exact=True)).first
        expect(card.locator('.stat-number')).to_have_text(f"{summary[key]:,}")
    # Todo shows real pending records with working links.
    measure_code = ui['db'].execute(select(table('measurements').c.measurement_code).where(
        table('measurements').c.measurement_id == world['measure'])).scalar()
    todo = page.locator('.todo-item')
    assert todo.count() >= 3
    plan_row = todo.filter(has_text='首页真实计划').first
    expect(plan_row).to_be_visible()
    expect(plan_row.get_by_role('link', name='处理 首页真实计划')).to_have_attribute('href', f'/plans?plan_id={world["plan"]}')
    measure_row = todo.filter(has_text='测量待复核').filter(has_text='疑似异常').first
    expect(measure_row).to_be_visible()
    measure_link = measure_row.get_by_role('link', name=f'处理 {measure_code}')
    expect(measure_link).to_have_attribute('href', f'/measurements?id={world["measure"]}')
    # Recent experiments: plan + run from fixtures, with one-click continue.
    experiments = page.locator('section[aria-labelledby="recent-experiments-title"] .record-item')
    assert experiments.count() >= 2
    plan_item = experiments.filter(has_text='首页真实计划').first
    continue_href = plan_item.get_by_role('link', name='发起执行').get_attribute('href')
    assert continue_href.startswith(f'/processes?create=1&plan_id={world["plan"]}')
    assert f'batch_id={world["batch"]}' in continue_href
    # Recent data: failed source file carries a real quality hint.
    data_items = page.locator('section[aria-labelledby="recent-data-title"] .record-item')
    source_item = data_items.filter(has_text='第八轮真实原件.xlsx').first
    expect(source_item).to_be_visible()
    expect(source_item.locator('.record-hint')).to_contain_text('解析失败')
    page.screenshot(path=str(SHOTS / 'round8-home-1440.png'), full_page=True)
    # One-click continue navigates.
    plan_item.get_by_role('link', name='发起执行').click()
    page.wait_for_url(BASE + f"/processes?create=1&plan_id={world['plan']}*")
    expect(page.locator('.el-drawer:not(.ai-drawer):visible')).to_be_visible()
    page.keyboard.press('Escape')
    # Stat cards navigate to their lists.
    page.goto(BASE + '/')
    page.wait_for_load_state('networkidle')
    page.locator('.stat-card').filter(has=page.get_by_text('实验执行', exact=True)).first.click()
    page.wait_for_url(BASE + '/processes')
    expect(page.get_by_role('heading', name='实验执行', exact=True)).to_be_visible()
    assert not ui['errors'], ui['errors']


def test_homepage_empty_state_and_partial_failure(ui):
    page = ui['page']
    page.set_viewport_size({'width': 1440, 'height': 1000})
    login(page, ui['actors'], 'viewer')
    page.wait_for_load_state('networkidle')
    # Viewer has no records: empty state explains there is nothing pending.
    expect(page.get_by_text('今天没有待办', exact=True)).to_be_visible()
    expect(page.get_by_text('还没有数据记录', exact=True)).to_be_visible()
    # A failing endpoint must not blank the other sections.
    page.route('**/api/v1/dashboard/todo*', lambda route: route.fulfill(status=503, content_type='application/json',
              body=json.dumps({'code': 5003, 'message': 'Database is temporarily unavailable', 'data': None,
                               'request_id': 'r8', 'timestamp': '2031-01-01T00:00:00+00:00'})))
    page.reload()
    page.wait_for_load_state('networkidle')
    expect(page.get_by_text('待办加载失败', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='重试待办', exact=True)).to_be_visible()
    expect(page.get_by_role('heading', name='科研统计概览', exact=True)).to_be_visible()
    expect(page.locator('.stat-card').first).to_be_visible()
    # Retry after removing the fault recovers without a reload.
    page.unroute('**/api/v1/dashboard/todo*')
    page.get_by_role('button', name='重试待办', exact=True).click()
    expect(page.get_by_text('待办加载失败', exact=True)).to_be_hidden()
    expect(page.get_by_text('今天没有待办', exact=True)).to_be_visible()
    assert not ui['errors'], ui['errors']


def test_homepage_mobile_390(ui):
    page = ui['page']
    page.set_viewport_size({'width': 390, 'height': 844})
    login(page, ui['actors'])
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('link', name='开始新实验', exact=True)).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(SHOTS / 'round8-home-390.png'), full_page=True)
    assert not ui['errors'], ui['errors']
