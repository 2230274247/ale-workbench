"""Real browser journeys on rollback-only MySQL and isolated static assets."""
import os
import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from app.db import table
from test_phase4_browser import db,client
import test_codex_core_repair_browser as browser_test
from test_codex_core_repair_browser import ui,BASE,capture
from test_sample_experiment_links import make_batch,make_sample,make_process,link,event,measurement

pytestmark=pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST')!='1' or not os.getenv('ALE_DB_NAME','').endswith('_test'),reason='Isolated opt-in browser only')

@pytest.fixture(autouse=True)
def output(monkeypatch,db,actors,client,request):
    monkeypatch.setattr(browser_test,'OUT',browser_test.ROOT/os.getenv('ALE_BROWSER_OUTPUT_ROOT','reports/batch-history-repair'))
    monkeypatch.setenv('ALE_ENVIRONMENT_LABEL','隔离测试环境')
    monkeypatch.setenv('ALE_INSTANCE_ID','ale-isolated-browser-test')
    # Seed before browser login starts background API requests on the shared connection.
    bid=make_batch(db,actors)
    if 'archived_batch' in request.node.name:
        code=db.scalar(select(table('batches').c.batch_code).where(table('batches').c.batch_id==bid))
        assert client.post(f'/api/v1/batches/{bid}/archive',headers=actors['operator']['headers'],json={'expected_row_version':1}).status_code==200
        db.info['world']=(bid,code)
    else:
        samples=[make_sample(db,actors,bid,str(i)) for i in range(5)]
        first=make_process(db,actors,bid,500);second=make_process(db,actors,bid,100)
        from test_core_product_alignment import system
        chemistry=system(db,actors,'已确认同腔处理体系')
        p=table('processes');db.execute(p.update().where(p.c.process_id.in_([first,second])).values(chemistry_system_id=chemistry))
        for i,sid in enumerate(samples):
            step=db.execute(table('process_steps').insert().values(process_id=first,step_index=i+1,step_kind='wait')).inserted_primary_key[0]
            link(db,first,sid,(i+1)*100);event(db,first,sid,'load');event(db,first,sid,'unload',step);measurement(db,first,sid,str(10-i))
        link(db,second,samples[0],100);event(db,second,samples[0],'load');event(db,second,samples[0],'unload')
        db.info['world']=(samples,first)

def test_archived_batch_status_and_safe_rename_in_existing_form(ui):
    page,db,actors,client=(ui[k] for k in ('page','db','actors','client'))
    bid,code=db.info['world']
    page.goto(BASE+'/batches');page.get_by_role('button',name='新建批次',exact=True).click()
    page.get_by_placeholder('例如 B01',exact=True).fill(code)
    page.get_by_role('button',name='检查编号 / 查找已有批次',exact=True).click()
    expect(page.get_by_role('status').filter(has_text='该编号的批次已归档')).to_be_visible()
    expect(page.get_by_role('link',name='打开已有批次 '+code)).to_have_attribute('href',f'/batches?batch_id={bid}')
    page.get_by_role('button',name='更正未使用批次编号',exact=True).click()
    box=page.get_by_role('dialog',name='更正未使用批次编号')
    box.get_by_role('textbox').fill(code+'-OLD');box.get_by_role('button',name='确定',exact=True).click()
    box=page.get_by_role('dialog',name='更正原因');box.get_by_role('textbox').fill('隔离浏览器验证误建更正');box.get_by_role('button',name='确定',exact=True).click()
    expect(page.get_by_role('status').filter(has_text='编号可用')).to_be_visible()
    expect(box).not_to_be_visible()
    row=client.get(f'/api/v1/batches/{bid}',headers=actors['operator']['headers']).json()['data']
    assert row['batch_code']==code+'-OLD' and row['archived_at']
    capture(ui,'batch-unused-code-corrected')

@pytest.mark.parametrize('width',[1440,390])
def test_repeated_runs_and_five_sample_bidirectional_biography(ui,width):
    page,db,actors=(ui[k] for k in ('page','db','actors'))
    samples,first=db.info['world']
    page.set_viewport_size({'width':width,'height':1000})
    page.goto(BASE+f'/sample-history?sample_id={samples[0]}')
    expect(page.get_by_role('heading',name='样品科研履历',exact=True)).to_be_visible()
    expect(page.get_by_test_id('sample-experiments').locator('.el-timeline-item')).to_have_count(2)
    expect(page.get_by_test_id('sample-participation-summary')).to_contain_text('200 cycles')
    capture(ui,f'repeated-sample-{width}')
    expect(page.locator('details').filter(has=page.locator('summary',has_text='原始事件日志'))).not_to_have_attribute('open','')
    page.get_by_role('link',name='打开实验',exact=True).first.click()
    page.wait_for_url(f'**/processes?process_id={first}')
    expect(page.get_by_role('button',name='完整科研履历 / 装卸记录',exact=True)).to_have_count(5)
    management=page.locator('summary',has_text='参与样品管理与原始装卸记录')
    if management.count():management.click()
    page.get_by_role('button',name='编辑绑定',exact=True).first.click()
    binding=page.get_by_role('dialog',name='样品绑定',exact=True)
    expect(binding.locator('.el-form-item').filter(has=page.get_by_text('样品完整 ALE 循环数',exact=True)).locator('input')).to_have_value('100')
    binding.get_by_role('button',name='取消',exact=True).click()
    expect(binding).not_to_be_visible()
    if management.count():management.click()
    capture(ui,f'five-sample-experiment-{width}')
    page.get_by_role('button',name='完整科研履历 / 装卸记录',exact=True).nth(4).click()
    page.wait_for_url(f'**/sample-history?sample_id={samples[4]}&process_id={first}')
    expect(page.get_by_test_id('sample-participation-summary')).to_contain_text('500 cycles')
    expect(page.get_by_test_id('sample-experiments')).to_contain_text('步骤 5')
    expect(page.get_by_test_id('sample-measurements').locator('.el-table__body tbody tr')).to_have_count(1)
    capture(ui,f'sample-biography-{width}')
