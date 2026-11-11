"""Round-five real MySQL/Uvicorn/Chromium acceptance; every write rolls back.
Run from backend: ALE_BROWSER_TEST=1 LD_LIBRARY_PATH=/tmp/libs2/usr/lib/x86_64-linux-gnu python3 -m pytest tests/test_phase5_browser.py -v -s
"""
import hashlib
import os
import shutil
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select

from app.config import ROOT
from app.db import table
from test_phase4_browser import db, client, world, locked, field, select_option, pick_samples, in_view
from test_phase3_imports import workbook

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8023'


@pytest.fixture
def ui(client, actors, db, world, tmp_path, monkeypatch):
    import uvicorn
    from app.main import app
    root = tmp_path / 'phase5-originals'
    monkeypatch.setenv('ALE_ORIGINALS_ROOT', str(root))
    servers = []

    def start():
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8023, log_level='error', access_log=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(150):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        servers.append((server, thread))

    def stop():
        server, thread = servers.pop()
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive(), 'Old Uvicorn thread still alive'

    def restart():
        stop()
        start()
        print('RESTART VERIFIED: old Uvicorn stopped/joined; new Uvicorn started on same port (same app and rollback connection)')

    start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width':1440,'height':1000}, accept_downloads=True)
            p = context.new_page()
            p.set_default_timeout(10000)
            errors, responses = [], []
            p.on('pageerror', lambda e: errors.append(str(e)))
            p.on('response', lambda r: responses.append((r.request.method, r.url.split('/api/v1/')[-1], r.status)) if '/api/v1/' in r.url else None)
            state = dict(page=p,context=context,client=client,actors=actors,db=db,world=world,errors=errors,responses=responses,restart=restart)
            try:
                yield state
            finally:
                if errors:
                    p.screenshot(path=str(ROOT/'reports/screenshots/phase5-js-error.png'), full_page=True)
                print('JS ERRORS:', errors)
                print('HTTP EVIDENCE:', [r for r in responses if r[0]!='GET' or r[2]>=400])
                context.close()
                browser.close()
                assert not errors
    finally:
        while servers:
            stop()
        if root.exists():
            shutil.rmtree(root)
        print('TEMPORARY ORIGINALS REMOVED:', not root.exists())


def login(ui):
    p=ui['page'];p.goto(BASE+'/login')
    p.get_by_label('用户名',exact=True).fill(ui['actors']['operator']['user']['username'])
    p.get_by_label('密码',exact=True).fill('TestPassword123!')
    p.get_by_role('button',name='登录工作台',exact=True).click()
    p.get_by_role('heading',name='工作台概览',exact=True).wait_for()


def capture(ui,name):
    p=ui['page'];p.wait_for_timeout(400)
    size=p.evaluate('({viewport:innerWidth,body:document.body.scrollWidth,document:document.documentElement.scrollWidth})')
    p.screenshot(path=str(ROOT/'reports/screenshots'/f'phase5-{p.viewport_size["width"]}-{name}.png'),full_page=True)
    assert max(size['body'],size['document'])<=size['viewport']+1,(name,size)
    print('LAYOUT OK:',name,size)


def api_data(ui,path):
    r=ui['client'].get('/api/v1'+path,headers=ui['actors']['operator']['headers'])
    assert r.status_code==200,r.text
    return r.json()['data']


def save_step(ui,dialog,endpoint):
    p=ui['page']
    with p.expect_response(lambda r: r.request.method in ('POST','PATCH') and r.url.endswith(endpoint)) as response:
        dialog.get_by_role('button',name='保存',exact=True).click()
    assert response.value.status in (200,201),response.value.text()
    dialog.wait_for(state='hidden')
    return response.value.json()['data']


@pytest.mark.parametrize('width,height',[(1440,1000),(390,844)],ids=['desktop','narrow'])
def test_phase5_named_creation_snapshots_restart_bind_archive_delete(ui,width,height):
    p,w,db=ui['page'],ui['world'],ui['db'];p.set_viewport_size({'width':width,'height':height})
    tool=table('tools')
    tid=db.execute(tool.insert().values(tool_code=f'P5T-{w["tag"]}',tool_name='第五轮真实设备',tool_type='other')).inserted_primary_key[0]
    login(ui);p.goto(BASE+'/plans')
    p.get_by_role('button',name='新建实验计划',exact=True).click()
    drawer=p.locator('.el-drawer').filter(has_text='创建实验计划');drawer.wait_for()
    field(ui,drawer,'计划编码').fill(f'P5P-{w["tag"]}')
    field(ui,drawer,'计划标题').fill('第五轮命名选择器计划')
    select_option(ui,field(ui,drawer,'批次（可空）'),w['batch_code'])
    assert drawer.locator('label').filter(has_text='批次 ID').count()==0
    capture(ui,'plan-named-batch')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/plans')) as created:
        drawer.get_by_role('button',name='保存实验计划',exact=True).click()
    assert created.value.status==201,created.value.text()
    plan=created.value.json()['data'];plan_id=plan['plan_id'];assert plan['batch_id']==w['batch_id']
    drawer.wait_for(state='hidden')
    # Round 8: the only step editor is the grid dialog (the vertical parameter form is gone).
    # Open the new plan explicitly instead of relying on URL state after creation.
    p.goto(BASE+f'/plans?plan_id={plan_id}')
    p.get_by_test_id('edit-process-grid').click()
    dialog=p.get_by_role('dialog',name='计划流程网格',exact=True);dialog.wait_for()
    assert dialog.get_by_test_id('parameter-groups-editor').count()==0
    dialog.get_by_role('button',name='添加步骤列',exact=True).first.click()
    expect(dialog.get_by_label('步骤列名称',exact=True)).to_have_count(1)
    dialog.get_by_label('步骤列名称',exact=True).first.fill('自由暴露步骤')
    dialog.get_by_label('步骤列分类',exact=True).first.fill('自由暴露步骤')
    cell=dialog.get_by_label('自由暴露步骤 温度 温度 值',exact=True);cell.fill('175.25')
    dialog.get_by_label('自由暴露步骤 源 名称 值',exact=True).fill('自由前驱体')
    dialog.get_by_label('自由暴露步骤 脉冲 时长 值',exact=True).fill('12.50')
    dialog.get_by_label('自由暴露步骤 脉冲 时长 单位',exact=True).fill('ms')
    dialog.get_by_label('自由暴露步骤 吹扫 时长 值',exact=True).fill('0.75')
    dialog.get_by_label('自定义参数行名称',exact=True).fill('信号')
    dialog.get_by_role('button',name='添加参数行',exact=True).click()
    dialog.get_by_label('自由暴露步骤 自定义 信号 值',exact=True).fill('7.125')
    dialog.get_by_label('自由暴露步骤 自定义 信号 单位',exact=True).fill('arb')
    template_name=f'P5模板-{w["tag"]}'
    bar=dialog.get_by_test_id('grid-template-bar')
    target=bar.get_by_label('模板目标列',exact=True)
    target.select_option(label=next(t for t in target.locator('option').all_text_contents() if t.endswith('自由暴露步骤')))
    bar.get_by_label('模板名称',exact=True).fill(template_name)
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/step-parameter-templates')) as saved:
        bar.get_by_role('button',name='另存为当前列为模板',exact=True).click()
    assert saved.value.status==201,saved.value.text()
    template=saved.value.json()['data'];original=template['definition']
    capture(ui,'generic-template-saved')
    with p.expect_response(lambda r:r.request.method=='PUT' and r.url.endswith('/process-grid')) as savedgrid:
        dialog.get_by_test_id('save-process-grid').click()
    assert savedgrid.value.status==200,savedgrid.value.text();dialog.wait_for(state='hidden')
    plan=api_data(ui,f'/plans/{plan_id}');step_id=plan['steps'][0]['step_id']
    assert plan['steps'][0]['parameter_snapshot']==original

    # Reopening the grid shows the persisted snapshot; the saved template is selectable.
    p.reload();p.get_by_test_id('edit-process-grid').click();dialog=p.get_by_role('dialog',name='计划流程网格',exact=True);dialog.wait_for()
    expect(dialog.get_by_label('自由暴露步骤 脉冲 时长 值',exact=True)).to_have_value('12.50')
    expect(dialog.get_by_label('自由暴露步骤 脉冲 时长 单位',exact=True)).to_have_value('ms')
    bar=dialog.get_by_test_id('grid-template-bar')
    expect(bar.get_by_label('参数模板',exact=True).locator(f'option[value="{template["template_id"]}"]')).to_have_text(template_name)
    dialog.get_by_role('button',name='取消',exact=True).click()

    ui['restart']();p.reload()
    p.goto(BASE+f'/plans?plan_id={plan_id}')
    p.get_by_test_id('step-summary-list').wait_for()
    expect(p.get_by_test_id('step-summary-list')).to_contain_text('自由暴露步骤')
    p.get_by_role('button',name='选样品并创建执行',exact=True).click()
    p.get_by_test_id('plan-inherit-note').wait_for()
    drawer=p.locator('.el-drawer').filter(has_text='创建实验执行')
    field(ui,drawer,'执行编码').fill(f'P5R-{w["tag"]}')
    select_option(ui,field(ui,drawer,'设备（可空）'),f'P5T-{w["tag"]}')
    for forbidden in ['执行模式','关联计划 ID','批次 ID','设备 ID','O₃','HF','TMA']:
        assert drawer.locator('.el-form-item__label').filter(has_text=forbidden).count()==0,forbidden
    expect(drawer).to_contain_text(w['batch_code'])
    expect(drawer).to_contain_text(f'P5P-{w["tag"]}')
    pick_samples(ui,w['coupon_codes'][:1])
    drawer.locator('.el-drawer__header').click()
    p.wait_for_timeout(300)
    # Inherited actual step: structure and units come from the plan, values stay empty.
    drawer.get_by_test_id('create-process-grid').click()
    grid=p.get_by_role('dialog',name='实际流程网格',exact=True);grid.wait_for()
    expect(grid.get_by_label('步骤列名称',exact=True).first).to_have_value('自由暴露步骤')
    assert grid.get_by_label('自由暴露步骤 温度 温度 值',exact=True).input_value()==''
    assert grid.get_by_label('自由暴露步骤 脉冲 时长 值',exact=True).input_value()==''
    expect(grid.get_by_label('自由暴露步骤 脉冲 时长 单位',exact=True)).to_have_value('ms')
    grid.get_by_label('自由暴露步骤 温度 温度 值',exact=True).fill('180')
    grid.get_by_label('自由暴露步骤 脉冲 时长 值',exact=True).fill('33.00')
    capture(ui,'independent-actual-grid')
    grid.get_by_test_id('save-process-grid').click();grid.wait_for(state='hidden')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/processes')) as made:
        drawer.get_by_role('button',name='保存实验执行',exact=True).click()
    assert made.value.status==201,made.value.text()
    run=made.value.json()['data'];pid=run['process_id'];drawer.wait_for(state='hidden')
    assert run['tool_id']==tid and run['plan_id']==plan_id and run['batch_id']==w['batch_id']
    actual=run['steps'][0]['parameter_snapshot'];assert actual['temperature']['value']=='180'
    assert actual['groups'][1]['fields'][0]['value']=='33.00'
    assert run['steps'][0]['plan_step_id']==step_id
    assert api_data(ui,f'/plans/{plan_id}')['steps'][0]['parameter_snapshot']==original
    assert api_data(ui,f'/step-parameter-templates/{template["template_id"]}')['definition']['groups'][1]['fields'][0]['value']=='12.50'
    ui['restart']();p.reload();p.goto(BASE+f'/processes?process_id={pid}')
    p.get_by_test_id('batch-bind-open').click();bind=p.get_by_test_id('batch-bind-dialog');bind.wait_for()
    pick_samples(ui,w['coupon_codes'][1:3]);field(ui,bind,'腔体位置').fill('P5-CH')
    for forbidden in ['O₃','HF','TMA']:
        assert bind.locator('.el-form-item__label').filter(has_text=forbidden).count()==0
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/samples/batch')) as bound:
        bind.get_by_test_id('batch-bind-submit').click()
    assert bound.value.status==201,bound.value.text();bind.wait_for(state='hidden')
    assert len(api_data(ui,f'/processes/{pid}')['samples'])==3
    assert api_data(ui,f'/processes/{pid}')['steps'][0]['parameter_snapshot']==actual
    capture(ui,'persisted-bindings')
    with p.expect_response(lambda r:r.request.method=='DELETE' and '/processes/' in r.url) as denied:
        p.locator('.detail-title').get_by_role('button',name='删除',exact=True).click()
        p.locator('.el-message-box').get_by_role('button',name='确认删除',exact=True).click()
    assert denied.value.status==409,denied.value.text()
    p.get_by_text('删除失败：',exact=False).wait_for()
    capture(ui,'delete-dependency-feedback')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/archive')) as archived:
        p.get_by_test_id('plan-archive').click()
        p.locator('.el-message-box').get_by_role('button',name='确认归档',exact=True).click()
    assert archived.value.status==200,archived.value.text()
    final=api_data(ui,f'/processes/{pid}')
    assert final['archived_at'] and len(final['samples'])==3 and final['steps'][0]['parameter_snapshot']==actual
    p.reload();p.get_by_role('button',name='编辑基本信息',exact=True).wait_for()
    assert p.get_by_test_id('plan-archive').count()==0
    # Empty process can be physically deleted, unlike the history-bearing execution.
    p.get_by_role('button',name='新建实验执行',exact=True).click();drawer.wait_for()
    field(ui,drawer,'执行编码').fill(f'P5EMPTY-{w["tag"]}')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/processes')) as empty:
        drawer.get_by_role('button',name='保存实验执行',exact=True).click()
    assert empty.value.status==201,empty.value.text();drawer.wait_for(state='hidden')
    eid=empty.value.json()['data']['process_id']
    with p.expect_response(lambda r:r.request.method=='DELETE' and r.url.split('?')[0].endswith(f'/processes/{eid}')) as deleted:
        p.locator('.detail-title').get_by_role('button',name='删除',exact=True).click()
        p.locator('.el-message-box').get_by_role('button',name='确认删除',exact=True).click()
    assert deleted.value.status in (200,204),deleted.value.text()
    assert locked(db,select(table('processes')).where(table('processes').c.process_id==eid))==[]
    capture(ui,'empty-process-deleted')
    print('ROUND5 VERIFIED: named batch/plan/tool; grid snapshot 12.50→actual33.00; reload+2 Uvicorn restarts; bind3; dependency409; archive history; empty delete')

@pytest.mark.parametrize('width,height',[(1440,1000),(390,844)],ids=['desktop','narrow'])
def test_phase5_import_original_only_delete_and_required_stage(ui,width,height):
    p,db,w=ui['page'],ui['db'],ui['world'];p.set_viewport_size({'width':width,'height':height});login(ui)
    files=[('unknown.bin',b'unknown\x00\xff'+w['tag'].encode()),('test.rga',b'RGA\x00\xff'+w['tag'].encode()),('xps.xml',b'<Chart><Series/></Chart>')]
    before=len(locked(db,select(table('measurements'))));points=len(locked(db,select(table('measurement_points'))))
    job=upload(ui,files)
    for item in job['items']:
        card=p.get_by_test_id(f'import-item-{item["item_id"]}')
        card.get_by_test_id(f'select-item-{item["item_id"]}').check()
        select_option(ui,card.get_by_test_id(f'action-{item["item_id"]}'),'仅保存原件')
        p.wait_for_timeout(300)
        assert card.get_by_role('combobox',name=item['filename']+'样品',exact=True).count()==0
        assert card.get_by_test_id('import-stage').count()==0
        expect(card).to_contain_text('不关联样品')
    capture(ui,'original-only-unassociated')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/confirm')) as confirmed:
        p.get_by_role('button',name='下一步：确认提交',exact=True).click()
        p.get_by_test_id('import-step3-submit').click()
    assert confirmed.value.status==200,confirmed.value.text()
    result=confirmed.value.json()['data'];p.get_by_test_id('confirm-results').wait_for()
    assert len(locked(db,select(table('measurements'))))==before
    assert len(locked(db,select(table('measurement_points'))))==points
    assert result['pending_count']==0
    for item in result['items']:
        sid=item['source_file_id'];row=locked(db,select(table('source_files')).where(table('source_files').c.file_id==sid))[0]
        assert row['sample_id'] is None and row['parse_status']=='pending'
        assert all(r['sample_id'] is None for r in locked(db,select(table('source_file_occurrences')).where(table('source_file_occurrences').c.source_file_id==sid)))
        expected=dict(files)[next(i['filename'] for i in job['items'] if i['item_id']==item['item_id'])]
        p.goto(BASE+f'/source-files?id={sid}');p.get_by_test_id('source-detail').wait_for()
        with p.expect_download() as downloaded:p.get_by_test_id('source-detail-download').click()
        actual=Path(downloaded.value.path()).read_bytes()
        assert actual==expected and hashlib.sha256(actual).hexdigest()==row['file_sha256']
        print('ORIGINAL SHA MATCH:',row['file_sha256'],'bytes',len(actual),'sample=NULL parse_status=pending')
    capture(ui,'original-download-sha')
    pending=upload(ui,[('delete-me.dat',b'pending-delete-'+w['tag'].encode())])
    with p.expect_response(lambda r:r.request.method=='DELETE' and r.url.endswith(f'/imports/{pending["job_id"]}?expected_row_version=1')) as deleted:
        p.get_by_role('button',name='删除暂存任务',exact=True).click()
        p.locator('.el-message-box').get_by_role('button',name='删除任务',exact=True).click()
    assert deleted.value.status==200,deleted.value.text()
    p.get_by_test_id('import-files').wait_for()
    assert locked(db,select(table('import_jobs')).where(table('import_jobs').c.job_id==pending['job_id']))==[]
    capture(ui,'pending-task-deleted')
    job=upload(ui,[('stage-required.xlsx',workbook())]);item=job['items'][0];iid=item['item_id']
    card=p.get_by_test_id(f'import-item-{iid}');card.get_by_test_id(f'select-item-{iid}').check()
    card.get_by_test_id(f'action-{iid}').click();p.get_by_role('option',name='导入正式测量',exact=True).click()
    control=card.get_by_role('combobox',name=item['filename']+'样品',exact=True)
    control.fill(w['coupon_codes'][0]);p.wait_for_timeout(700)
    p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=w['coupon_codes'][0]).first.click()
    expect(card.get_by_label('阶段序号',exact=True)).to_have_value('')
    p.get_by_role('button',name='下一步：确认提交',exact=True).click();feedback=card.get_by_test_id(f'readiness-errors-{iid}');feedback.wait_for()
    expect(feedback).to_contain_text(item['filename']+'：请选择测量阶段')
    expect(feedback).to_contain_text('请填写阶段序号')
    expect(p.get_by_test_id('import-step3-submit')).to_have_count(0)
    expect(card.get_by_role('combobox',name='测量阶段',exact=True)).to_be_focused()
    capture(ui,'required-stage-feedback')
    assert len(locked(db,select(table('measurements'))))==before
    print('ROUND5 IMPORT VERIFIED: unknown/RGA/XPS original-only no associations; 3 SHA downloads; measurements/points unchanged; pending task delete; stage required feedback')



@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)], ids=['desktop','narrow'])
def test_phase5_import_before_confirm_readiness_and_recovery(ui,width,height):
    p,db,w=ui['page'],ui['db'],ui['world']
    p.set_viewport_size({'width':width,'height':height});login(ui)
    before=len(locked(db,select(table('measurements'))))
    job=upload(ui,[('first-needs-review.xlsx',workbook()),('unselected-kept.xlsx',workbook())])
    item=job['items'][0];iid=item['item_id'];other=job['items'][1]['item_id']
    card=p.get_by_test_id(f'import-item-{iid}')
    card.get_by_test_id(f'select-item-{iid}').check()
    select_option(ui,card.get_by_test_id(f'action-{iid}'),'导入正式测量')
    card.get_by_label('导入备注',exact=True).fill('保留人工核对内容')
    start=len(ui['responses'])
    p.get_by_role('button',name='下一步：确认提交',exact=True).click()
    errors=card.get_by_test_id(f'readiness-errors-{iid}')
    expect(errors).to_contain_text(item['filename']+'：请选择样品')
    expect(errors).to_contain_text(item['filename']+'：请选择测量阶段')
    expect(errors).to_contain_text(item['filename']+'：请填写阶段序号')
    sample=card.get_by_role('combobox',name=item['filename']+'样品',exact=True)
    expect(sample).to_be_focused()
    in_view(ui,f'[data-testid="import-item-{iid}"] [data-readiness-field="sample"]')
    expect(p.get_by_test_id('import-step3-submit')).to_have_count(0)
    expect(p.get_by_test_id(f'readiness-errors-{other}')).to_have_count(0)
    expect(card.get_by_label('导入备注',exact=True)).to_have_value('保留人工核对内容')
    capture(ui,'before-confirm-missing-sample')
    sample.fill(w['coupon_codes'][0]);p.wait_for_timeout(700)
    p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=w['coupon_codes'][0]).first.click()
    p.wait_for_timeout(400)
    # Top step navigation must enforce the same readiness check as Next.
    p.get_by_test_id('import-confirm-step').click()
    stage=card.get_by_role('combobox',name='测量阶段',exact=True)
    expect(stage).to_be_focused()
    in_view(ui,f'[data-testid="import-item-{iid}"] [data-readiness-field="stage"]')
    expect(p.get_by_test_id('import-step3-submit')).to_have_count(0)
    expect(card.get_by_label('阶段序号',exact=True)).to_have_value('')
    expect(card.get_by_test_id('stage-sequence-help')).to_contain_text('不是文件顺序或工艺循环次数')
    select_option(ui,card.get_by_test_id('import-stage'),'初始')
    p.get_by_role('button',name='下一步：确认提交',exact=True).click()
    sequence=card.get_by_label('阶段序号',exact=True)
    expect(sequence).to_be_focused()
    in_view(ui,f'[data-testid="import-item-{iid}"] [data-readiness-field="sequence"]')
    expect(errors).to_contain_text('请填写阶段序号')
    capture(ui,'before-confirm-missing-sequence')
    sequence.fill('-1')
    p.get_by_role('button',name='下一步：确认提交',exact=True).click()
    expect(errors).to_contain_text('阶段序号须为 0–4294967295 整数')
    expect(sequence).to_be_focused()
    sequence.fill('0')
    card.get_by_test_id(f'units-{iid}').check();card.get_by_test_id(f'associations-{iid}').check()
    expect(errors).to_have_count(0)
    assert all(r[0]!='POST' or not r[1].endswith('/confirm') for r in ui['responses'][start:])
    assert len(locked(db,select(table('measurements'))))==before
    p.get_by_role('button',name='下一步：确认提交',exact=True).click()
    expect(p.get_by_test_id('import-step3-submit')).to_be_visible()
    p.get_by_role('button',name='返回核对',exact=True).click()
    expect(card.get_by_label('导入备注',exact=True)).to_have_value('保留人工核对内容')
    expect(sequence).to_have_value('0')
    expect(card.get_by_test_id(f'units-{iid}')).to_be_checked()
    expect(card.get_by_test_id(f'associations-{iid}')).to_be_checked()
    p.get_by_role('button',name='下一步：确认提交',exact=True).click()
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/confirm')) as confirmed:
        p.get_by_test_id('import-step3-submit').click()
        p.locator('.el-message-box').get_by_role('button',name='确认所选并提交',exact=True).click()
    assert confirmed.value.status==200,confirmed.value.text()
    assert len(confirmed.value.request.post_data_json['items'])==1
    request=confirmed.value.request.post_data_json['items'][0]
    assert request['stage']=='initial' and request['stage_seq']==0 and request['notes']=='保留人工核对内容'
    p.get_by_test_id('confirm-results').wait_for()
    assert len(locked(db,select(table('measurements'))))==before+1
    final=api_data(ui,f'/imports/{job["job_id"]}')
    assert next(i for i in final['items'] if i['item_id']==other)['status']=='pending'
    capture(ui,'before-confirm-recovered')
    print('READINESS VERIFIED: missing sample/stage/sequence blocked before confirmation; both navigation entries; filename Chinese errors; actual focus + viewport; invalid sequence; no confirm POST; selected choices/notes retained; explicit initial/0 recovery POST200; unselected item pending')

def batch_login(ui, role):
    p = ui['page']
    ui['context'].clear_cookies()
    p.goto(BASE + '/login')
    p.get_by_label('用户名', exact=True).fill(ui['actors'][role]['user']['username'])
    p.get_by_label('密码', exact=True).fill('TestPassword123!')
    p.get_by_role('button', name='登录工作台', exact=True).click()
    p.get_by_role('heading', name='工作台概览', exact=True).wait_for()


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)], ids=['desktop', 'narrow'])
def test_phase5_batch_archive_dependency_feedback(ui, width, height):
    p, w = ui['page'], ui['world']
    p.set_viewport_size({'width': width, 'height': height})
    batch_login(ui, 'admin')
    p.goto(BASE + '/batches')
    p.get_by_role('textbox', name='搜索关键词').fill(w['batch_code'])
    p.get_by_role('button', name='查询', exact=True).click()
    row = p.locator('.el-table__body tr').filter(has_text=w['batch_code'])
    expect(row).to_have_count(1)
    expect(row.get_by_test_id('batch-archive')).to_be_visible()
    with p.expect_response(lambda r: r.request.method == 'DELETE' and r.url.endswith(f'/batches/{w["batch_id"]}')) as denied:
        row.get_by_role('button', name='删除', exact=True).click()
        p.locator('.el-message-box').get_by_role('button', name='确认删除', exact=True).click()
    assert denied.value.status == 409, denied.value.text()
    panel = p.get_by_test_id('records-action-feedback')
    expect(panel).to_contain_text('样品 7 条')
    expect(panel).to_contain_text('实验计划 1 条')
    expect(panel.get_by_test_id('batch-archive-shortcut')).to_be_visible()
    p.wait_for_timeout(3200)
    expect(panel).to_be_visible()
    capture(ui, 'batch-delete-dependencies')
    before = api_data(ui, f'/batches/{w["batch_id"]}')
    samples = api_data(ui, f'/batches/{w["batch_id"]}/samples')
    plan = api_data(ui, f'/plans/{w["plan"]}')
    panel.get_by_test_id('batch-archive-shortcut').click()
    confirm = p.locator('.el-message-box')
    expect(confirm).to_contain_text('全部历史关联')
    expect(confirm).to_contain_text('业务状态保持不变')
    confirm.get_by_role('button', name='取消', exact=True).click()
    assert not api_data(ui, f'/batches/{w["batch_id"]}')['archived_at']
    panel.get_by_test_id('batch-archive-shortcut').click()
    confirm.get_by_role('button', name='确认归档', exact=True).wait_for()
    # A concurrent edit after the detail read must produce a visible CAS error.
    response = ui['client'].patch(f'/api/v1/batches/{w["batch_id"]}', headers=ui['actors']['operator']['headers'],
                                  json={'expected_row_version': before['row_version'], 'notes': 'concurrent edit'})
    assert response.status_code == 200, response.text
    with p.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/archive')) as stale:
        confirm.get_by_role('button', name='确认归档', exact=True).click()
    assert stale.value.status == 409
    assert stale.value.request.post_data_json == {'expected_row_version': before['row_version']}
    expect(panel).to_contain_text('归档失败')
    expect(panel).to_contain_text('重新读取版本')
    p.wait_for_timeout(3200)
    expect(panel).to_be_visible()
    capture(ui, 'batch-archive-cas-feedback')
    with p.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/archive')) as archived:
        panel.get_by_test_id('batch-archive-shortcut').click()
        confirm.get_by_role('button', name='确认归档', exact=True).click()
    assert archived.value.status == 200, archived.value.text()
    assert archived.value.request.post_data_json == {'expected_row_version': before['row_version'] + 1}
    expect(panel).to_contain_text('已归档')
    expect(panel.get_by_test_id('batch-archive-shortcut')).to_have_count(0)
    expect(row.get_by_test_id('batch-archived-badge')).to_be_visible()
    expect(row.get_by_test_id('batch-archive')).to_have_count(0)
    p.wait_for_timeout(3200)
    expect(panel).to_be_visible()
    capture(ui, 'batch-archive-success')
    final = api_data(ui, f'/batches/{w["batch_id"]}')
    assert final['archived_at'] and final['status'] == before['status']
    assert final['row_version'] == before['row_version'] + 2
    assert api_data(ui, f'/batches/{w["batch_id"]}/samples') == samples
    final_plan = api_data(ui, f'/plans/{w["plan"]}')
    assert {k: v for k, v in final_plan.items() if k != 'batch'} == {k: v for k, v in plan.items() if k != 'batch'}
    assert final_plan['batch']['batch_id'] == plan['batch']['batch_id']
    p.goto(BASE + f'/batches?batch_id={w["batch_id"]}')
    drawer = p.locator('.records-drawer')
    expect(drawer.get_by_test_id('batch-detail-archived-badge')).to_be_visible()
    expect(drawer.get_by_test_id('batch-detail-archive')).to_have_count(0)
    expect(drawer).to_contain_text('归档时间')
    expect(drawer).to_contain_text('进行中')
    p.reload()
    expect(drawer.get_by_test_id('batch-detail-archived-badge')).to_be_visible()
    capture(ui, 'batch-archived-detail-reload')
    print('BATCH ARCHIVE VERIFIED: admin non-owner; dependency DELETE409 samples7/plans1 durable; cancel no write; concurrent CAS409 durable; retry fresh version POST200; success durable; status active; samples and plan identical; list/detail badges and reload')


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)], ids=['desktop', 'narrow'])
def test_phase5_batch_archive_owner_viewer_other_permissions(ui, width, height):
    p, w, db = ui['page'], ui['world'], ui['db']
    p.set_viewport_size({'width': width, 'height': height})
    login(ui)
    p.goto(BASE + f'/batches?batch_id={w["batch_id"]}')
    drawer = p.locator('.records-drawer')
    expect(drawer.get_by_test_id('batch-detail-archive')).to_be_visible()
    expect(p.get_by_role('button', name='删除', exact=True)).to_have_count(0)
    with p.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/archive')) as archived:
        drawer.get_by_test_id('batch-detail-archive').click()
        p.locator('.el-message-box').get_by_role('button', name='确认归档', exact=True).click()
    assert archived.value.status == 200
    expect(drawer.get_by_test_id('records-detail-feedback')).to_contain_text('已归档')
    expect(drawer.get_by_test_id('batch-detail-archived-badge')).to_be_visible()
    capture(ui, 'batch-owner-archive')
    # The same owner as viewer still sees the record, but cannot archive it.
    users = table('users')
    with db.info['browser_lock']:
        db.execute(users.update().where(users.c.user_id == w['user']).values(role='viewer'))
    batch_login(ui, 'operator')
    p.goto(BASE + f'/batches?batch_id={w["batch_id"]}')
    expect(drawer.get_by_test_id('batch-detail-archived-badge')).to_be_visible()
    expect(drawer.get_by_test_id('batch-detail-archive')).to_have_count(0)
    expect(drawer.get_by_role('button', name='编辑档案', exact=True)).to_have_count(0)
    # Also inspect an unarchived owned record: role, not archived_at, hides the action.
    with db.info['browser_lock']:
        bid = db.execute(table('batches').insert().values(batch_code=f'P5VIEW-{w["tag"]}', batch_name='只读未归档', owner_user_id=w['user'])).inserted_primary_key[0]
    p.goto(BASE + f'/batches?batch_id={bid}')
    expect(drawer.locator('h2')).to_have_text(f'P5VIEW-{w["tag"]}')
    start = len(ui['responses'])
    expect(drawer.get_by_test_id('batch-detail-archive')).to_have_count(0)
    expect(p.get_by_test_id('batch-archive')).to_have_count(0)
    capture(ui, 'batch-viewer-readonly')
    assert all(r[0] == 'GET' for r in ui['responses'][start:])
    current = ui['client'].get('/api/v1/auth/me', headers=ui['actors']['operator']['headers'])
    assert current.status_code == 200 and current.json()['data']['user']['role'] == 'viewer'
    denied = ui['client'].post(f'/api/v1/batches/{bid}/archive', headers=ui['actors']['operator']['headers'], json={'expected_row_version': 1})
    assert denied.status_code == 403, denied.text
    batch_login(ui, 'other')
    p.goto(BASE + f'/batches?batch_id={bid}')
    expect(drawer).to_contain_text('档案加载失败')
    expect(drawer.get_by_test_id('batch-detail-archive')).to_have_count(0)
    denied = ui['client'].post(f'/api/v1/batches/{bid}/archive', headers=ui['actors']['other']['headers'], json={'expected_row_version': 1})
    assert denied.status_code == 404, denied.text
    print('BATCH PERMISSIONS VERIFIED: owner operator POST200; admin non-owner covered separately; own viewer unarchived UI no action/no writes + POST403; other operator hidden detail + POST404')


@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)], ids=['desktop','narrow'])
def test_phase5_clear_plan_discards_inherited_drafts_before_creation(ui,width,height):
    p,w=ui['page'],ui['world'];p.set_viewport_size({'width':width,'height':height});login(ui)
    p.goto(BASE+f'/processes?create=1&plan_id={w["plan"]}&batch_id={w["batch_id"]}')
    drawer=p.locator('.el-drawer').filter(has_text='创建实验执行')
    expect(drawer.get_by_test_id('plan-inherit-note')).to_be_visible()
    # Round 8: inherited steps are listed read-only and edited only in the 2D grid.
    expect(drawer.locator('.field-hint').filter(has_text='映射计划步骤 #')).to_have_count(2)
    field(ui,drawer,'执行编码').fill(f'P5CLEAR-{w["tag"]}')
    control=drawer.locator('.el-form-item').filter(has=p.locator('.el-form-item__label',has_text='关联计划（可空）')).locator('.el-select')
    control.hover();control.locator('.el-select__clear').click()
    box=p.locator('.el-message-box');box.get_by_role('button',name='保留当前计划',exact=True).click()
    expect(control).to_contain_text(w['plan_code'])
    expect(drawer.locator('.field-hint').filter(has_text='映射计划步骤 #')).to_have_count(2)
    control.hover();control.locator('.el-select__clear').click()
    box.get_by_role('button',name='重建步骤',exact=True).click()
    expect(drawer.get_by_test_id('plan-inherit-note')).to_have_count(0)
    expect(drawer.locator('.field-hint').filter(has_text='映射计划步骤 #')).to_have_count(0)
    expect(drawer).to_contain_text('尚未添加实际步骤')
    # A fresh independent step is created in the same grid; it must carry no plan mapping.
    drawer.get_by_test_id('create-process-grid').click()
    grid=p.get_by_role('dialog',name='实际流程网格',exact=True);grid.wait_for()
    expect(grid.get_by_label('步骤列名称',exact=True)).to_have_count(0)
    grid.get_by_role('button',name='添加步骤列',exact=True).first.click()
    expect(grid.get_by_label('步骤列名称',exact=True)).to_have_count(1)
    grid.get_by_label('步骤列名称',exact=True).first.fill('清除计划后的独立步骤')
    grid.get_by_test_id('save-process-grid').click();grid.wait_for(state='hidden')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/processes')) as made:
        drawer.get_by_role('button',name='保存实验执行',exact=True).click()
    assert made.value.status==201,made.value.text()
    body=made.value.request.post_data_json;run=made.value.json()['data']
    assert body['plan_id'] is None and len(body['steps'])==1 and body['steps'][0]['plan_step_id'] is None
    assert run['plan_id'] is None and len(run['steps'])==1 and run['steps'][0]['plan_step_id'] is None
    drawer.wait_for(state='hidden')
    p.goto(BASE+f'/processes?process_id={run["process_id"]}');expect(p.locator('.experiment-detail')).to_contain_text('清除计划后的独立步骤')
    capture(ui,'clear-plan-created-independent')
    print('CLEAR PLAN VERIFIED: cancel restores plan and two drafts; confirm removes inherited drafts/note; independent step POST201 plan_id=NULL plan_step_id=NULL; detail persisted')


@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)], ids=['desktop','narrow'])
def test_phase5_binding_conflict_refresh_reconciles_and_retries(ui,width,height):
    p,w=ui['page'],ui['world'];p.set_viewport_size({'width':width,'height':height});login(ui)
    h=ui['actors']['operator']['headers']
    made=ui['client'].post('/api/v1/processes',headers=h,json={'process_code':f'P5CONFLICT-{w["tag"]}','process_mode':'other','batch_id':w['batch_id']})
    assert made.status_code==201,made.text
    pid=made.json()['data']['process_id'];endpoint=f'/processes/{pid}/samples/batch'
    p.goto(BASE+f'/processes?process_id={pid}');p.get_by_test_id('batch-bind-open').click()
    bind=p.get_by_test_id('batch-bind-dialog');pick_samples(ui,w['coupon_codes'][:2])
    bind.get_by_role('heading',name='批量绑定样品',exact=True).click()
    field(ui,bind,'腔体位置').fill('RECOVER-CH');field(ui,bind,'样品完整 ALE 循环数').fill('7')
    field(ui,bind,'样品角色备注').fill('冲突恢复保留备注')
    # A real concurrent API write binds one selected ID after the browser selected it.
    concurrent=ui['client'].post('/api/v1'+endpoint,headers=h,json={'sample_ids':w['coupons'][:1]})
    assert concurrent.status_code==201,concurrent.text
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith(endpoint)) as conflict:
        bind.get_by_test_id('batch-bind-submit').click()
    assert conflict.value.status==409,conflict.value.text()
    expect(bind.get_by_test_id('batch-bind-submit')).to_be_disabled()
    recover=bind.get_by_test_id('binding-conflict-recover');expect(recover).to_be_visible()
    # Failed recovery must not unlock submission or discard selections/attributes.
    detail_url=BASE+f'/api/v1/processes/{pid}'
    p.route(detail_url,lambda route:route.fulfill(status=503,content_type='application/json',body='{"message":"test refresh unavailable"}'),times=1)
    recover.click();expect(bind).to_contain_text('刷新失败')
    expect(bind.get_by_test_id('batch-bind-submit')).to_be_disabled()
    expect(field(ui,bind,'腔体位置')).to_have_value('RECOVER-CH')
    with p.expect_response(lambda r:r.request.method=='GET' and r.url==detail_url) as refreshed:
        recover.click()
    assert refreshed.value.status==200
    expect(recover).to_have_count(0)
    expect(bind).to_contain_text('移除 1 份已绑定样品')
    expect(field(ui,bind,'腔体位置')).to_have_value('RECOVER-CH')
    expect(field(ui,bind,'样品完整 ALE 循环数')).to_have_value('7')
    expect(field(ui,bind,'样品角色备注')).to_have_value('冲突恢复保留备注')
    expect(bind.get_by_test_id('sample-picker')).to_contain_text(w['coupon_codes'][1])
    expect(bind.get_by_test_id('sample-picker')).not_to_contain_text(w['coupon_codes'][0])
    expect(bind.get_by_test_id('batch-bind-submit')).to_be_enabled();capture(ui,'binding-conflict-reconciled')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith(endpoint)) as retried:
        bind.get_by_test_id('batch-bind-submit').click()
    assert retried.value.status==201,retried.value.text()
    assert retried.value.request.post_data_json['sample_ids']==w['coupons'][1:2]
    bind.wait_for(state='hidden');final=api_data(ui,f'/processes/{pid}')
    assert sorted(s['sample_id'] for s in final['samples'])==sorted(w['coupons'][:2])
    remaining=next(s for s in final['samples'] if s['sample_id']==w['coupons'][1])
    assert remaining['chamber_position']=='RECOVER-CH' and remaining['full_ale_cycles']==7 and remaining['sample_role_note']=='冲突恢复保留备注'
    capture(ui,'binding-conflict-retry-saved')
    print('BIND RECOVERY VERIFIED: real concurrent binding causes409; failed GET preserves lock/input; successful GET removes bound ID only and unlocks; retry sends remaining ID POST201 with attributes persisted')


@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)], ids=['desktop','narrow'])
def test_phase5_process_archived_badge_time_persist_independent_log(ui,width,height):
    p,w=ui['page'],ui['world'];p.set_viewport_size({'width':width,'height':height});login(ui)
    code=f'P5ARCHIVE-{w["tag"]}'
    made=ui['client'].post('/api/v1/processes',headers=ui['actors']['operator']['headers'],json={'process_code':code,'process_mode':'other','log_status':'partial','batch_id':w['batch_id']})
    assert made.status_code==201,made.text
    run=made.json()['data'];pid=run['process_id']
    p.goto(BASE+f'/processes?process_id={pid}')
    expect(p.get_by_test_id('process-detail-archived-badge')).to_have_count(0)
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith(f'/processes/{pid}/archive')) as archived:
        p.get_by_test_id('plan-archive').click();p.locator('.el-message-box').get_by_role('button',name='确认归档',exact=True).click()
    assert archived.value.status==200,archived.value.text()
    final=archived.value.json()['data'];assert final['archived_at'] and final['log_status']=='partial'
    expect(p.get_by_test_id('process-detail-archived-badge')).to_have_text('已归档')
    expect(p.get_by_test_id('process-archived-time')).to_contain_text(final['archived_at'])
    p.wait_for_timeout(3200);expect(p.get_by_test_id('process-detail-archived-badge')).to_be_visible()
    ui['restart']();p.reload()
    expect(p.get_by_test_id('process-detail-archived-badge')).to_be_visible()
    expect(p.get_by_test_id('process-archived-time')).to_contain_text(final['archived_at'])
    expect(p.get_by_test_id('plan-archive')).to_have_count(0)
    row=p.locator('.el-table__body tr').filter(has_text=code)
    expect(row.get_by_test_id('process-archived-badge')).to_have_text('已归档')
    expect(row).to_contain_text('日志：部分')
    capture(ui,'process-archive-badge-reloaded')
    reread=api_data(ui,f'/processes/{pid}');assert reread['archived_at']==final['archived_at'] and reread['log_status']=='partial'
    print('PROCESS ARCHIVE VERIFIED: POST200; durable list/detail badge + exact archived_at after toast expiry/restart/reload; log_status partial unchanged')
