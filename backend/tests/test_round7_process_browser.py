"""Real browser + MySQL; shared rollback fixtures verify original data manifests."""
import os
import threading
import time
import uuid
import pytest
from playwright.sync_api import expect, sync_playwright
from test_phase4_browser import db, client
from test_round7_process_grid import snapshot
from app.config import ROOT

pytestmark=pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST')!='1',reason='Opt-in browser acceptance')
BASE='http://127.0.0.1:8028'


def test_process_grid_save_reload_nested_units_generic_template(client,actors,db,monkeypatch,tmp_path):
    import uvicorn
    import app.main as main_module
    if os.getenv("ALE_TEST_FRONTEND"):
        (tmp_path/"frontend").symlink_to(os.environ["ALE_TEST_FRONTEND"],target_is_directory=True)
        monkeypatch.setattr(main_module,"ROOT",tmp_path)
    from app.main import app
    h=actors['operator']['headers']
    code='R7UI-'+uuid.uuid4().hex[:10]
    run=client.post('/api/v1/processes',headers=h,json={'process_code':code,'process_mode':'other','steps':[{'step_index':1,'step_kind':'自定义 Xe 分类','step_name':'Xe 活化','pulse_s':'2.500','duration_s':'3.000','parameter_snapshot':snapshot('自定义 Xe 分类','17','ms')}]}).json()['data']
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8028,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1500,'height':1100})
            p=context.new_page();p.set_default_timeout(15000);errors=[]
            p.on('pageerror',lambda e:errors.append(str(e)))
            p.goto(BASE+'/login');p.get_by_label('用户名',exact=True).fill(actors['operator']['user']['username']);p.get_by_label('密码',exact=True).fill('TestPassword123!');p.get_by_role('button',name='登录工作台',exact=True).click()
            p.get_by_role('heading',name='工作台概览',exact=True).wait_for()
            p.goto(BASE+f"/processes?process_id={run['process_id']}")
            p.get_by_test_id('edit-process-grid').click();dialog=p.get_by_role('dialog',name='实际流程网格',exact=True)
            dialog.get_by_label('总循环数',exact=True).fill('1')
            expect(dialog.locator('.legacy-parameters').first).to_contain_text('可能冲突')
            dialog.locator('.legacy-parameters summary').first.click()
            expect(dialog.locator('.legacy-parameters').first).to_contain_text('2.500')
            expect(dialog.get_by_label('步骤列分类',exact=True)).to_have_value('自定义 Xe 分类')
            dialog.get_by_label('Xe 活化 脉冲 时长 值',exact=True).fill('23.5')
            dialog.get_by_label('Xe 活化 脉冲 时长 单位',exact=True).fill('µs')
            data_snapshot={'step_type':'自定义 Xe 分类','temperature':{'value':None,'unit':'K'},'groups':[{'name':'脉冲','fields':[{'name':'时长','value':'23.5','unit':'µs'}]},{'name':'源','fields':[{'name':'名称','value':'Ar','unit':None}]}]}
            dialog.get_by_role('button',name='复制列',exact=True).click()
            expect(dialog.get_by_label('步骤列名称',exact=True)).to_have_count(2)
            dialog.get_by_label('步骤列名称',exact=True).nth(1).fill('A100')
            dialog.get_by_label('步骤列分类',exact=True).nth(1).fill('用户 C 任意处理')
            dialog.get_by_role('button',name='添加嵌套组',exact=True).first.click()
            dialog.get_by_label('流程组名称',exact=True).first.fill('组合循环')
            dialog.get_by_label('组重复次数',exact=True).first.fill('3')
            dialog.get_by_label('移动步骤到组',exact=True).first.select_option(label='组合循环')
            group=dialog.locator('.nested-process-group').first
            group.get_by_role('button',name='添加嵌套组',exact=True).first.click()
            group.get_by_label('流程组名称',exact=True).nth(1).fill('未知重复子组')
            group.get_by_label('移动步骤到组',exact=True).first.select_option(label='未知重复子组')
            # Template controls are grid-level now: pick a column, then save/apply a copy.
            bar=dialog.get_by_test_id('grid-template-bar')
            # Explicit flow order: the group (holding the original column) precedes the copy.
            options=bar.get_by_label('模板目标列',exact=True).locator('option').all_text_contents()
            target=next(text for text in options if text.endswith('Xe 活化'))
            bar.get_by_label('模板目标列',exact=True).select_option(label=target)
            bar.get_by_label('模板名称',exact=True).fill('R7 UI Xe 模板')
            with p.expect_response(lambda r:'/step-parameter-templates' in r.url and r.request.method=='POST') as templ:
                bar.get_by_role('button',name='另存为当前列为模板',exact=True).click()
            assert templ.value.status==201
            template_id=templ.value.json()['data']['template_id']
            template_definition=templ.value.json()['data']['definition']
            assert templ.value.json()['data']['definition']==data_snapshot
            p.wait_for_timeout(350)
            p.screenshot(path=str(ROOT/'reports/screenshots/round7-process-grid-editor.png'),full_page=True)
            with p.expect_response(lambda r:'/process-grid' in r.url and r.request.method=='PUT') as saved:
                dialog.get_by_test_id('save-process-grid').click()
            assert saved.value.status==200,saved.value.text()
            data=saved.value.json()['data'];assert data['process_flow']['total_cycles']==1
            assert data['steps'][0]['step_name']=='A100'
            saved_first_snapshot=data['steps'][0]['parameter_snapshot']
            assert data['steps'][1]['pulse_s']=='2.500'
            assert data['steps'][1]['parameter_source']=='parameter_snapshot'
            assert data['steps'][1]['step_id']==run['steps'][0]['step_id']
            assert data['steps'][1]['parameter_snapshot']['groups'][0]['fields'][0]=={'name':'时长','value':'23.5','unit':'µs'}
            assert data['process_flow']['children'][1]['repeat']==3
            assert data['process_flow']['children'][1]['children'][0]['repeat'] is None
            p.reload();p.get_by_test_id('edit-process-grid').click();dialog=p.get_by_role('dialog',name='实际流程网格',exact=True)
            # Template persisted in MySQL and remains selectable after a full reload.
            bar=dialog.get_by_test_id('grid-template-bar')
            expect(bar.get_by_label('参数模板',exact=True).locator(f'option[value="{template_id}"]')).to_have_text('R7 UI Xe 模板')
            # Applying is a deep copy: the unit survives, the record is unchanged until save.
            bar.get_by_label('模板目标列',exact=True).select_option(label=next(t for t in bar.get_by_label('模板目标列',exact=True).locator('option').all_text_contents() if t.endswith('A100')))
            bar.get_by_label('参数模板',exact=True).select_option(str(template_id))
            bar.get_by_role('button',name='应用到当前列',exact=True).click()
            expect(dialog.get_by_label('A100 脉冲 时长 值',exact=True)).to_have_value('23.5')
            expect(dialog.get_by_label('A100 脉冲 时长 单位',exact=True)).to_have_value('µs')
            applied=client.get(f"/api/v1/processes/{run['process_id']}",headers=h).json()['data']
            # Applying a template never mutates stored history: still the pre-apply snapshot.
            assert applied['steps'][0]['parameter_snapshot']==saved_first_snapshot
            assert applied['steps'][0]['parameter_snapshot']['groups'][0]['fields'][0]['unit']=='µs'
            expect(dialog.get_by_label('总循环数',exact=True)).to_have_value('1')
            expect(dialog.get_by_label('步骤列名称',exact=True).first).to_have_value('A100')
            expect(dialog.get_by_label('Xe 活化 脉冲 时长 值',exact=True)).to_have_value('23.5')
            expect(dialog.get_by_label('Xe 活化 脉冲 时长 单位',exact=True)).to_have_value('µs')
            expect(dialog.get_by_label('组重复次数',exact=True).nth(1)).to_have_value('')
            p.wait_for_timeout(350)
            p.screenshot(path=str(ROOT/'reports/screenshots/round7-process-grid-reloaded.png'),full_page=True)
            p.set_viewport_size({'width':390,'height':844})
            p.screenshot(path=str(ROOT/'reports/screenshots/round7-process-grid-mobile.png'),full_page=True)
            assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')
            dialog.get_by_role('button',name='添加步骤列',exact=True).first.click()
            expect(dialog.get_by_label('新步骤 脉冲 时长 单位',exact=True)).to_have_value('ms')
            expect(dialog.get_by_label('新步骤 吹扫 时长 单位',exact=True)).to_have_value('s')
            expect(dialog.get_by_label('新步骤 等待 时长 单位',exact=True)).to_have_value('s')
            assert not errors,errors
            print('Browser verified: generic classifications, copy column, nested groups, explicit unknown repeats, per-cell unit, template POST, atomic PUT, reload, narrow width; no JS errors')
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=5)
