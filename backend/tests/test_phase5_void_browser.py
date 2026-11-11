"""Sample void management acceptance on Chromium, real MySQL, rollback fingerprints."""
import pytest
from playwright.sync_api import expect
from test_phase5_browser import ui, login, capture, BASE
from test_phase4_browser import db, client, world
from test_phase5_sample_void import fresh, call

@pytest.mark.parametrize('width,height',[(1440,1000),(390,844)],ids=['desktop','narrow'])
def test_void_management_reason_conflict_history_and_selection(ui,width,height):
    p,c,a=ui['page'],ui['client'],ui['actors'];p.set_viewport_size({'width':width,'height':height})
    sample=fresh(c,a,sample_type='parent_wafer',notes='科学原始记录保留')
    used=fresh(c,a)
    call(c,a,'post',f"/samples/{used['sample_id']}/transitions",{'expected_row_version':1,'event_type':'measure','to_status':'available'},status=201)
    login(ui);p.goto(BASE+'/samples')
    search=p.get_by_role('textbox',name='搜索关键词');search.fill(sample['sample_code']);p.get_by_role('button',name='查询',exact=True).click()
    p.get_by_test_id('sample-void').click();dialog=p.get_by_test_id('sample-void-dialog')
    expect(dialog.get_by_role('button',name='确认作废',exact=True)).to_be_disabled()
    dialog.get_by_role('textbox',name='作废原因').fill('   ')
    expect(dialog.get_by_role('button',name='确认作废',exact=True)).to_be_disabled()
    dialog.get_by_role('textbox',name='作废原因').fill('误建样品，保留记录供追溯')
    capture(ui,'void-reason-required')
    # A competing correction after opening causes CAS rejection, with reason retained.
    call(c,a,'patch',f"/samples/{sample['sample_id']}",{'expected_row_version':1,'notes':'科学原始记录保留（校正）'})
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/void')) as response:
        dialog.get_by_role('button',name='确认作废',exact=True).click()
    assert response.value.status==409
    expect(dialog.get_by_role('textbox',name='作废原因')).to_have_value('误建样品，保留记录供追溯')
    capture(ui,'void-cas-reason-retained')
    dialog.get_by_role('button',name='重载样品并保留原因',exact=True).click()
    expect(dialog.get_by_role('button',name='确认作废',exact=True)).to_be_enabled()
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/void')) as response:
        dialog.get_by_role('button',name='确认作废',exact=True).click()
    assert response.value.status==200,response.value.text()
    v=response.value.json()['data'];assert v['status']=='available' and v['row_version']==3
    expect(p.get_by_test_id('sample-detail-voided-badge')).to_be_visible()
    drawer=p.locator('.records-drawer')
    expect(drawer.get_by_role('button',name='编辑档案',exact=True)).to_have_count(0)
    expect(drawer).to_contain_text('科学原始记录保留（校正）')
    capture(ui,'void-readonly-detail')
    drawer.get_by_role('button',name='查看完整历史（只读）',exact=True).click()
    history=p.get_by_test_id('void-history');expect(history.locator('.el-table__row')).to_have_count(1)
    expect(history).to_contain_text('初始 → 可用')
    expect(history.get_by_role('button',name='追加流转',exact=True)).to_have_count(0)
    capture(ui,'void-history-readonly')
    history.locator('.el-dialog__headerbtn').click()
    drawer.get_by_role('button',name='关闭',exact=True).click()
    expect(p.locator('.table-code')).to_have_count(0)
    p.get_by_test_id('include-voided').click()
    expect(p.get_by_test_id('sample-voided-badge')).to_be_visible()
    expect(p.get_by_role('button',name='编辑',exact=True)).to_be_disabled()
    capture(ui,'void-management-filter')
    p.reload();search=p.get_by_role('textbox',name='搜索关键词');search.fill(sample['sample_code']);p.get_by_role('button',name='查询',exact=True).click()
    expect(p.locator('.table-code')).to_have_count(0)
    # Creation selector must exclude the voided parent even after management inclusion.
    p.get_by_role('button',name='新建样品',exact=True).first.click();drawer=p.locator('.records-drawer')
    batch_field=drawer.locator('.el-form-item').filter(has= p.locator('label').filter(has_text='所属批次')).locator('.el-select')
    batch_field.click();p.locator('.el-select-dropdown:visible').get_by_text(sample['batch_id'] and call(c,a,'get',f"/batches/{sample['batch_id']}")['batch_code'],exact=False).click()
    parent_field=drawer.locator('.el-form-item').filter(has=p.locator('label').filter(has_text='母片 / 上级样品')).locator('.el-select')
    parent_field.click();expect(p.locator('.el-select-dropdown:visible').get_by_text(sample['sample_code'],exact=False)).to_have_count(0)
    capture(ui,'void-parent-excluded')
    p.keyboard.press('Escape');drawer.get_by_role('button',name='取消',exact=True).click()
    if p.locator('.el-message-box:visible').count():p.locator('.el-message-box').get_by_role('button',name='放弃修改',exact=True).click()
    search.fill(used['sample_code']);p.get_by_role('button',name='查询',exact=True).click();p.get_by_test_id('sample-void').click()
    dialog.get_by_role('textbox',name='作废原因').fill('不能作废已使用样品')
    with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/void')) as response:dialog.get_by_role('button',name='确认作废',exact=True).click()
    assert response.value.status==409
    capture(ui,'void-used-rejected')
    dialog.get_by_role('button',name='取消',exact=True).click()
    print('VOID VERIFIED:',{'sample_id':v['sample_id'],'status':v['status'],'row_version':v['row_version'],'void_reason':v['void_reason']})

@pytest.mark.parametrize('role',['admin','viewer'])
def test_void_management_roles(ui,role):
    from app.db import table
    p,c,a,db=ui['page'],ui['client'],ui['actors'],ui['db']
    sample=fresh(c,a)
    if role=='viewer':
        uid=a['viewer']['user']['user_id']
        db.execute(table('samples').update().where(table('samples').c.sample_id==sample['sample_id']).values(owner_user_id=uid))
        db.execute(table('batches').update().where(table('batches').c.batch_id==sample['batch_id']).values(owner_user_id=uid))
    login({**ui,'actors':{**a,'operator':a[role]}})
    p.goto(BASE+f"/samples?sample_id={sample['sample_id']}")
    drawer=p.locator('.records-drawer');expect(drawer.get_by_role('heading',name=sample['sample_code'],exact=True)).to_be_visible()
    if role=='viewer':
        expect(p.get_by_test_id('sample-detail-void')).to_have_count(0)
        expect(drawer.get_by_role('button',name='编辑档案',exact=True)).to_have_count(0)
        capture(ui,'void-viewer-readonly')
    else:
        drawer.get_by_test_id('sample-detail-void').click()
        dialog=p.get_by_test_id('sample-void-dialog');dialog.get_by_role('textbox',name='作废原因').fill('管理员核对误建')
        with p.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/void')) as response:dialog.get_by_role('button',name='确认作废',exact=True).click()
        assert response.value.status==200
        expect(p.get_by_test_id('sample-detail-voided-badge')).to_be_visible()
        drawer.get_by_role('button',name='关闭',exact=True).click()
        p.get_by_role('textbox',name='搜索关键词').fill(sample['sample_code'])
        p.get_by_test_id('include-voided').click()
        expect(p.get_by_role('button',name='删除',exact=True)).to_be_disabled()
        expect(p.get_by_role('button',name='编辑',exact=True)).to_be_disabled()
        capture(ui,'void-admin-delete-disabled')
