"""Windows Chromium acceptance against isolated MySQL + isolated originals."""
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import update

from app.config import ROOT
from app.db import table
from test_phase4_browser import db, client
from test_phase3_imports import workbook
from test_codex_core_repair import import_pair

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1' or not os.getenv('ALE_DB_NAME', '').endswith('_test'), reason='Opt-in isolated browser acceptance')
BASE = 'http://127.0.0.1:8042'
OUT = ROOT / 'reports' / 'codex-core-repair'


@pytest.fixture
def ui(client, actors, db, tmp_path, monkeypatch, request):
    global OUT
    if os.getenv('ALE_BROWSER_OUT'):
        OUT = Path(os.environ['ALE_BROWSER_OUT'])
        OUT.mkdir(parents=True, exist_ok=True)
    import uvicorn
    import app.main as main
    from app import ai
    @contextmanager
    def ai_transaction():
        # current_user already holds the request fixture's lock. Keep the AI
        # status read on the same rollback connection; never open a second writer.
        with db.begin_nested():
            yield db
    monkeypatch.setattr(ai,'ai_transaction',ai_transaction)
    main.canonical_contract()
    monkeypatch.setattr(main, 'ROOT', OUT)
    monkeypatch.setenv('ALE_ORIGINALS_ROOT', str(tmp_path / 'originals'))
    cross_data=import_pair(client,actors,db,different_model='cross_model' in request.node.name) if any(name in request.node.name for name in ('cross_model','reliable_summary')) else None
    if 'reliable_summary' in request.node.name:
        sid,pid,before,after=cross_data
        m,p=table('measurements'),table('processes')
        db.execute(update(m).where(m.c.measurement_id==before).values(measured_at='2026-01-01 09:00:00'))
        db.execute(update(m).where(m.c.measurement_id==after).values(measured_at='2026-01-01 12:00:00'))
        db.execute(update(p).where(p.c.process_id==pid).values(started_at='2026-01-01 10:00:00',ended_at='2026-01-01 11:00:00'))
    server = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=8042, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            page.set_default_timeout(15000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(BASE + '/login')
            page.get_by_label('用户名', exact=True).fill(actors['operator']['user']['username'])
            page.get_by_label('密码', exact=True).fill('TestPassword123!')
            page.get_by_role('button', name='登录工作台', exact=True).click()
            page.get_by_role('heading', name='新建实验记录', exact=True).wait_for()
            try:
                yield dict(page=page, client=client, actors=actors, db=db, errors=errors,cross_data=cross_data)
            finally:
                page.screenshot(path=str(OUT / ('last-'+re.sub(r'[^\w-]','_',request.node.name)+'.png')),full_page=True)
            assert not errors, errors
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def capture(ui, name):
    page = ui['page']
    path = OUT / f'{name}.png'
    page.screenshot(path=str(path), full_page=True)
    metrics = page.evaluate('({viewport:innerWidth,body:document.body.scrollWidth,document:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight})')
    assert metrics['document'] <= metrics['viewport'] + 1, metrics
    print('SCREENSHOT', path.name, metrics)


def choose(page, control, label):
    control.locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")][1]').click()
    page.locator('[id="'+control.get_attribute('aria-controls')+'"]').get_by_role('option', name=label, exact=True).click()


@pytest.mark.parametrize('width', [1440, 390])
def test_wizard_empty_batch_short_codes_import_and_sample_review(ui, width):
    page, client, actors = ui['page'], ui['client'], ui['actors']
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto(BASE + '/experiments/new')
    page.get_by_label('计划标题', exact=True).fill('S01 实验记录')
    page.get_by_role('button', name='保存目标与草稿', exact=True).click()
    page.wait_for_url('**/experiments/new?plan_id=*')
    page.get_by_role('button', name=re.compile('^参与样品：')).click()
    page.get_by_label('样品数量', exact=True).fill('16')
    page.get_by_label('样品编号前缀', exact=True).fill('S01')
    page.get_by_role('button', name='新建批次', exact=True).click()
    dialog = page.get_by_role('dialog', name='新建样品所属批次')
    dialog.get_by_label('快速批次编号').fill('S01')
    dialog.get_by_role('button', name='取消', exact=True).click()
    expect(page.get_by_label('样品数量', exact=True)).to_have_value('16')
    expect(page.get_by_label('样品编号前缀', exact=True)).to_have_value('S01')
    page.get_by_role('button', name='新建批次', exact=True).click()
    dialog.get_by_label('快速批次编号').fill('S01')
    dialog.get_by_label('快速批次名称').fill('测试沉积批次；非物理母片')
    dialog.get_by_role('button', name='创建并选中批次', exact=True).click()
    expect(dialog).not_to_be_visible()
    page.get_by_role('button', name='预览可用编号', exact=True).click()
    expect(page.get_by_label('样品编号 1', exact=True)).to_have_value('S01-1')
    expect(page.get_by_label('样品编号 16', exact=True)).to_have_value('S01-16')
    capture(ui, f'A-wizard-short-codes-{width}')
    if width==1440:
        page.get_by_label('样品数量',exact=True).fill('15')
        expect(page.get_by_test_id('wizard-sample-preview')).not_to_be_visible()
        page.get_by_label('样品数量',exact=True).fill('16')
        page.get_by_role('button',name='预览可用编号',exact=True).click()
        expect(page.get_by_label('样品编号 16',exact=True)).to_have_value('S01-16')
    if width==390:
        def lose_sample_response(route):
            assert route.fetch().status==201
            route.abort('failed')
        page.route('**/api/v1/batches/*/samples/batch',lose_sample_response,times=1)
    page.get_by_role('button', name='创建并关联本次执行', exact=True).click()
    if width==390:
        page.get_by_role('button',name='核对上次样品创建结果',exact=True).click()
    expect(page.get_by_role('button', name='参与样品：已保存', exact=True)).to_be_visible()
    headers = actors['operator']['headers']
    samples = client.get('/api/v1/samples', headers=headers, params={'size': 200}).json()['data']
    assert sorted([s['sample_code'] for s in samples]) == sorted([f'S01-{i}' for i in range(1, 17)])
    run = client.get('/api/v1/processes', headers=headers).json()['data'][0]
    detail = client.get(f"/api/v1/processes/{run['process_id']}", headers=headers).json()['data']
    assert len(detail['samples']) == 16 and len(run['process_code']) < 30
    page.get_by_role('button', name='预览可用编号', exact=True).click()
    expect(page.get_by_label('样品编号 1', exact=True)).to_have_value('S01-17')
    sid = next(s['sample_id'] for s in samples if s['sample_code'] == 'S01-1')
    page.goto(BASE + f'/samples?sample_id={sid}')
    page.get_by_test_id('sample-research-review').wait_for()
    page.get_by_role('button', name='导入该样品数据', exact=True).click()
    page.get_by_test_id('import-files').set_input_files([
        {'name': '1.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook(('10', '11', '12'))},
        {'name': '1-O3 Exposure 10-HF-TMA 50 cycles.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': workbook(('9', '10', '11'))}])
    page.get_by_test_id('upload-preview').click()
    cards = page.locator('article.import-item')
    expect(cards).to_have_count(2)
    expect(cards.nth(0).locator('.el-select').first).to_contain_text('S01-1')
    # Stage is a required fact; next must explain exactly which file lacks it.
    page.get_by_role('button', name='下一步：确认提交', exact=True).click()
    expect(page.get_by_role('button', name=re.compile('1.xlsx：请选择测量阶段'))).to_be_visible()
    # Choose stages through the actual Element Plus controls.
    choose(page, cards.nth(0).get_by_role('combobox', name='测量阶段', exact=True), '初始')
    choose(page, cards.nth(1).get_by_role('combobox', name='测量阶段', exact=True), 'ALE 后')
    assert page.get_by_test_id('import-analysis').count() == 0
    capture(ui, f'B-import-compact-review-{width}')
    page.get_by_role('button', name='下一步：确认提交', exact=True).click()
    page.get_by_test_id('import-step3-submit').click()
    expect(page.get_by_test_id('import-result-banner')).to_be_visible()
    capture(ui, f'B-import-saved-{width}')
    page.get_by_role('button', name='返回样品详情查看结果', exact=True).click()
    expect(page.get_by_test_id('sample-measurements').locator('.el-table__body tbody tr')).to_have_count(2)
    expect(page.get_by_text(re.compile('无法计算：未确认同样品的前测配对'))).to_be_visible()
    page.get_by_test_id('sample-research-review').scroll_into_view_if_needed()
    capture(ui, f'D-sample-research-history-{width}')
    page.locator('.records-drawer').screenshot(path=str(OUT/f'D-sample-results-{width}.png'))
    print('VERIFIED', width, 'cancel preserved inputs; S01-1..16 bound; next S01-17; two Excel uploads confirmed once; sample review refreshed; no invented EPC')


def test_cross_model_pair_failure_still_renders_original_charts(ui):
    sid, pid, before, after = ui['cross_data']
    page = ui['page']
    page.goto(BASE + f'/analysis?sample_id={sid}')
    page.get_by_role('checkbox', name=re.compile('^纳入 ')).nth(0).check()
    page.get_by_role('checkbox', name=re.compile('^纳入 ')).nth(1).check()
    page.get_by_role('button', name=re.compile('计算')).first.click()
    page.locator('.scientific-plot').first.wait_for()
    rows=ui['client'].get('/api/v1/analysis/measurements',headers=ui['actors']['operator']['headers'],params={'sample_id':sid}).json()['data']
    labels={r['measurement_id']:r['measurement_code'] for r in rows}
    choose(page,page.get_by_role('combobox',name='分析前测',exact=True),labels[before])
    choose(page,page.get_by_role('combobox',name='分析后测',exact=True),labels[after])
    page.get_by_role('checkbox',name=re.compile('我已核对前后方向')).check()
    page.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(page.get_by_text(re.compile('差值未计算：.*模型'))).to_be_visible()
    expect(page.get_by_test_id('scientific-plot')).to_be_visible()
    capture(ui, 'C-cross-model-original-plots')
    print('VERIFIED cross-model independent plot response and charts; pair delta rejection covered by API test')


def test_standalone_single_and_bulk_inline_batch_reuse(ui):
    page=ui['page']
    page.goto(BASE+'/samples')
    page.get_by_role('button',name='新建样品',exact=True).click()
    page.get_by_test_id('inline-batch-open').click()
    dialog=page.get_by_role('dialog',name='新建批次',exact=True)
    dialog.get_by_label('批次编号',exact=True).fill('S02')
    dialog.get_by_label('批次名称',exact=True).fill('单独建样验证')
    dialog.get_by_role('button',name='创建并选中',exact=True).click()
    expect(page.get_by_placeholder('例如 B01-S01')).to_have_value('S02-1')
    page.get_by_role('button',name='保存样品',exact=True).click()
    page.get_by_role('button',name='S02-1',exact=True).wait_for()
    page.goto(BASE+'/samples')
    page.get_by_test_id('sample-home-bulk').click()
    bulk=page.get_by_role('dialog',name='批量创建小样',exact=True)
    bulk.get_by_test_id('batch-count').fill('2')
    bulk.get_by_label('编号前缀',exact=True).fill('MY-SAMPLES')
    bulk.get_by_label('前处理',exact=True).fill('保留共同属性')
    page.get_by_test_id('bulk-inline-batch-open').click()
    dialog.get_by_role('button',name='取消',exact=True).click()
    expect(bulk.get_by_test_id('batch-count')).to_have_value('2')
    expect(bulk.get_by_label('编号前缀',exact=True)).to_have_value('MY-SAMPLES')
    page.get_by_test_id('bulk-inline-batch-open').click()
    dialog.get_by_label('批次编号',exact=True).fill('S03')
    dialog.get_by_label('批次名称',exact=True).fill('批量内联验证')
    dialog.get_by_role('button',name='创建并选中',exact=True).click()
    expect(bulk.get_by_label('编号前缀',exact=True)).to_have_value('MY-SAMPLES')
    expect(bulk.get_by_label('前处理',exact=True)).to_have_value('保留共同属性')
    bulk.get_by_role('button',name='按当前设置重新生成编号预览',exact=True).click()
    expect(bulk.get_by_test_id('batch-preview').locator('tbody tr').first.locator('input').first).to_have_value('MY-SAMPLES-1')
    bulk.get_by_test_id('batch-submit').click()
    expect(bulk).not_to_be_visible()
    data=ui['client'].get('/api/v1/samples',headers=ui['actors']['operator']['headers'],params={'size':200}).json()['data']
    assert {s['sample_code'] for s in data}=={'S02-1','MY-SAMPLES-1','MY-SAMPLES-2'}
    capture(ui,'A-standalone-single-bulk')


def test_reliable_summary_and_execution_code_edit(ui):
    page=ui['page']
    sid,pid,before,after=ui['cross_data']
    page.goto(BASE+f'/processes?process_id={pid}')
    page.get_by_role('button',name='修改执行编号',exact=True).click()
    page.locator('.el-message-box__input input').fill('RUN-100-A')
    page.get_by_role('button',name='保存编号',exact=True).click()
    expect(page.get_by_role('heading',name='RUN-100-A',exact=True)).to_be_visible()
    page.goto(BASE+f'/samples?sample_id={sid}')
    expect(page.get_by_test_id('sample-experiments')).to_contain_text('RUN-100-A')
    expect(page.get_by_text(re.compile('每循环表观刻蚀量 0.01 nm/cycle'))).to_be_visible()
    page.get_by_test_id('sample-research-review').scroll_into_view_if_needed()
    page.locator('.records-drawer').screenshot(path=str(OUT/'D-confirmed-apparent-summary.png'))
    sample=ui['client'].get(f'/api/v1/samples/{sid}',headers=ui['actors']['operator']['headers']).json()['data']
    page.goto(BASE+f'/imports?process_id={pid}')
    page.get_by_test_id('import-files').set_input_files({'name':sample['sample_code']+'.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':workbook(('20','21','22'))})
    page.get_by_test_id('upload-preview').click()
    card=page.locator('article.import-item')
    card.get_by_role('button',name=re.compile('^建议 ')).click()
    expect(card.get_by_role('combobox',name='导入执行',exact=True).locator('xpath=ancestor::div[contains(@class,"el-select")][last()]')).to_contain_text('RUN-100-A')
    print('VERIFIED actual UI: rename execution with history; 11 → 10 nm; sample 100 cycles instead of equipment 500; apparent 0.01 nm/cycle')

