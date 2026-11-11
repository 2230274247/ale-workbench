"""Opt-in actual MySQL/Uvicorn/Chromium acceptance, rollback-only, temporary originals.
Run each parametrized group independently; ALE_PARSER_UPLOADS points at original ZIPs.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
import zipfile

import pytest
from sqlalchemy import select
from app.db import engine, metadata, table
from app.config import ROOT
from test_phase3_imports import sample, process, rows as import_rows

pytestmark = pytest.mark.skipif(os.getenv('ALE_BROWSER_TEST') != '1', reason='Opt-in browser acceptance')
BASE = 'http://127.0.0.1:8019'


def database_manifest(connection):
    return {t.name: hashlib.sha256(json.dumps([dict(r) for r in connection.execute(select(t).order_by(*t.primary_key.columns)).mappings()], default=str, sort_keys=True).encode()).hexdigest()
            for t in metadata().tables.values()}


def originals_manifest():
    root = ROOT / 'storage' / 'originals'
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def db():
    with engine().connect() as independent:
        baseline = database_manifest(independent)
    original_baseline = originals_manifest()
    connection = engine().connect()
    tx = connection.begin()
    try:
        yield connection
    finally:
        counts = {t.name: len(connection.execute(select(t)).all()) for t in metadata().tables.values()}
        tx.rollback()
        connection.close()
        with engine().connect() as independent:
            assert database_manifest(independent) == baseline, 'Committed DB changed'
        assert originals_manifest() == original_baseline, 'Production originals changed'
        print('ROLLBACK VERIFIED: all %d tables identical; production originals %d files identical; transaction row counts=%s' % (len(baseline), len(original_baseline), counts))


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import get_db
    from app.security import limiter
    lock=threading.Lock()
    db.info['browser_lock']=lock
    def override():
        with lock:
            with db.begin_nested(): yield db
    app.dependency_overrides[get_db]=override
    limiter.entries.clear()
    try:
        with TestClient(app,raise_server_exceptions=False) as c: yield c
    finally: app.dependency_overrides.clear()


def rows(db,name):
    with db.info['browser_lock']: return import_rows(db,name)


@pytest.fixture
def corpus():
    root = Path(os.environ.get('ALE_PARSER_UPLOADS', str(ROOT.parent / 'uploads')))
    selected = []
    specifications = [('1.-2026.8.31-SiN.zip', '/1.xlsx'),
                      ('3.-2026.9.28-SiN(1).zip', '/2.FULL-46nm-PECVD-ERROR_Temperature.xlsx'),
                      ('1.-2026.8.31-SiN.zip', '/Al2p Scan.xml')]
    for archive, suffix in specifications:
        with zipfile.ZipFile(root / archive) as z:
            info = next(i for i in z.infolist() if i.filename.endswith(suffix))
            selected.append((Path(info.filename).name, z.read(info)))
    selected.append(('unknown.rga', b'phase3 unrecognized instrument original'))
    return selected


@pytest.fixture
def ui(client, actors, db, tmp_path, monkeypatch, corpus):
    import uvicorn
    from playwright.sync_api import sync_playwright
    from app.main import app
    root = tmp_path / 'test_store'
    monkeypatch.setenv('ALE_ORIGINALS_ROOT', str(root))
    sid = sample(db, actors)
    pid = process(db, actors, sid)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8019, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width':1440,'height':1000}, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(6000)
            errors, responses = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('response', lambda r: responses.append((r.request.method,r.url.split('/api/v1/')[-1],r.status)) if '/api/v1/' in r.url else None)
            state = dict(page=page,context=context,actors=actors,client=client,db=db,sid=sid,pid=pid,corpus=corpus,errors=errors,responses=responses)
            try: yield state
            finally:
                print('JS ERRORS:', errors)
                print('HTTP EVIDENCE:', [r for r in responses if r[0]!='GET' or r[2]>=400])
                context.close()
                browser.close()
    finally:
        server.should_exit=True
        thread.join(timeout=5)
        assert not thread.is_alive()
        stored = [p for p in root.rglob('*') if p.is_file()]
        print('TEMPORARY test_store original files:', len(stored))
        if root.exists(): shutil.rmtree(root)
        assert not root.exists()
        print('TEMPORARY test_store REMOVED')


def login(ui):
    p=ui['page']
    p.goto(BASE+'/login')
    p.get_by_label('用户名',exact=True).fill(ui['actors']['operator']['user']['username'])
    p.get_by_label('密码',exact=True).fill('TestPassword123!')
    p.get_by_role('button',name='登录工作台',exact=True).click()
    p.get_by_role('heading',name='工作台概览',exact=True).wait_for()


def capture(ui,name):
    p=ui['page']
    p.wait_for_timeout(350)  # Finish Element Plus overlay transitions before visual evidence.
    size=p.evaluate('({viewport:innerWidth,body:document.body.scrollWidth,document:document.documentElement.scrollWidth})')
    p.screenshot(path=str(ROOT/'reports'/'screenshots'/f'phase3-{p.viewport_size["width"]}-{name}.png'),full_page=True)
    assert max(size['body'],size['document'])<=size['viewport']+1,(name,size)
    print('LAYOUT', name, size)


def configure(ui,item,action='导入正式测量',duplicate=False):
    from playwright.sync_api import expect
    p=ui['page']; iid=item['item_id']; name=item['filename']
    card=p.get_by_test_id(f'import-item-{iid}')
    p.get_by_test_id(f'select-item-{iid}').check()
    p.get_by_test_id(f'action-{iid}').click()
    p.get_by_role('option',name=action,exact=True).click()
    if action=='仅保存原件': return
    sample_code=next(r['sample_code'] for r in rows(ui['db'],'samples') if r['sample_id']==ui['sid'])
    process_code=next(r['process_code'] for r in rows(ui['db'],'processes') if r['process_id']==ui['pid'])
    control=card.get_by_role('combobox',name=name+'样品',exact=True)
    control.fill(sample_code);p.wait_for_timeout(700)
    p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=sample_code).first.click()
    p.wait_for_timeout(300)
    card.get_by_role('combobox',name=name+'执行',exact=True).locator('xpath=ancestor::div[contains(@class,"el-select")][1]').click()
    p.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=process_code).first.click()
    expect(card.get_by_label('阶段序号',exact=True)).to_have_value('')
    card.get_by_test_id('import-stage').click()
    p.get_by_role('option',name='初始',exact=True).click()
    card.get_by_label('阶段序号',exact=True).fill('0')
    p.wait_for_timeout(300)
    p.get_by_test_id(f'units-{iid}').check()
    p.get_by_test_id(f'associations-{iid}').check()
    if duplicate:
        p.get_by_test_id(f'duplicate-{iid}').check()
        card.get_by_label('重复导入原因',exact=True).fill('验收：同 SHA 经人工核对保留第二独立测量')


def submit(ui):
    p=ui['page']
    if p.get_by_role('button',name='下一步：确认提交',exact=True).count():
        p.get_by_role('button',name='下一步：确认提交',exact=True).click()
    p.get_by_test_id('import-step3-submit').click()
    if p.locator('.el-message-box').count():
        p.locator('.el-message-box').get_by_role('button',name='确认所选并提交',exact=True).click()


@pytest.mark.parametrize('width,height',[(1440,1000),(390,844)],ids=['desktop','narrow'])
def test_phase3_browser_end_to_end(ui,width,height):
    from playwright.sync_api import expect
    started=time.monotonic(); p=ui['page']; db=ui['db']; client=ui['client']; headers=ui['actors']['operator']['headers']
    p.set_viewport_size({'width':width,'height':height})
    login(ui)
    p.goto(BASE+'/imports')
    before=len(rows(db,'measurements'))
    p.get_by_test_id('import-files').set_input_files([{'name':n,'mimeType':'application/octet-stream','buffer':b} for n,b in ui['corpus']])
    # 上传预览要真实解析 4 个原件（含 2 个 Eoptics），首次调用需启动解析进程并预热数据库连接，
    # 6 秒默认值会在冷启动时误判失败，因此对解析类请求单独放宽等待时间。
    with p.expect_response(lambda r:'/imports/preview' in r.url and r.request.method=='POST',timeout=60000) as uploaded:
        p.get_by_test_id('upload-preview').click()
    job=uploaded.value.json()['data']
    p.get_by_test_id('import-job').wait_for()
    assert len(job['items'])==4 and len(rows(db,'measurements'))==before
    for item in job['items']:
        assert item['status']=='pending' and item['confirmation'] is None
        expect(p.get_by_test_id(f'select-item-{item["item_id"]}')).not_to_be_checked()
    assert p.get_by_role('button',name='下一步：确认提交',exact=True).is_disabled()
    parsed=[i for i in job['items'] if i['parse_result']['type']=='eoptics']
    others=[i for i in job['items'] if i not in parsed]
    assert len(parsed)==2
    capture(ui,'preview-pending')
    for item in parsed: configure(ui,item)
    configure(ui,others[0],'仅保存原件')
    # A real server response is received and then deliberately lost at the network boundary.
    lost=[]
    def lose(route):
        response=route.fetch(); assert response.status==200
        lost.append(response.json()['data'])
        route.abort('connectionreset')
    p.route('**/api/v1/imports/*/confirm',lose,times=1)
    submit(ui)
    p.get_by_test_id('retry-confirm').wait_for()
    capture(ui,'lost-response-retry')
    committed=len(rows(db,'measurements'))
    assert committed==before+sum(len(i['parse_result']['blocks']) for i in parsed)
    with p.expect_response(lambda r:'/confirm' in r.url and r.request.method=='POST',timeout=30000) as retried:
        p.get_by_test_id('retry-confirm').click()
    out=retried.value.json()['data']
    p.get_by_test_id('confirm-results').wait_for()
    assert out==lost[0] and len(rows(db,'measurements'))==committed
    assert out['pending_count']==1
    mids=[mid for i in out['items'] for mid in i.get('measurement_ids',[])]
    assert len(mids)==2
    # Exact raw values and anomaly flags must survive confirmation.
    points=rows(db,'measurement_points')
    for item,mid in zip(parsed,mids):
        expected=item['parse_result']['blocks'][0]['points']
        actual=[r for r in points if r['measurement_id']==mid]
        assert len(actual)==len(expected)
        for a,e in zip(actual,expected):
            assert a['raw_values']==e['raw_values'] and bool(a['is_outlier'])==e['is_outlier']
    assert sum(bool(r['is_outlier']) for r in points if r['measurement_id'] in mids)>=1
    capture(ui,'multi-confirm-results')
    p.reload();p.get_by_test_id('import-job').wait_for()
    pending=others[1]
    expect(p.get_by_test_id(f'select-item-{pending["item_id"]}')).not_to_be_checked()
    configure(ui,pending,'仅保存原件')
    with p.expect_response(lambda r:'/confirm' in r.url and r.request.method=='POST',timeout=30000) as continued: submit(ui)
    assert continued.value.json()['data']['pending_count']==0
    p.get_by_test_id('confirm-results').wait_for()
    assert len(rows(db,'measurements'))==committed
    # Upload same bytes into a fresh job: server rejects until reason explicitly supplied.
    p.goto(BASE+'/imports')
    name,content=ui['corpus'][0]
    p.get_by_test_id('import-files').set_input_files({'name':name,'mimeType':'application/octet-stream','buffer':content})
    with p.expect_response(lambda r:'/imports/preview' in r.url and r.request.method=='POST',timeout=30000) as dup: p.get_by_test_id('upload-preview').click()
    duplicate=dup.value.json()['data']['items'][0]
    p.get_by_test_id('import-job').wait_for()
    configure(ui,duplicate)
    with p.expect_response(lambda r:'/confirm' in r.url and r.request.method=='POST',timeout=30000) as denied_dup: submit(ui)
    assert denied_dup.value.status==409
    p.get_by_role('button',name='返回核对',exact=True).click()
    p.get_by_test_id(f'duplicate-{duplicate["item_id"]}').check()
    before_reason=len([r for r in ui['responses'] if '/confirm' in r[1] and r[0]=='POST'])
    p.get_by_role('button',name='下一步：确认提交',exact=True).click()
    p.get_by_test_id('import-step3-submit').click()
    p.get_by_text('确认重复时须填写原因。',exact=False).wait_for()
    assert len([r for r in ui['responses'] if '/confirm' in r[1] and r[0]=='POST'])==before_reason
    p.get_by_role('button',name='返回核对',exact=True).click()
    p.get_by_label('重复导入原因',exact=True).fill('验收同 SHA 独立版本，保留原始历史')
    with p.expect_response(lambda r:'/confirm' in r.url and r.request.method=='POST',timeout=30000) as accepted: submit(ui)
    replacement=accepted.value.json()['data']['items'][0]['measurement_ids'][0]
    p.get_by_test_id('confirm-results').wait_for()
    assert replacement not in mids and len(rows(db,'measurements'))==committed+1
    p.goto(BASE+f'/measurements?id={mids[0]}')
    p.get_by_test_id('measurement-detail').wait_for()
    expect(p.get_by_test_id('measurement-points').locator('tbody tr')).to_have_count(len(parsed[0]['parse_result']['blocks'][0]['points']))
    capture(ui,'measurement-detail')
    p.get_by_test_id('measurement-quality-note').fill('第三轮真实浏览器质量核对')
    p.get_by_test_id('measurement-quality-save').click()
    p.get_by_text('质量标记已保存',exact=True).wait_for()
    with p.expect_download() as download: p.locator('[data-testid^="measurement-download-"]').first.click()
    downloaded=Path(download.value.path()).read_bytes()
    assert hashlib.sha256(downloaded).hexdigest()==hashlib.sha256(content).hexdigest()
    p.get_by_test_id('measurement-replacement-id').fill(str(replacement))
    p.get_by_test_id('measurement-replacement-load').click();p.get_by_test_id('measurement-replacement-loaded').wait_for()
    p.get_by_test_id('measurement-supersede-reason').fill('验收取代关系，历史与测点保留')
    p.get_by_test_id('measurement-supersede-prepare').click();p.get_by_test_id('measurement-supersede-confirmation').wait_for()
    capture(ui,'supersede-confirmation')
    p.get_by_test_id('measurement-supersede-ack').check();p.get_by_test_id('measurement-supersede-submit').click()
    p.get_by_text('取代关系已保存，旧测量及测点历史保留',exact=True).wait_for()
    expect(p.get_by_test_id('measurement-detail')).to_contain_text('历史测量（保留）')
    # Demote fixture owner so viewer sees the exact same records and tasks.
    uid=ui['actors']['operator']['user']['user_id']
    response=client.patch(f'/api/v1/users/{uid}',headers=ui['actors']['admin']['headers'],json={'role':'viewer'})
    assert response.status_code==200,response.text
    ui['context'].clear_cookies();login(ui)
    writes=[]
    p.on('request',lambda r:writes.append((r.method,r.url)) if r.method in ('POST','PATCH','PUT','DELETE') and '/api/v1/' in r.url and '/auth/' not in r.url else None)
    p.goto(BASE+f'/imports?job={job["job_id"]}');p.get_by_test_id('import-job').wait_for()
    # 第四轮把导入页改为四步向导后，打开某个任务时不再渲染第 1 步的上传区，
    # 只读账户因此看不到上传控件（比旧版“显示但禁用”更明确）。原有用例保护的
    # 不变量逐条保留：只读提示可见、提交按钮禁用、第 1 步的上传控件即使可达也禁用。
    expect(p.get_by_test_id('imports-page')).to_contain_text('当前账户为只读')
    assert p.get_by_test_id('import-files').count()==0
    assert p.get_by_role('button',name='下一步：确认提交',exact=True).is_disabled()
    capture(ui,'viewer-imports')
    p.locator('.el-step').filter(has_text='① 上传').click()
    assert p.get_by_test_id('import-files').is_disabled()
    assert p.get_by_test_id('upload-preview').is_disabled()
    p.goto(BASE+f'/measurements?id={mids[0]}');p.get_by_test_id('measurement-readonly').wait_for()
    assert p.get_by_test_id('measurement-quality-save').is_disabled()
    capture(ui,'viewer-measurement')
    assert not writes,writes
    from app.security import limiter
    limiter.entries.clear()
    denials=p.evaluate('''async ({job,mid})=>{const a=await fetch('/api/v1/auth/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const t=(await a.json()).data.access_token;const h={'Content-Type':'application/json',Authorization:'Bearer '+t};return await Promise.all([fetch('/api/v1/imports/'+job+'/confirm',{method:'POST',headers:h,body:JSON.stringify({expected_row_version:1,items:[]})}),fetch('/api/v1/measurements/'+mid ,{method:'PATCH',headers:h,body:JSON.stringify({quality_flag:'good',expected_row_version:1})})]).then(rs=>rs.map(r=>r.status));}''',{'job':job['job_id'],'mid':mids[0]})
    assert denials==[403,403],denials
    assert not ui['errors'],ui['errors']
    elapsed=time.monotonic()-started
    print(f'WORKFLOW VERIFIED width={width}: files=4 real Eoptics=2 original-only=2 measurements=3 points={sum(len(i["parse_result"]["blocks"][0]["points"]) for i in parsed)+len(parsed[0]["parse_result"]["blocks"][0]["points"])} duplicate409=1 viewer403={denials} JS=0 UI writes as viewer=0 download SHA match; elapsed={elapsed:.2f}s')
    assert elapsed<60
