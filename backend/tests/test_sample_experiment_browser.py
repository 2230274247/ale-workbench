"""Real Chromium acceptance for sample↔experiment links and inline batch creation.

Runs against the independent *_test database; the parent fixture rolls back and
verifies both the database manifest and the test originals directory.
"""
import os
import threading
import time
import uuid

import pytest
from playwright.sync_api import expect

from app.config import ROOT
from app.db import table
from test_phase4_browser import db, client  # noqa: F401  (rollback + manifests)

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8033'
PASSWORD = 'TestPassword123!'
SHOTS = ROOT / 'reports' / 'screenshots'


def seed_batch(db, actors, tag='SLUI'):
    uid = actors['operator']['user']['user_id']
    code = f'{tag}B-{uuid.uuid4().hex[:8]}'
    bid = db.execute(table('batches').insert().values(
        batch_code=code, batch_name='浏览器验收批次', owner_user_id=uid)).inserted_primary_key[0]
    return bid, code


def seed_sample(db, actors, bid, label):
    uid = actors['operator']['user']['user_id']
    code = f'SLUI-{label}-{uuid.uuid4().hex[:6]}'
    sid = db.execute(table('samples').insert().values(
        sample_code=code, batch_id=bid, sample_type='coupon',
        status='available', owner_user_id=uid)).inserted_primary_key[0]
    return sid, code


def seed_process(db, actors, bid, code=None, cycles=None):
    uid = actors['operator']['user']['user_id']
    code = code or f'SLUIP-{uuid.uuid4().hex[:8]}'
    pid = db.execute(table('processes').insert().values(
        process_code=code, process_mode='other', operator_user_id=uid,
        batch_id=bid, log_status='unknown', full_ale_cycles=cycles)).inserted_primary_key[0]
    return pid, code


@pytest.fixture
def ui(client, db, actors, tmp_path, monkeypatch):
    import uvicorn
    from playwright.sync_api import sync_playwright
    import app.main as main_module
    from contextlib import contextmanager
    import app.ai as ai_module

    @contextmanager
    def same_transaction():
        with db.begin_nested():
            yield db
    monkeypatch.setattr(ai_module, 'ai_transaction', same_transaction)
    frontend = os.getenv('ALE_TEST_FRONTEND')
    if frontend:
        (tmp_path / 'frontend').symlink_to(frontend, target_is_directory=True)
        monkeypatch.setattr(main_module, 'ROOT', tmp_path)
    SHOTS.mkdir(parents=True, exist_ok=True)
    server = uvicorn.Server(uvicorn.Config(app=main_module.app, host='127.0.0.1', port=8033,
                                           log_level='error', access_log=False))
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
            page.set_default_timeout(15000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            try:
                yield page, errors
            finally:
                print('JS ERRORS:', errors)
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def login(page, actors):
    from app.security import limiter
    limiter.entries.clear()
    page.goto(BASE + '/login')
    page.get_by_label('用户名', exact=True).fill(actors['operator']['user']['username'])
    page.get_by_label('密码', exact=True).fill(PASSWORD)
    page.get_by_role('button', name='登录工作台', exact=True).click()
    page.get_by_role('heading', name='工作台概览', exact=True).wait_for()


def test_inline_batch_and_sample_code_edit(ui, actors, db):
    page, errors = ui
    login(page, actors)
    page.goto(BASE + '/samples')
    page.get_by_role('button', name='新建样品').first.click()
    page.get_by_placeholder('例如 B01-S01').fill('UI-SAMPLE-001')
    page.get_by_test_id('inline-batch-open').click()
    page.wait_for_timeout(600)
    print('DIALOGS', page.locator('.el-dialog').count(), page.locator('[role=dialog]').count())
    print('VISIBLE TEXT', page.locator('body').inner_text()[-500:])
    dialog = page.locator('.el-dialog').filter(has_text='新建批次').last
    expect(dialog).to_be_visible()
    dialog.get_by_placeholder('例如 B01').fill('UIB-' + uuid.uuid4().hex[:6])
    dialog.get_by_placeholder('例如 2026-10 沉积批次').fill('浏览器内联批次')
    dialog.get_by_role('button', name='创建并选中', exact=True).click()
    expect(dialog).to_be_hidden()
    # The sample form stayed open and kept its code; the new batch is selected.
    expect(page.get_by_placeholder('例如 B01-S01')).to_have_value('UI-SAMPLE-001')
    expect(page.locator('.records-inline-row')).to_contain_text('UIB-')
    page.get_by_role('button', name='保存样品', exact=True).click()
    expect(page.get_by_text('UI-SAMPLE-001').first).to_be_visible()
    page.screenshot(path=str(SHOTS / 'sample-inline-batch.png'), full_page=True)
    assert errors == []


def test_bidirectional_navigation_and_five_sample_nodes(ui, actors, db):
    page, errors = ui
    bid, batch_code = seed_batch(db, actors)
    samples = [seed_sample(db, actors, bid, str(index)) for index in range(5)]
    pid, process_code = seed_process(db, actors, bid, cycles=500)
    steps = []
    for index in range(1, 6):
        steps.append(db.execute(table('process_steps').insert().values(
            process_id=pid, step_index=index, step_kind='wait')).inserted_primary_key[0])
    for index, (sid, code) in enumerate(samples):
        db.execute(table('process_samples').insert().values(
            process_id=pid, sample_id=sid, full_ale_cycles=(index + 1) * 100,
            chamber_position=f'P{index + 1}', is_control=0))
        for kind in ('load', 'unload'):
            db.execute(table('sample_transitions').insert().values(
                sample_id=sid, to_status='in_process' if kind == 'load' else 'available',
                event_type=kind, process_id=pid, step_id=steps[index]))
        db.execute(table('measurements').insert().values(
            measurement_code='SLUIM-' + uuid.uuid4().hex[:8], sample_id=sid, process_id=pid,
            stage='after_ale', is_current=1, thickness_mean_nm=str(10 + index)))
    login(page, actors)
    page.goto(BASE + f'/processes?process_id={pid}')
    page.get_by_role('heading', name=process_code).wait_for()
    for index, (sid, code) in enumerate(samples):
        article = page.locator('.experiment-step').filter(has_text=code)
        expect(article).to_contain_text('本次循环')
        expect(article).to_contain_text(str((index + 1) * 100))
        expect(article).to_contain_text(f'步骤 {index + 1}')
    page.screenshot(path=str(SHOTS / 'five-sample-nodes.png'), full_page=True)
    # Experiment → sample detail → back to the same experiment.
    first_code = samples[2][1]
    page.locator('.experiment-step').filter(has_text=first_code).get_by_role('button', name='查看样品详情', exact=True).click()
    page.wait_for_url(f'**/samples?sample_id=*')
    page.get_by_role('heading', name=first_code).wait_for()
    expect(page.get_by_test_id('sample-experiments')).to_contain_text(process_code)
    expect(page.get_by_test_id('sample-participation-summary')).to_contain_text('已记录累计 300 cycles')
    page.get_by_role('button', name='打开实验', exact=True).first.click()
    page.wait_for_url(f'**/processes?process_id={pid}')
    page.get_by_role('heading', name=process_code).wait_for()
    assert errors == []


def test_sample_rename_and_unused_draft_cleanup(ui, actors, db):
    page, errors = ui
    bid, batch_code = seed_batch(db, actors)
    sid, sample_code = seed_sample(db, actors, bid, 'R')
    pid, process_code = seed_process(db, actors, bid)
    db.execute(table('process_samples').insert().values(process_id=pid, sample_id=sid, full_ale_cycles=100))
    login(page, actors)
    page.goto(BASE + f'/samples?sample_id={sid}')
    page.get_by_role('heading', name=sample_code).wait_for()
    page.get_by_role('button', name='编辑档案', exact=True).click()
    new_code = 'UI-RENAMED-' + uuid.uuid4().hex[:5]
    page.get_by_placeholder('例如 B01-S01').fill(new_code)
    page.get_by_role('button', name='保存样品', exact=True).click()
    expect(page.get_by_text(new_code).first).to_be_visible()
    page.goto(BASE + f'/processes?process_id={pid}')
    page.get_by_role('heading', name=process_code).wait_for()
    expect(page.locator('.experiment-step').filter(has_text=new_code)).to_be_visible()

    # Unused draft cleanup: select the draft process and preview its impact.
    draft_pid, draft_code = seed_process(db, actors, bid)
    page.goto(BASE + '/processes')
    row = page.locator('.table-wrap .el-table__row').filter(has_text=draft_code)
    expect(row).to_have_count(1)
    row.locator('.el-checkbox').click()
    page.get_by_test_id('batch-cleanup-open').click()
    dialog = page.get_by_test_id('batch-cleanup-table')
    expect(dialog).to_contain_text(draft_code)
    expect(dialog).to_contain_text('无依赖未使用草稿')
    page.get_by_test_id('batch-cleanup-apply').click()
    expect(page.get_by_test_id('batch-cleanup-table')).to_be_hidden()
    expect(page.locator('.table-wrap .el-table__row').filter(has_text=draft_code)).to_have_count(0)
    assert errors == []

    # Detail lifecycle preview omits delete for a process with a scientific dependency.
    page.goto(BASE + f'/processes?process_id={pid}')
    page.get_by_role('heading', name=process_code).wait_for()
    page.get_by_test_id('lifecycle-open').click()
    lifecycle = page.get_by_test_id('lifecycle-dialog')
    expect(lifecycle).to_be_visible()
    expect(lifecycle.get_by_test_id('lifecycle-action-delete')).to_have_count(0)
    expect(lifecycle).to_contain_text('删除仅在没有任何依赖时可用')
    page.keyboard.press('Escape')
