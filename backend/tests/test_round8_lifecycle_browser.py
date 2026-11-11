"""Current source isolated build, Chromium + real MySQL outer rollback."""
import os
import pytest
from playwright.sync_api import expect
from app.config import ROOT
from test_round8_nav_dashboard_browser import db, client, world, ui, login, BASE
from test_round8_lifecycle import create

pytestmark=pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST')!='1',reason='Opt-in browser')

@pytest.mark.parametrize('width',[1440,390])
def test_preview_confirmation_cas_restore_and_lost_response(ui,width):
    p=ui['page'];p.set_viewport_size({'width':width,'height':1000})
    row=create(ui['client'],ui['actors'],'batches')
    login(p,ui['actors'],'operator');p.goto(BASE+'/batches')
    p.get_by_label('搜索关键词',exact=True).fill(row['batch_code'])
    p.get_by_role('button',name='查询',exact=True).click()
    p.get_by_test_id('lifecycle-open').click()
    dialog=p.get_by_test_id('lifecycle-dialog')
    expect(dialog.get_by_test_id('lifecycle-action-void')).to_be_visible()
    writes=[]
    p.on('request',lambda r:writes.append(r.url) if r.method=='POST' and '/lifecycle/' in r.url else None)
    dialog.get_by_test_id('lifecycle-submit').click()
    p.locator('.el-message-box').get_by_role('button',name='取消',exact=True).click()
    assert not writes
    # Real CAS conflict after preview, then refresh preserving reason.
    dialog.locator('textarea').fill('保留生命周期原因')
    from test_phase5_sample_void import call
    call(ui['client'],ui['actors'],'patch',f"/batches/{row['batch_id']}",{'expected_row_version':1,'notes':'concurrent'})
    dialog.get_by_test_id('lifecycle-submit').click()
    p.get_by_role('button',name='确认归档',exact=True).click()
    expect(dialog.get_by_test_id('lifecycle-error')).to_contain_text('记录已变更')
    dialog.get_by_test_id('lifecycle-reload').click()
    expect(dialog.locator('textarea')).to_have_value('保留生命周期原因')
    expect(dialog.get_by_test_id('lifecycle-submit')).to_be_enabled()
    # Let the server commit to the request SAVEPOINT then drop only its response.
    def lose(route):
        route.fetch()
        route.abort('failed')
    p.route('**/lifecycle/batches/*/apply',lose,times=1)
    dialog.get_by_test_id('lifecycle-submit').click()
    p.get_by_role('button',name='确认归档',exact=True).click()
    expect(dialog.get_by_test_id('lifecycle-recover')).to_be_visible()
    dialog.get_by_test_id('lifecycle-recover').click()
    expect(dialog).not_to_be_visible()
    p.get_by_test_id('lifecycle-open').click()
    expect(dialog.get_by_test_id('lifecycle-archived-badge')).to_be_visible()
    expect(dialog.get_by_test_id('lifecycle-action-restore')).to_be_visible()
    p.wait_for_timeout(400)  # Element Plus dialog enter animation must finish before evidence capture.
    p.screenshot(path=str(ROOT/'reports/screenshots'/f'round8-lifecycle-archive-recovery-{width}.png'),full_page=True)
    dialog.get_by_test_id('lifecycle-submit').click()
    p.get_by_role('button',name='确认恢复',exact=True).click()
    expect(dialog).not_to_be_visible()
    p.reload()
    p.get_by_label('搜索关键词',exact=True).fill(row['batch_code'])
    p.get_by_role('button',name='查询',exact=True).click()
    p.get_by_test_id('lifecycle-open').click()
    expect(dialog.get_by_test_id('lifecycle-action-void')).to_be_visible()
    dialog.get_by_test_id('lifecycle-action-void').click()
    expect(dialog.get_by_test_id('lifecycle-submit')).to_be_disabled()
    dialog.locator('textarea').fill('误建批次')
    dialog.get_by_test_id('lifecycle-submit').click()
    p.get_by_role('button',name='确认作废',exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(p.get_by_test_id('lifecycle-open')).to_have_count(0)
    p.get_by_test_id('include-voided').check()
    p.get_by_test_id('lifecycle-open').click()
    expect(dialog.get_by_test_id('lifecycle-voided-badge')).to_be_visible()
    expect(dialog.get_by_test_id('lifecycle-submit')).to_be_disabled()
    assert p.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
    assert not ui['errors']


def test_batch_explicit_sample_selection(ui):
    from test_phase5_sample_void import fresh
    from sqlalchemy import select
    from app.db import table
    sample=fresh(ui['client'],ui['actors'])
    with ui['db'].info['browser_lock']:
        code=ui['db'].scalar(select(table('batches').c.batch_code).where(table('batches').c.batch_id==sample['batch_id']))
    p=ui['page'];login(p,ui['actors'],'operator');p.goto(BASE+'/batches')
    p.get_by_label('搜索关键词',exact=True).fill(code)
    p.get_by_role('button',name='查询',exact=True).click()
    p.get_by_test_id('lifecycle-open').click()
    dialog=p.get_by_test_id('lifecycle-dialog')
    dialog.get_by_test_id('lifecycle-action-archive_with_dependents').click()
    expect(dialog.get_by_test_id('lifecycle-submit')).to_be_disabled()
    dialog.get_by_test_id(f"lifecycle-candidate-{sample['sample_id']}").check()
    dialog.get_by_test_id('lifecycle-submit').click()
    expect(p.locator('.el-message-box')).to_contain_text('所选 1 份未使用样品')
    p.locator('.el-message-box').get_by_role('button',name='取消',exact=True).click()
    with ui['db'].info['browser_lock']:
        assert ui['db'].scalar(select(table('samples').c.archived_at).where(table('samples').c.sample_id==sample['sample_id'])) is None
    dialog.get_by_test_id('lifecycle-submit').click()
    p.get_by_role('button',name='确认归档',exact=True).click()
    expect(dialog).not_to_be_visible()
    with ui['db'].info['browser_lock']:
        assert ui['db'].scalar(select(table('samples').c.archived_at).where(table('samples').c.sample_id==sample['sample_id'])) is not None
    assert not ui['errors']
