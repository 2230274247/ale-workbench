"""Real Chromium + real MySQL rollback: three account purposes and visible isolation.

No synthetic fetch interception: the browser talks to the real FastAPI app over
HTTP, sessions are real, and every write rolls back with the parent transaction.
"""
import os
import threading
import time
import uuid

import pytest
from playwright.sync_api import expect
from sqlalchemy import select

from app.config import ROOT
from app.db import table
from app.security import hasher, new_session
from test_phase4_browser import db, client  # noqa: F401  (rollback + manifests)

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8032'
PASSWORD = 'AccountBrowser123!'
SHOTS = ROOT / 'reports' / 'screenshots'


def make_user(db, role, purpose):
    users = table('users')
    name = f'ui_{purpose}_{uuid.uuid4().hex[:12]}'
    uid = db.execute(users.insert().values(
        username=name, display_name=f'{purpose} account',
        password_hash=hasher.hash(PASSWORD), role=role,
        account_purpose=purpose, status='active', token_version=0)).inserted_primary_key[0]
    user = dict(db.execute(select(users).where(users.c.user_id == uid)).mappings().one())
    new_session(db, user)
    return user


def make_sample(db, owner, label):
    tag = uuid.uuid4().hex[:10]
    bid = db.execute(table('batches').insert().values(
        batch_code=f'UIB-{tag}', batch_name=f'{label} batch',
        owner_user_id=owner['user_id'])).inserted_primary_key[0]
    code = f'UIS-{label}-{tag}'
    db.execute(table('samples').insert().values(
        sample_code=code, batch_id=bid, sample_type='coupon', status='available',
        exclude_from_analysis=False, owner_user_id=owner['user_id']))
    return code


@pytest.fixture
def accounts(db):
    return {
        'admin': make_user(db, 'admin', 'management'),
        'research': make_user(db, 'operator', 'research'),
        'testing': make_user(db, 'operator', 'testing'),
    }


@pytest.fixture
def codes(db, accounts):
    return {'research': make_sample(db, accounts['research'], 'research'),
            'testing': make_sample(db, accounts['testing'], 'testing')}


@pytest.fixture
def ui(client, db, accounts, tmp_path, monkeypatch):
    import uvicorn
    from contextlib import contextmanager
    import app.ai as ai_module

    @contextmanager
    def same_transaction():
        # The real app opens a separate connection; tests must see uncommitted fixtures.
        with db.begin_nested():
            yield db
    monkeypatch.setattr(ai_module, 'ai_transaction', same_transaction)
    from playwright.sync_api import sync_playwright
    import app.main as main_module
    frontend = os.getenv('ALE_TEST_FRONTEND')
    if frontend:
        (tmp_path / 'frontend').symlink_to(frontend, target_is_directory=True)
        monkeypatch.setattr(main_module, 'ROOT', tmp_path)
    SHOTS.mkdir(parents=True, exist_ok=True)
    server = uvicorn.Server(uvicorn.Config(app=main_module.app, host='127.0.0.1', port=8032,
                                           log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(160):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            page.set_default_timeout(15000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            try:
                yield dict(page=page, errors=errors)
            finally:
                print('JS ERRORS:', errors)
                context.close()
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def login(page, user):
    from app.security import limiter
    limiter.entries.clear()  # test-only: repeated logins are not a credential attack
    page.goto(BASE + '/login')
    page.get_by_label('用户名', exact=True).fill(user['username'])
    page.get_by_label('密码', exact=True).fill(PASSWORD)
    page.get_by_role('button', name='登录工作台', exact=True).click()
    page.get_by_role('heading', name='工作台概览', exact=True).wait_for()
    page.wait_for_load_state('networkidle')


def logout(page):
    page.locator('.user-menu').click()
    page.get_by_text('退出登录', exact=True).click()
    page.wait_for_url('**/login')


def samples_text(page):
    page.goto(BASE + '/samples')
    page.wait_for_load_state('networkidle')
    return page.locator('main').inner_text()


def test_three_accounts_identity_and_isolation(ui, accounts, codes):
    page, errors = ui['page'], ui['errors']

    login(page, accounts['research'])
    identity = page.locator('.session-identity').inner_text()
    assert '科研账户' in identity and '生产环境' in identity and '仅本人数据' in identity
    text = samples_text(page)
    assert codes['research'] in text and codes['testing'] not in text
    page.screenshot(path=str(SHOTS / 'account-research.png'), full_page=True)

    logout(page)
    login(page, accounts['testing'])
    identity = page.locator('.session-identity').inner_text()
    assert '测试账户' in identity and '生产环境' in identity and '仅本人数据' in identity
    text = samples_text(page)
    assert codes['testing'] in text and codes['research'] not in text
    page.screenshot(path=str(SHOTS / 'account-testing.png'), full_page=True)

    logout(page)
    login(page, accounts['admin'])
    identity = page.locator('.session-identity').inner_text()
    assert '管理账户' in identity and '管理员 · 全局数据视图' in identity
    text = samples_text(page)
    assert codes['research'] in text and codes['testing'] in text
    page.screenshot(path=str(SHOTS / 'account-admin-global.png'), full_page=True)

    # Back to research: the previous admin list must not survive the session change.
    logout(page)
    login(page, accounts['research'])
    text = samples_text(page)
    assert codes['research'] in text and codes['testing'] not in text
    assert errors == [], errors


def test_members_page_shows_purpose_and_invite_choice(ui, accounts):
    page = ui['page']
    login(page, accounts['admin'])
    page.goto(BASE + '/users')
    page.wait_for_load_state('networkidle')
    main = page.locator('main').inner_text()
    assert '账户用途' in main
    for label in ('管理账户', '科研账户', '测试账户'):
        assert label in main
    page.get_by_role('button', name='邀请成员').first.click()
    dialog = page.get_by_role('dialog')
    expect(dialog.get_by_text('账户用途', exact=True)).to_be_visible()
    dialog.locator('.el-select').nth(1).click()
    page.wait_for_timeout(400)
    for label in ('科研账户', '测试账户'):
        assert page.get_by_role('option', name=label).count() >= 1, label
    page.keyboard.press('Escape')
    assert ui['errors'] == []
