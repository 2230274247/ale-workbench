"""Production Vue routes + real API/parser on isolated rollback-only MySQL."""
import os
import uuid
from pathlib import Path
import pytest
from playwright.sync_api import expect
from app.db import table
from test_phase4_browser import db, client
from test_phase3_imports import originals, workbook, preview
from test_sample_experiment_links import make_batch, make_sample, make_process, link, event
import test_codex_core_repair_browser as common
from test_codex_core_repair_browser import ui, BASE, capture, choose

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1' or not os.getenv('ALE_DB_NAME', '').endswith('_test'), reason='Independent test database required')
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'reports/ui-upgrade' / os.getenv('ALE_UI_STAGE', 'p0')

@pytest.fixture(autouse=True)
def world(db, client, actors, originals, monkeypatch):
    OUT.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(common, 'OUT', OUT)
    monkeypatch.setenv('ALE_ENVIRONMENT', 'testing')
    monkeypatch.setenv('ALE_ENVIRONMENT_LABEL', '隔离测试 · 回滚验证')
    monkeypatch.setenv('ALE_INSTANCE_ID', 'ale-ui-upgrade-test')
    bid = make_batch(db, actors)
    sid = make_sample(db, actors, bid)
    pid = make_process(db, actors, bid, 500)
    tag = uuid.uuid4().hex[:8]
    db.execute(table('samples').update().where(table('samples').c.sample_id == sid).values(sample_code='UI-S01-'+tag))
    plan = db.execute(table('experiment_plans').insert().values(plan_code='UI-PLAN-'+tag, title='氮化硅前后膜厚研究', objective='核对已确认配对及逐片实际参与', owner_user_id=actors['operator']['user']['user_id'])).inserted_primary_key[0]
    db.execute(table('processes').update().where(table('processes').c.process_id == pid).values(plan_id=plan, started_at='2026-01-01 10:00:00', ended_at='2026-01-01 11:00:00'))
    link(db, pid, sid, 100); event(db, pid, sid, 'load'); event(db, pid, sid, 'unload')
    model = db.execute(table('optical_models').insert().values(model_code='UI-MODEL-'+tag, model_name='隔离核验模型')).inserted_primary_key[0]
    job = preview(client, actors, [('before-'+tag+'.xlsx', workbook(('10','11','11','12'))), ('after-'+tag+'.xlsx', workbook(('9','10','10','11')))])
    choices = [dict(item_id=i['item_id'], action='import', sample_id=sid, process_id=pid, stage=stage, optical_model_id=model, confirm_units=True, confirm_associations=True) for i,stage in zip(job['items'],['initial','after_ale'])]
    choices[1]['pair_item_id'] = choices[0]['item_id']
    response = client.post(f"/api/v1/imports/{job['job_id']}/confirm", headers=actors['operator']['headers'], json={'expected_row_version':job['row_version'],'items':choices})
    assert response.status_code == 200, response.text
    mids = [i['measurement_ids'][0] for i in response.json()['data']['items']]
    for mid,when in zip(mids,['2026-01-01 09:00:00','2026-01-01 12:00:00']):
        db.execute(table('measurements').update().where(table('measurements').c.measurement_id==mid).values(measured_at=when))
    db.info['ui_world'] = (sid,pid,plan,mids)

def test_routes_and_before_after(ui):
    p=ui['page'];sid,pid,plan,mids=ui['db'].info['ui_world']
    for width in [1440,390]:
        p.set_viewport_size({'width':width,'height':1000})
        p.goto(BASE+'/')
        expect(p.get_by_role('heading',name='工作台概览',exact=True)).to_be_visible()
        capture(ui,f'home-{width}')
        p.goto(BASE+f'/analysis?sample_id={sid}&process_id={pid}')
        expect(p.locator('.analysis-controls .el-table input[type=checkbox]')).to_have_count(2)
        for checkbox in p.locator('.analysis-controls .el-table input[type=checkbox]').all(): checkbox.check()
        p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
        expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','8')
        capture(ui,f'analysis-{width}')
        p.goto(BASE+f'/sample-history?sample_id={sid}')
        expect(p.get_by_test_id('sample-experiments')).to_contain_text('氮化硅前后膜厚研究')
        capture(ui,f'sample-{width}')
        p.goto(BASE+f'/processes?process_id={pid}')
        expect(p.get_by_test_id('experiment-results')).to_contain_text('氮化硅前后膜厚研究')
        capture(ui,f'experiment-{width}')

def test_plot_and_scientific_boundaries(ui):
    if os.getenv('ALE_UI_STAGE') == 'before': pytest.skip('Post-upgrade behavior')
    p=ui['page'];sid,pid,plan,mids=ui['db'].info['ui_world']
    p.goto(BASE+f'/analysis?sample_id={sid}&measurement_id={mids[0]}')
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(p.get_by_test_id('compact-point-summary')).to_be_visible()
    expect(p.get_by_test_id('compact-point-summary')).to_contain_text('11')
    p.get_by_role('button',name='展开图表',exact=True).click()
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','4')
    p.locator('.plot-advanced > summary').click()
    p.get_by_label('分析图形',exact=True).select_option('mapping')
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','4')
    with p.expect_download() as dl: p.get_by_role('button',name='导出图像 PNG',exact=True).click()
    assert dl.value.path().read_bytes().startswith(b'\x89PNG')
    p.get_by_label('分析图形',exact=True).select_option('scatter')
    with ui['db'].info['browser_lock']:
        ui['db'].execute(table('measurement_points').update().where(table('measurement_points').c.measurement_id==mids[0]).values(x_mm=None,y_mm=None))
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    p.get_by_role('button',name='展开图表',exact=True).click()
    p.locator('.plot-advanced > summary').click()
    p.get_by_label('分析图形',exact=True).select_option('mapping')
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','0')
    expect(p.get_by_text('所选横轴 / 指标没有已记录的有效值',exact=False)).to_be_visible()
    # Cross-model fallback uses the actual API, not mocked plot data.
    with ui['db'].info['browser_lock']:
        mid2=ui['db'].execute(table('optical_models').insert().values(model_code='UI-CROSS-'+uuid.uuid4().hex[:8],model_name='另一模型')).inserted_primary_key[0]
        ui['db'].execute(table('measurements').update().where(table('measurements').c.measurement_id==mids[1]).values(optical_model_id=mid2))
    p.goto(BASE+f'/analysis?sample_id={sid}')
    expect(p.locator('.analysis-controls .el-table input[type=checkbox]')).to_have_count(2)
    for box in p.locator('.analysis-controls .el-table input[type=checkbox]').all():box.check()
    names=[r[0] for r in ui['db'].execute(table('measurements').select().with_only_columns(table('measurements').c.measurement_code).where(table('measurements').c.measurement_id.in_(mids)))]
    choose(p,p.get_by_role('combobox',name='分析前测',exact=True),names[0]);choose(p,p.get_by_role('combobox',name='分析后测',exact=True),names[1])
    p.get_by_label('我已核对前后方向',exact=False).check()
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(p.get_by_text('差值未计算：',exact=False)).to_be_visible()
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','8')
    capture(ui,'cross-model-raw-data')
    p.goto(BASE+f'/processes?process_id={pid}')
    expect(p.locator('.sample-result-table')).to_contain_text('11 → 10')
    expect(p.locator('.sample-result-table')).to_contain_text('无法计算')

def test_sample_links_and_original_measurement(ui):
    p=ui['page'];sid,pid,plan,mids=ui['db'].info['ui_world']
    p.goto(BASE+f'/processes?process_id={pid}')
    p.get_by_role('button',name='完整科研履历 / 装卸记录',exact=True).first.click()
    p.wait_for_url('**/sample-history?sample_id=*')
    expect(p.get_by_test_id('sample-experiments')).to_contain_text('氮化硅前后膜厚研究')
    if os.getenv('ALE_UI_STAGE') not in ('before','p0'):
        expect(p.locator('.history-measurement')).to_have_count(2)
        p.locator('.history-measurement').first.get_by_role('link',name='原件',exact=True).click()
        p.wait_for_url('**/source-files?id=*')
        p.go_back()
    p.get_by_role('link',name='打开实验',exact=True).first.click()
    p.wait_for_url(f'**/processes?process_id={pid}')
    # Read a retained actual research file, then import ONLY into isolated rollback test DB.
    files=list((ROOT/'storage/originals').rglob('*'))
    original=next((f for f in files if f.is_file()),None)
    assert original is not None, 'No retained original available'
    import hashlib
    digest=hashlib.sha256(original.read_bytes()).hexdigest()
    job=preview(ui['client'],ui['actors'],[('retained-research.xlsx',original.read_bytes())])
    item=job['items'][0]
    assert item['parse_result']['status']=='parsed'
    with ui['db'].info['browser_lock']:
        bid=make_batch(ui['db'],ui['actors']);source_sample=make_sample(ui['db'],ui['actors'],bid)
    response=ui['client'].post(f"/api/v1/imports/{job['job_id']}/confirm",headers=ui['actors']['operator']['headers'],json={'expected_row_version':job['row_version'],'items':[{'item_id':item['item_id'],'action':'import','sample_id':source_sample,'stage':'initial','confirm_units':True,'confirm_associations':True}]})
    assert response.status_code==200,response.text
    mid=response.json()['data']['items'][0]['measurement_ids'][0]
    p.goto(BASE+f'/analysis?sample_id={source_sample}&measurement_id={mid}')
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(p.get_by_test_id('compact-point-summary')).to_be_visible()
    assert p.get_by_test_id('compact-point-summary').locator('.el-table__body tbody tr').count()>=4
    capture(ui,'retained-original-api-summary-1440')
    assert hashlib.sha256(original.read_bytes()).hexdigest()==digest
    print('RETAINED_ORIGINAL_SHA256_UNCHANGED',digest,'ISOLATED_IMPORT_ONLY')

def test_confirmed_comparison_mapping_and_accessibility(ui):
    p=ui['page'];sid,pid,plan,mids=ui['db'].info['ui_world']
    p.goto(BASE+f'/analysis?process_id={pid}&sample_id={sid}')
    boxes=p.locator('.analysis-controls .el-table input[type=checkbox]')
    expect(boxes).to_have_count(2)
    for box in boxes.all():box.check()
    names=[ui['db'].execute(table('measurements').select().with_only_columns(table('measurements').c.measurement_code).where(table('measurements').c.measurement_id==mid)).scalar_one() for mid in mids]
    choose(p,p.get_by_role('combobox',name='分析前测',exact=True),names[0]);choose(p,p.get_by_role('combobox',name='分析后测',exact=True),names[1])
    p.get_by_label('我已核对前后方向',exact=False).check()
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(p.get_by_text('平均变化 -1 nm',exact=False)).to_be_visible()
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','8')
    p.locator('.plot-advanced > summary').click()
    with p.expect_download() as dl:p.get_by_role('button',name='导出数据与计算记录',exact=True).click()
    import json
    data=json.loads(dl.value.path().read_text(encoding='utf-8'))
    assert data['pair']['mean_delta_nm']=='-1'
    assert all(s['source']['sha256'] for s in data['series'])
    capture(ui,'confirmed-pair')
    job=preview(ui['client'],ui['actors'],[('coordinate-81.xlsx',workbook(tuple(str(10+i/100) for i in range(81))))])
    item=job['items'][0]
    response=ui['client'].post(f"/api/v1/imports/{job['job_id']}/confirm",headers=ui['actors']['operator']['headers'],json={'expected_row_version':job['row_version'],'items':[{'item_id':item['item_id'],'action':'import','sample_id':sid,'stage':'intermediate','confirm_units':True,'confirm_associations':True}]})
    assert response.status_code==200,response.text
    mid=response.json()['data']['items'][0]['measurement_ids'][0]
    p.goto(BASE+f'/analysis?sample_id={sid}&measurement_id={mid}')
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','81')
    p.get_by_label('分析图形',exact=True).select_option('mapping')
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','81')
    capture(ui,'coordinate-81-mapping')
    p.set_viewport_size({'width':390,'height':844});p.emulate_media(reduced_motion='reduce')
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert p.locator('.ai-launch:visible').count()==0
    p.locator('.plot-advanced > summary').focus();p.keyboard.press('Enter')
    assert p.locator('.plot-advanced').get_attribute('open') is not None
    assert p.locator('.plot-advanced > summary').evaluate('(e)=>getComputedStyle(e).outlineStyle')!='none'
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).focus()
    assert p.get_by_role('button',name='按当前选择计算并绘图',exact=True).evaluate('(e)=>getComputedStyle(e).transitionDuration')=='0s'
    capture(ui,'coordinate-81-mapping-390')

def test_experiment_first_filter_keeps_sample_context(ui):
    p=ui['page'];sid,pid,plan,mids=ui['db'].info['ui_world']
    code=ui['db'].execute(table('processes').select().with_only_columns(table('processes').c.process_code).where(table('processes').c.process_id==pid)).scalar_one()
    sample_code=ui['db'].execute(table('samples').select().with_only_columns(table('samples').c.sample_code).where(table('samples').c.sample_id==sid)).scalar_one()
    p.goto(BASE+'/analysis')
    choose(p,p.get_by_role('combobox',name='分析执行',exact=True),'氮化硅前后膜厚研究 · '+code)
    expect(p.locator('.analysis-controls .el-table input[type=checkbox]')).to_have_count(2)
    choose(p,p.get_by_role('combobox',name='分析样品',exact=True),sample_code)
    expect(p.get_by_role('combobox',name='分析执行',exact=True).locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")][1]')).to_contain_text(code)
    choose(p,p.get_by_role('combobox',name='分析阶段',exact=True),'ALE 后')
    expect(p.locator('.analysis-controls .el-table input[type=checkbox]')).to_have_count(1)
