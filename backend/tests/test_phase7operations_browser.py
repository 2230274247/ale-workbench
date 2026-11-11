"""Explicit synthetic Round7 UI evidence, real MySQL outer rollback, no live AI."""
import os
import uuid
import pytest
from playwright.sync_api import expect
from sqlalchemy import select, func
from app.db import table
from app.config import ROOT
from test_phase4_browser import db, client, world
from test_ai import setup_ai
from test_ai_browser import ui, login, BASE

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')

@pytest.mark.parametrize('width',[1440,390])
def test_synthetic_ai_states_and_test_before_enable(ui,width):
    p=ui['page']; p.set_viewport_size({'width':width,'height':1000})
    login(ui,'admin'); p.goto(BASE+'/ai-settings')
    p.get_by_role('heading',name='AI 设置',exact=True).wait_for()
    p.get_by_label('清除服务器密钥',exact=True).check()
    p.get_by_role('button',name='保存设置',exact=True).click()
    expect(p.get_by_role('button',name='发现模型',exact=True)).to_be_disabled()
    expect(p.get_by_test_id('test-disabled-reason')).to_contain_text('请先保存 API Key')
    p.get_by_label('服务商预设',exact=True).select_option('deepseek')
    expect(p.get_by_label('HTTPS 接口地址',exact=True)).to_have_value('https://api.deepseek.com')
    key=p.get_by_label('新 API Key（只写）',exact=False)
    key.fill('phase7-synthetic-only')
    expect(p.get_by_role('button',name='发送通用测试',exact=True)).to_be_disabled()
    expect(p.get_by_test_id('test-disabled-reason')).to_contain_text('先保存修改')
    assert not ui['seen']
    p.get_by_role('button',name='保存设置',exact=True).click()
    expect(key).to_have_value('')
    expect(p.get_by_role('button',name='发现模型',exact=True)).to_be_enabled()
    p.get_by_role('button',name='发现模型',exact=True).click()
    p.get_by_label('已发现的模型',exact=True).select_option('discovered-choice')
    expect(p.get_by_role('button',name='发送通用测试',exact=True)).to_be_disabled()
    p.get_by_role('button',name='保存设置',exact=True).click()
    expect(p.get_by_label('启用研究助手',exact=True)).not_to_be_checked()
    expect(p.get_by_test_id('model-metadata')).to_contain_text('未知')
    expect(p.get_by_test_id('test-disabled-reason')).to_contain_text('请勾选')
    p.get_by_label('允许发送通用问候给已配置模型服务（不含实验数据，计入预算）',exact=True).check()
    p.get_by_role('button',name='发送通用测试',exact=True).click()
    expect(p.locator('.ai-test-result')).to_contain_text('通用问候')
    assert len(ui['seen'])==2
    payload=ui['seen'][-1][1]
    assert 'tools' not in payload and payload['messages'][-1]['content']=='Say hello briefly. Do not access scientific data.'
    p.get_by_label('启用研究助手',exact=True).check()
    p.get_by_role('button',name='保存设置',exact=True).click()
    p.screenshot(path=str(ROOT/'reports/screenshots'/f'phase7-operations-ai-synthetic-{width}.png'),full_page=True)
    assert p.evaluate('document.documentElement.scrollWidth <= innerWidth+1')


def test_sample_home_bulk_twenty_editable_atomic(ui):
    p=ui['page']; login(ui,'operator'); p.goto(BASE+'/samples')
    p.get_by_role('heading',name='样品管理',exact=True).wait_for()
    expect(p.get_by_role('button',name='新建样品',exact=True)).to_be_visible()
    p.get_by_test_id('sample-home-bulk').click()
    dialog=p.get_by_test_id('batch-create-dialog')
    dialog.get_by_label('批量目标批次',exact=True).click()
    p.get_by_role('option',name=ui['world']['batch_code']+' · 第四轮验收批次',exact=True).click()
    dialog.get_by_test_id('batch-count').fill('20')
    dialog.get_by_test_id('batch-count').press('Tab')
    preview=dialog.get_by_test_id('batch-preview')
    expect(preview.locator('.el-table__body tbody tr')).to_have_count(20)
    code='P7UI-'+uuid.uuid4().hex[:12]
    preview.locator('.el-table__body tbody tr').first.locator('input').first.fill(code)
    before=ui['db'].scalar(select(func.count()).select_from(table('samples')))
    p.screenshot(path=str(ROOT/'reports/screenshots'/'phase7-operations-bulk20-synthetic.png'),full_page=True)
    dialog.get_by_test_id('batch-submit').click()
    expect(dialog).not_to_be_visible()
    p.wait_for_load_state('networkidle')
    assert ui['db'].scalar(select(func.count()).select_from(table('samples')))==before+20
    assert ui['db'].scalar(select(func.count()).select_from(table('samples')).where(table('samples').c.sample_code==code))==1
    assert not ui['seen']
    print('BROWSER SAMPLE BASELINE',before,'CREATED',20,'SYNTHETIC AI CALLS',len(ui['seen']))
