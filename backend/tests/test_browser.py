"""Browser acceptance against the real API/MySQL in an outer rollback transaction."""
import os
import threading
import time
import socket
from pathlib import Path
import pytest

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')


def test_real_browser_workflows(client, actors, db):
    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.main import app
    from app.config import ROOT
    from app.security import limiter
    output = ROOT / 'reports' / 'screenshots'
    output.mkdir(parents=True, exist_ok=True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8012, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.05)
    assert server.started
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'], env={**os.environ, 'LD_LIBRARY_PATH':'/tmp/libs/x/usr/lib/x86_64-linux-gnu'})
            page = browser.new_page(viewport={'width':1440,'height':1000}, device_scale_factor=1)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto('http://127.0.0.1:8012/login')
            page.get_by_role('heading', name='欢迎回来').wait_for()
            page.screenshot(path=str(output / '01-login.png'), full_page=True)
            page.get_by_label('用户名', exact=True).fill(actors['admin']['user']['username'])
            page.get_by_label('密码', exact=True).fill('TestPassword123!')
            page.get_by_role('button', name='登录工作台').click()
            page.get_by_role('heading', name='工作台概览').wait_for()
            page.wait_for_function("!document.querySelector('.el-loading-mask') || [...document.querySelectorAll('.el-loading-mask')].every(e=>getComputedStyle(e).display==='none')")
            page.wait_for_timeout(350)
            page.screenshot(path=str(output / '02-dashboard.png'), full_page=True)
            page.goto('http://127.0.0.1:8012/batches')
            page.get_by_role('button', name='新建批次', exact=True).first.click()
            page.get_by_label('批次编码', exact=True).fill('ACCEPTANCE-BATCH')
            page.get_by_label('批次名称', exact=True).fill('验收测试批次（自动回滚）')
            page.get_by_label('标称厚度 / nm', exact=True).fill('47.500')
            page.get_by_role('button', name='保存批次', exact=True).click()
            page.get_by_text('验收测试批次（自动回滚）', exact=True).wait_for()
            page.locator('.el-drawer').wait_for(state='hidden')
            page.wait_for_timeout(350)
            page.screenshot(path=str(output / '03-batches.png'), full_page=True)
            page.goto('http://127.0.0.1:8012/samples')
            page.get_by_role('button', name='新建样品', exact=True).first.click()
            page.get_by_label('样品编码', exact=True).fill('ACCEPTANCE-S01')
            page.get_by_label('所属批次', exact=True).click()
            page.get_by_role('option').filter(has_text='ACCEPTANCE-BATCH').click()
            page.get_by_label('标称厚度 / nm', exact=True).fill('47.500')
            page.get_by_role('button', name='保存样品', exact=True).click()
            page.get_by_role('button', name='ACCEPTANCE-S01', exact=True).wait_for()
            page.locator('.el-drawer').wait_for(state='hidden')
            page.wait_for_timeout(350)
            page.screenshot(path=str(output / '04-samples.png'), full_page=True)
            page.get_by_role('button', name='编辑', exact=True).first.click()
            page.get_by_label('前处理记录', exact=True).fill('仅用于验收，事务结束回滚')
            page.get_by_role('button', name='保存样品', exact=True).click()
            page.get_by_text('样品已保存', exact=True).wait_for()
            page.goto('http://127.0.0.1:8012/users')
            page.get_by_role('heading', name='成员与邀请').wait_for()
            page.screenshot(path=str(output / '05-users.png'), full_page=True)
            page.get_by_role('button', name='邀请成员', exact=True).first.click()
            page.get_by_role('button', name='生成邀请码', exact=True).click()
            page.locator('.invitation-code').wait_for()
            invite = page.locator('.invitation-code').inner_text()
            assert len(invite) > 20
            page.get_by_role('button', name='完成', exact=True).click()
            page.get_by_role('tab', name='邀请记录').click()
            page.get_by_text('待使用', exact=True).first.wait_for()
            page.screenshot(path=str(output / '06-invitations.png'), full_page=True)
            # A refresh restores auth using only the HttpOnly cookie.
            page.reload()
            page.get_by_role('heading', name='成员与邀请').wait_for()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
