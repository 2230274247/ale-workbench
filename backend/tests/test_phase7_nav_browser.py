"""Round 7 navigation and assistant placement, real MySQL rollback fixture."""
import os
import pytest
from playwright.sync_api import expect
from test_phase4_browser import db, client, world, ui, BASE, SHOTS

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')

def login(p, ui, role='admin'):
    p.goto(BASE+'/login')
    p.get_by_label('用户名',exact=True).fill(ui['actors'][role]['user']['username'])
    p.get_by_label('密码',exact=True).fill('TestPassword123!')
    p.get_by_role('button',name='登录工作台',exact=True).click()
    expect(p.locator('.topbar')).to_be_visible()
    p.wait_for_load_state('networkidle')

@pytest.mark.parametrize('width',[1440,390])
def test_grouped_nav_and_assistant(ui,width):
    p=ui['page'];p.set_viewport_size({'width':width,'height':900})
    login(p,ui)
    nav=p.locator('#workspace-nav')
    def open_nav():
        if width==390 and not p.locator('.sidebar').evaluate("e=>e.classList.contains('mobile-open')"):
            p.get_by_role('button',name='打开导航',exact=True).click()
    open_nav()
    expected=['/','/batches','/samples','/chemistry','/plans','/processes','/sample-history','/imports','/measurements','/source-files','/analysis','/instruments/ellipsometry','/users','/ai-settings']
    assert set(nav.locator('a').evaluate_all('(els)=>els.map(e=>e.getAttribute("href"))'))==set(expected)
    for target in expected:
        open_nav()
        link=nav.locator(f'a[href="{target}"]');link.scroll_into_view_if_needed();link.click();p.wait_for_url(BASE+target)
        p.wait_for_load_state('networkidle')
        assert p.url.split(BASE)[1].split('?')[0]==target
        expect(nav.locator(f'a[href="{target}"]')).to_have_attribute('aria-current','page')
        if width==390: expect(p.locator('.sidebar')).not_to_have_class('sidebar mobile-open')
    p.goto(BASE+'/samples');p.wait_for_load_state('networkidle');open_nav()
    nav.get_by_role('button',name='收起材料管理',exact=True).click()
    expect(nav.locator('a[href="/samples"]')).to_be_visible()
    expect(nav.locator('a[href="/batches"]')).to_be_hidden()
    if width==1440:p.get_by_role('button',name='折叠侧边栏',exact=True).click()
    p.reload();p.wait_for_load_state('networkidle');open_nav()
    expect(nav.get_by_role('button',name='展开材料管理',exact=True)).to_have_attribute('aria-expanded','false')
    if width==1440:
        expect(p.locator('.app-shell')).to_have_class('app-shell sidebar-collapsed')
        p.get_by_role('button',name='展开侧边栏',exact=True).click()
    expect(nav.locator('a[href="/batches"]')).to_be_hidden()
    nav.get_by_role('button',name='展开材料管理',exact=True).click()
    p.screenshot(path=str(SHOTS/f'phase7-nav-groups-{width}.png'),full_page=True)
    # The grouped navigation can invoke the assistant even when the float is hidden.
    nav.get_by_role('button',name='研究助手',exact=True).click()
    expect(p.locator('.ai-drawer')).to_be_visible()
    p.locator('#ai-question').fill('未发送的研究问题')
    p.get_by_role('button',name='关闭研究助手',exact=True).click()
    expect(p.locator('.ai-drawer')).to_be_hidden()
    p.locator('.header-assistant').click()
    expect(p.locator('#ai-question')).to_have_value('未发送的研究问题')
    p.get_by_role('button',name='关闭研究助手',exact=True).click()
    expect(p.locator('.ai-drawer')).to_be_hidden()
    p.goto(BASE+'/');p.wait_for_load_state('networkidle')
    if width==1440:p.set_viewport_size({'width':1440,'height':1600})
    if width==1440:expect(p.locator('.ai-launch')).to_be_visible()
    else:expect(p.locator('.ai-launch')).to_be_hidden()
    # Real Element Plus password dialog: save validation, dirty close, nested message box.
    p.locator('.user-menu').hover()
    p.get_by_role('menuitem',name='修改密码').click()
    dialog=p.get_by_role('dialog',name='修改密码',exact=True)
    expect(dialog).to_be_visible();expect(p.locator('.ai-launch')).to_be_hidden()
    dialog.get_by_role('button',name='保存密码',exact=True).click()
    assert dialog.locator('#current-password').evaluate('e=>!e.validity.valid');expect(dialog).to_be_visible()
    dialog.locator('#current-password').fill('not-submitted')
    dialog.get_by_role('button',name='取消',exact=True).click()
    box=p.locator('.el-message-box')
    expect(box).to_be_visible();expect(p.locator('.ai-launch')).to_be_hidden()
    box.get_by_role('button',name='继续编辑').click()
    expect(dialog).to_be_visible()
    dialog.get_by_role('button',name='取消',exact=True).click()
    box.get_by_role('button',name='放弃修改').click()
    expect(dialog).to_be_hidden()
    if width==1440:expect(p.locator('.ai-launch')).to_be_visible()
    # Actual business drawer: save/cancel remain unobscured.
    p.goto(BASE+'/batches');p.wait_for_load_state('networkidle');p.get_by_role('button',name='新建批次',exact=True).first.click()
    drawer=p.locator('.el-drawer:not(.ai-drawer):visible')
    expect(drawer).to_be_visible();expect(p.locator('.ai-launch')).to_be_hidden()
    p.screenshot(path=str(SHOTS/f'phase7-nav-modal-{width}.png'),full_page=True)
    cancel=drawer.get_by_role('button',name='取消',exact=True)
    cancel.click();expect(drawer).to_be_hidden()
    p.goto(BASE+'/');p.wait_for_load_state('networkidle')
    if width==1440:
        # A page action under the launcher suppresses it on DOM insertion; remove restores it.
        p.evaluate("""()=>{let b=document.createElement('button');b.id='nav-test-bottom';b.textContent='底部保存';b.style.cssText='position:fixed;right:24px;bottom:24px;width:160px;height:50px';document.querySelector('.page-main').append(b)}""")
        expect(p.locator('.ai-launch')).to_be_hidden();p.locator('#nav-test-bottom').click()
        p.evaluate("document.querySelector('#nav-test-bottom').remove()")
        expect(p.locator('.ai-launch')).to_be_visible()
    # Corrupt preferences are ignored; switched user never inherits the admin fold state.
    uid=ui['actors']['admin']['user']['user_id'];key=f'ale:nav:v1:user:{uid}'
    p.evaluate('(key)=>localStorage.setItem(key,"{broken")',key)
    p.reload();p.wait_for_load_state('networkidle');open_nav()
    expect(nav.get_by_role('button',name='收起材料管理',exact=True)).to_have_attribute('aria-expanded','true')
    if width==390:p.locator('.nav-scrim').click(position={'x':370,'y':100})
    p.locator('.user-menu').hover();p.get_by_role('menuitem',name='退出登录').click()
    expect(p.get_by_role('button',name='登录工作台',exact=True)).to_be_visible()
    login(p,ui,'viewer');open_nav()
    assert nav.locator('a[href="/users"],a[href="/ai-settings"],a[href="/chemistry"]').count()==0
    expect(nav.get_by_role('button',name='收起材料管理',exact=True)).to_have_attribute('aria-expanded','true')
    assert not ui['errors'],ui['errors']
    print(f'PHASE7 NAV PASS width={width}: 14 routes, active highlight, fold fresh-load, account scope, malformed storage, AI nav/header reopen, dialog/save/cancel/nested-modal/drawer/bottom-action avoidance, JS errors=[]')
