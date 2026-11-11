"""Real Chromium/ECharts acceptance with real upload bytes, rollback database."""
import os
import shutil
import threading
import time
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright,expect
from sqlalchemy import select,func
from app.config import ROOT
from app.db import table
from test_scientificanalysis import actual_files,sample,upload,choice,confirm
from test_phase4_browser import db,client

pytestmark=pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST')!='1',reason='Opt-in real browser')
BASE='http://127.0.0.1:8037'

@pytest.fixture
def browser_ui(client,actors,db,tmp_path,monkeypatch):
    import uvicorn
    from app.main import app
    monkeypatch.setenv('ALE_ORIGINALS_ROOT',str(tmp_path/'originals'))
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8037,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(150):
        if server.started:break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
            page=context.new_page();errors=[];responses=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('response',lambda r:responses.append((r.url.rsplit('/api/v1/',1)[-1],r.status)) if '/api/v1/analysis/' in r.url else None)
            page.goto(BASE+'/login');page.get_by_label('用户名',exact=True).fill(actors['operator']['user']['username']);page.get_by_label('密码',exact=True).fill('TestPassword123!');page.get_by_role('button',name='登录工作台',exact=True).click();page.get_by_role('heading',name='工作台概览',exact=True).wait_for()
            yield page,responses
            print('BROWSER_JS_ERRORS',errors,'ANALYSIS_HTTP',responses)
            assert not errors
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=5)
        assert not thread.is_alive()
        if (tmp_path/'originals').exists():shutil.rmtree(tmp_path/'originals')

def screenshot(p,name):
    p.screenshot(path=str(ROOT/'reports/screenshots'/name),full_page=True)
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth+1')

def test_real_upload_preview_echarts_and_independent_analysis(browser_ui,client,actors,db):
    p,responses=browser_ui
    files=actual_files();assert set(files)=={4,81}
    with db.info['browser_lock']:
        baseline={n:db.scalar(select(func.count()).select_from(table(n))) for n in ('measurements','measurement_points','source_files')}
    p.goto(BASE+'/imports')
    p.get_by_test_id('import-files').set_input_files([{'name':f'real-{n}.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':files[n][1]} for n in (4,81)])
    p.get_by_test_id('upload-preview').click()
    expect(p.get_by_test_id('scientific-plot')).to_have_count(2,timeout=20000)
    expect(p.get_by_test_id('echarts-canvas').nth(0)).to_have_attribute('data-rendered-count','4')
    expect(p.get_by_test_id('echarts-canvas').nth(1)).to_have_attribute('data-rendered-count','81')
    assert p.locator('[data-testid="echarts-canvas"] canvas').count()==2
    screenshot(p,'round7-analysis-upload-1440.png')
    with db.info['browser_lock']:
        for n,v in baseline.items():assert db.scalar(select(func.count()).select_from(table(n)))==v
    jobid=int(p.url.split('job=')[1].split('&')[0]);print('REAL_PREVIEW_ECHARTS_COUNTS',[4,81],'BASELINE_UNCHANGED',baseline)
    p.goto(BASE+f'/analysis?job_id={jobid}')
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','85')
    p.get_by_label('分析图形',exact=True).select_option('mapping')
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','4')
    p.get_by_label('Mapping 来源',exact=True).select_option('1')
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','81')
    p.get_by_label('分析指标',exact=True).select_option('mse')
    screenshot(p,'round7-analysis-mapping-mse-1440.png')
    with p.expect_download() as dl:p.get_by_role('button',name='导出图像 PNG',exact=True).click()
    saved=dl.value.path();assert saved.read_bytes().startswith(b'\x89PNG')
    with p.expect_download() as dl:p.get_by_role('button',name='导出数据与计算记录',exact=True).click()
    import json
    data=json.loads(dl.value.path().read_text());assert [s['raw_count'] for s in data['series']]==[4,81]
    p.get_by_label('分析图形',exact=True).select_option('distribution');expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','85')
    p.get_by_label('分析图形',exact=True).select_option('trend');p.get_by_label('趋势横轴',exact=True).select_option('cumulative_cycles');expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','0')
    p.set_viewport_size({'width':390,'height':844});p.get_by_label('分析图形',exact=True).select_option('line');p.get_by_label('分析横轴',exact=True).select_option('point_no');screenshot(p,'round7-analysis-390.png')
    p.set_viewport_size({'width':1440,'height':1000})
    with db.info['browser_lock']:sid=sample(db,actors)
    job=client.get(f'/api/v1/imports/{jobid}',headers=actors['operator']['headers']).json()['data']
    committed=confirm(client,actors,job,[choice(i,sid) for i in job['items']]);assert committed.status_code==200,committed.text
    mids=[i['measurement_ids'][0] for i in committed.json()['data']['items']]
    p.goto(BASE+'/analysis')
    for mid in mids:
        with db.info['browser_lock']:code=db.scalar(select(table('measurements').c.measurement_code).where(table('measurements').c.measurement_id==mid))
        p.get_by_label('纳入 '+code,exact=True).check()
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click();expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','85')
    # Explicit save supports a single group or a confirmed pair.
    with db.info['browser_lock']:code=db.scalar(select(table('measurements').c.measurement_code).where(table('measurements').c.measurement_id==mids[1]))
    p.get_by_label('纳入 '+code,exact=True).uncheck()
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    expect(p.get_by_test_id('echarts-canvas')).to_have_attribute('data-rendered-count','4')
    p.get_by_label('保存分析名称',exact=True).fill('真实文件预览与正式测量一致性验证')
    p.get_by_role('button',name='显式保存分析记录',exact=True).click();expect(p.get_by_text('已保存分析记录 #',exact=False)).to_be_visible()
    expect(p.get_by_test_id('saved-analysis-record')).to_contain_text('来源有效性：有效');expect(p.get_by_test_id('saved-analysis-record')).to_contain_text('测点指纹');screenshot(p,'round7-analysis-formal-save-1440.png')
    print('EXPORT_PNG_JSON_VERIFIED',True,'FORMAL_POINT_COUNT',85,'RECORDED_CYCLES_ONLY_NO_INFERENCE',True,'ALL_TEST_WRITES_ROLLBACK',True)


def test_measurement_mean_trends_groups_gaps_and_saved_validity(browser_ui,client,actors,db):
    import json
    from test_scientificanalysis import post
    from test_phase3_imports import unique,workbook
    p,_=browser_ui
    files=actual_files();assert set(files)=={4,81}
    with db.info['browser_lock']:
        sid=sample(db,actors)
        modelid=db.execute(table('optical_models').insert().values(model_code=unique(),model_name=unique())).inserted_primary_key[0]
    job=upload(client,actors,[(f'real-{n}.xlsx',files[n][1]) for n in (4,81)]).json()['data']
    committed=confirm(client,actors,job,[choice(i,sid,optical_model_id=modelid) for i in job['items']]);assert committed.status_code==200,committed.text
    mids=[i['measurement_ids'][0] for i in committed.json()['data']['items']]
    with db.info['browser_lock']:
        m=table('measurements');process=table('processes');codes=[];pids=[]
        for mid,cycles,temp,cumulative in zip(mids,[30,10],[250,150],[90,50]):
            pid=db.execute(process.insert().values(process_code=unique(),process_mode='other',operator_user_id=actors['operator']['user']['user_id'],r1_temp_c=temp,full_ale_cycles=7,process_flow={'version':1,'total_cycles':cycles,'children':[]})).inserted_primary_key[0];pids.append(pid)
            db.execute(m.update().where(m.c.measurement_id==mid).values(process_id=pid,cumulative_cycles=cumulative))
            codes.append(db.scalar(select(m.c.measurement_code).where(m.c.measurement_id==mid)))
    with db.info['browser_lock']:
        points=table('measurement_points')
        first_points=list(db.execute(select(points.c.point_id).where(points.c.measurement_id==mids[0]).order_by(points.c.point_no)).scalars())
        db.execute(points.update().where(points.c.point_id==first_points[2]).values(is_outlier=True))
    calculated=post(client,actors,{'sources':[{'kind':'measurement','id':mid} for mid in mids]}).json()['data']
    means={s['source']['id']:float(s['statistics']['thickness_nm']['mean']) for s in calculated['series']}
    p.goto(BASE+'/analysis')
    for code in codes:p.get_by_label('纳入 '+code,exact=True).check()
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click()
    canvas=p.get_by_test_id('echarts-canvas');expect(canvas).to_have_attribute('data-rendered-count','85')
    p.get_by_label('分析图形',exact=True).select_option('trend');p.get_by_label('图例分组',exact=True).select_option('model')
    expect(canvas).to_have_attribute('data-rendered-count','2')
    def plotted():return json.loads(canvas.get_attribute('data-plot-series'))
    p.wait_for_function("JSON.parse(document.querySelector('[data-testid=echarts-canvas]').dataset.plotSeries).length===1")
    data=plotted();assert len(data)==1;assert [v['value'] for v in data[0]['data']]==[[10,means[mids[1]]],[30,means[mids[0]]]]
    for axis,xs in [('cumulative_cycles',[50,90]),('full_ale_cycles',[7,7]),('r1_temp_c',[150,250])]:
        p.get_by_label('趋势横轴',exact=True).select_option(axis)
        p.wait_for_function('(xs)=>JSON.parse(document.querySelector("[data-testid=echarts-canvas]").dataset.plotSeries)[0].data.map(p=>p.value[0]).join(",")===xs',arg=','.join(map(str,xs)))
    p.get_by_label('图例分组',exact=True).select_option('stage')
    p.wait_for_function("JSON.parse(document.querySelector('[data-testid=echarts-canvas]').dataset.plotSeries)[0].name.includes('阶段')")
    assert len(plotted())==1
    screenshot(p,'round7-analysis-final-trend.png')
    p.get_by_label('分析图形',exact=True).select_option('scatter');p.get_by_label('图例分组',exact=True).select_option('model')
    expect(canvas).to_have_attribute('data-rendered-count','85');assert len(plotted())==1
    # Exclusion stays a null in the explicit point-order line; outlier stays on same line.
    p.get_by_label('纳入 '+codes[1],exact=True).uncheck()
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click();expect(canvas).to_have_attribute('data-rendered-count','4')
    p.locator('summary').first.click();p.get_by_label('排除 0:1',exact=True).check();p.get_by_label('分析排除理由',exact=True).fill('人工核查保留断线')
    p.get_by_role('button',name='按当前选择计算并绘图',exact=True).click();expect(canvas).to_have_attribute('data-rendered-count','3')
    p.get_by_label('分析图形',exact=True).select_option('line');p.get_by_label('分析横轴',exact=True).select_option('point_no')
    p.wait_for_function("JSON.parse(document.querySelector('[data-testid=echarts-canvas]').dataset.plotSeries)[0].type==='line'")
    assert len(plotted()[0]['data'])==4 and plotted()[0]['data'][1]['value'][1] is None
    assert plotted()[0]['data'][2]['symbol']=='diamond' and plotted()[0]['data'][2]['value'][1] is not None
    p.get_by_label('分析横轴',exact=True).select_option('x_mm')
    p.wait_for_timeout(100)
    xs=[d['value'][0] for d in plotted()[0]['data']];assert xs==sorted(xs)
    p.get_by_label('分析横轴',exact=True).select_option('point_no')
    p.get_by_label('保存分析名称',exact=True).fill('均值与依赖验证');p.get_by_role('button',name='显式保存分析记录',exact=True).click()
    saved=p.get_by_test_id('saved-analysis-record');expect(saved).to_contain_text('来源有效性：有效');expect(saved).to_contain_text('0:1');expect(saved).to_contain_text('人工核查保留断线')
    with db.info['browser_lock']:db.execute(process.update().where(process.c.process_id==pids[0]).values(r1_temp_c=251))
    p.get_by_role('button',name='重新读取此保存结果并检查来源',exact=True).click();expect(saved).to_contain_text('来源有效性：已失效')
    print('MEAN_TREND actual 4/81 files = 2 means; sorted recorded cycles [10,30], cumulative [50,90], full ALE [7,7], temperatures [150,250]; model grouping real; excluded point null gap; saved recipe reopened, process change invalidates')
