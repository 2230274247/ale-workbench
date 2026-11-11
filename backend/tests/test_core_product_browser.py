"""Existing experiment/sample/import journeys against isolated MySQL and build."""
import os,uuid
import pytest
from playwright.sync_api import expect
from app.db import table
from test_phase4_browser import db,client
import test_codex_core_repair_browser as common
from test_codex_core_repair_browser import ui,BASE,capture
from test_phase3_imports import originals
from test_codex_core_repair import import_pair
from test_sample_experiment_links import make_batch,make_sample,make_process,link,event
from test_core_product_alignment import system

pytestmark=pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST')!='1' or not os.getenv('ALE_DB_NAME','').endswith('_test'),reason='Isolated opt-in browser only')

@pytest.fixture(autouse=True)
def world(monkeypatch,db,client,actors,originals,request,tmp_path):
    monkeypatch.setattr(common,'OUT',common.ROOT/'reports/core-product-alignment')
    monkeypatch.setenv('ALE_ENVIRONMENT_LABEL','隔离测试')
    monkeypatch.setenv('ALE_INSTANCE_ID','ale-test')
    monkeypatch.setenv('ALE_ORIGINALS_ROOT',str(tmp_path/'originals'))
    if 'upload' in request.node.name:return
    if 'result' in request.node.name:
        sid,pid,before,after=import_pair(client,actors,db)
        m,p=table('measurements'),table('processes')
        db.execute(m.update().where(m.c.measurement_id==before).values(measured_at='2026-01-01 09:00:00'))
        db.execute(m.update().where(m.c.measurement_id==after).values(measured_at='2026-01-01 12:00:00'))
        plan=db.execute(table('experiment_plans').insert().values(plan_code='UI-'+uuid.uuid4().hex[:8],title='氮化硅刻蚀研究',objective='比较前后膜厚',owner_user_id=actors['operator']['user']['user_id'])).inserted_primary_key[0]
        db.execute(p.update().where(p.c.process_id==pid).values(plan_id=plan,started_at='2026-01-01 10:00:00',ended_at='2026-01-01 11:00:00'))
        db.info['product_world']=(sid,pid,plan)
    else:
        bid=make_batch(db,actors);samples=[make_sample(db,actors,bid,str(i)) for i in range(5)]
        chemistry=system(db,actors,'明确的同腔体系');pids=[]
        for index in range(2):
            pid=make_process(db,actors,bid,500);pids.append(pid)
            plan=db.execute(table('experiment_plans').insert().values(plan_code='UI-'+uuid.uuid4().hex[:8],title=f'第{index+1}项研究实验',owner_user_id=actors['operator']['user']['user_id'])).inserted_primary_key[0]
            db.execute(table('processes').update().where(table('processes').c.process_id==pid).values(plan_id=plan,chemistry_system_id=chemistry))
        for i,sid in enumerate(samples):
            step=db.execute(table('process_steps').insert().values(process_id=pids[0],step_index=i+1,step_kind='wait')).inserted_primary_key[0]
            link(db,pids[0],sid,(i+1)*100);event(db,pids[0],sid,'load');event(db,pids[0],sid,'unload',step)
        link(db,pids[1],samples[0],100);event(db,pids[1],samples[0],'load');event(db,pids[1],samples[0],'unload')
        db.info['product_world']=(samples,pids)

def test_plan_and_execution_show_result_first_and_link_to_sample(ui):
    sid,pid,plan=ui['db'].info['product_world'];page=ui['page']
    for path in (f'/plans?plan_id={plan}',f'/processes?process_id={pid}'):
        page.goto(BASE+path)
        summary=page.get_by_test_id('experiment-results');expect(summary).to_be_visible()
        expect(summary).to_contain_text('氮化硅刻蚀研究')
        expect(summary).to_contain_text('原始平均膜厚 11 nm')
        expect(summary).to_contain_text('原始平均膜厚 10 nm')
        expect(summary).to_contain_text('0.01 nm/cycle')
        expect(summary).to_contain_text('可用膜厚点 3 / 总点数 3')
        expect(page.get_by_text('版本 1',exact=True)).not_to_be_visible()
    capture(ui,'experiment-result-first')
    summary.locator('.sample-result > summary').first.click()
    summary.locator('summary',has_text='测量详情：真实测点、模型与原始文件').click()
    measurement_link=summary.get_by_test_id('sample-measurements').get_by_role('link').first
    measurement_link.click()
    expect(page.get_by_test_id('measurement-detail')).to_contain_text('氮化硅刻蚀研究')
    expect(page.get_by_test_id('measurement-points').locator('.el-table__body tbody tr')).to_have_count(3)
    expect(page.get_by_test_id('measurement-id')).not_to_be_visible()
    capture(ui,'measurement-detail-by-name')
    page.goto(BASE+f'/processes?process_id={pid}')
    page.get_by_role('button',name='完整科研履历 / 装卸记录',exact=True).click()
    page.wait_for_url('**/sample-history?sample_id=*')
    expect(page.get_by_test_id('measurement-summary')).to_contain_text('11 nm')
    expect(page.get_by_test_id('sample-experiments')).to_contain_text('氮化硅刻蚀研究')
    page.get_by_role('link',name='打开实验',exact=True).click()
    page.wait_for_url(f'**/processes?process_id={pid}')

@pytest.mark.parametrize('width',[1440,390])
def test_two_experiments_and_five_extraction_nodes(ui,width):
    samples,pids=ui['db'].info['product_world'];page=ui['page'];page.set_viewport_size({'width':width,'height':1000})
    page.goto(BASE+f'/sample-history?sample_id={samples[0]}')
    history=page.get_by_test_id('sample-experiments')
    expect(history).to_contain_text('第1项研究实验');expect(history).to_contain_text('第2项研究实验')
    expect(page.get_by_test_id('sample-participation-summary')).to_contain_text('200 cycles')
    page.get_by_role('link',name='打开实验',exact=True).first.click()
    expect(page.get_by_test_id('experiment-sample-result')).to_have_count(5)
    for i in range(5):
        card=page.get_by_test_id('experiment-sample-result').nth(i)
        expect(card).to_contain_text(f'本次逐片循环：{(i+1)*100}')
        expect(card).to_contain_text(f'取出步骤 {i+1}')
    capture(ui,f'five-sample-results-{width}')
    page.get_by_role('button',name='完整科研履历 / 装卸记录',exact=True).nth(4).click()
    expect(page.get_by_test_id('sample-participation-summary')).to_contain_text('500 cycles')

def test_existing_upload_journey_with_new_result_summary(ui):
    from test_codex_core_repair_browser import test_wizard_empty_batch_short_codes_import_and_sample_review
    test_wizard_empty_batch_short_codes_import_and_sample_review(ui,1440)
