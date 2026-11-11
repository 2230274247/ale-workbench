import hmac
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, Request, Response, Body
from sqlalchemy import select, func
from sqlalchemy.dialects.mysql import insert as mysql_insert
from . import schemas as S
from .db import get_db, table
from .common import envelope, fail, dbnow, audit
from .security import current_user, limiter, hasher, verify, new_session, cookie, decode, valid_session, digest, tokens, cookie_origin, revoke_all, REFRESH_SECONDS
from .config import BACKEND, environment

router=APIRouter(prefix='/api/v1/auth',tags=['Authentication'])

@router.get('/setup-status')
def setup_status(request:Request,db=Depends(get_db)):
    required=not db.scalar(select(func.count()).select_from(table('users')))
    return envelope(request,{'needs_setup':required})

@router.post('/setup',status_code=201,dependencies=[Depends(limiter.check)])
def setup(body:S.Setup,request:Request,response:Response,db=Depends(get_db)):
    try:expected=(BACKEND/'.setup-code').read_text().strip()
    except OSError:fail(503,'Setup code is not configured')
    if not expected or not hmac.compare_digest(expected.encode(),body.setup_code.encode()):fail(403)
    settings=table('app_settings')
    statement=mysql_insert(settings).values(setting_key='setup_lock',setting_value='locked',updated_at=dbnow())
    db.execute(statement.on_duplicate_key_update(setting_key=statement.inserted.setting_key))
    db.execute(select(settings).where(settings.c.setting_key=='setup_lock').with_for_update()).first()
    if db.scalar(select(func.count()).select_from(table('users'))):fail(409)
    u=table('users')
    uid=db.execute(u.insert().values(username=body.username,display_name=body.display_name,password_hash=hasher.hash(body.password),role='admin',account_purpose='management',status='active',token_version=0)).inserted_primary_key[0]
    user=dict(db.execute(select(u).where(u.c.user_id==uid)).mappings().one())
    audit(db,uid,'insert','user',uid)
    return envelope(request,user)

@router.post('/login',dependencies=[Depends(limiter.check)])
def login(body:S.Login,request:Request,response:Response,db=Depends(get_db)):
    u=table('users');user=db.execute(select(u).where(u.c.username==body.username).with_for_update()).mappings().first()
    if not verify(body.password,user['password_hash'] if user else None) or not user or user['status']!='active':fail(401,'Invalid credentials')
    pair=new_session(db,user);cookie(response,pair);audit(db,user['user_id'],'login','user',user['user_id'])
    return envelope(request,{'token':pair,'user':dict(user)})

@router.post('/register',status_code=201,dependencies=[Depends(limiter.check)])
def register(body:S.Register,request:Request,response:Response,db=Depends(get_db)):
    inv=table('invitations');u=table('users')
    invitation=db.execute(select(inv).where(inv.c.code_hash==digest(body.invite_code)).with_for_update()).mappings().first()
    if not invitation or invitation['used_at'] or invitation['revoked_at'] or invitation['expires_at']<=dbnow():fail(409,'Registration cannot be completed')
    role=invitation['role'];purpose=invitation['account_purpose']
    if role not in ('operator','viewer') or purpose not in ('research','testing'):fail(409,'Registration cannot be completed')
    # Unique-key errors propagate to the transaction dependency, rolling back invitation consumption.
    uid=db.execute(u.insert().values(username=body.username,display_name=body.display_name,email=body.email or None,password_hash=hasher.hash(body.password),role=role,account_purpose=purpose,status='active',token_version=0)).inserted_primary_key[0]
    db.execute(inv.update().where(inv.c.invitation_id==invitation['invitation_id']).values(used_by=uid,used_at=dbnow()))
    user=dict(db.execute(select(u).where(u.c.user_id==uid)).mappings().one())
    audit(db,uid,'insert','user',uid);return envelope(request,user)

@router.post('/refresh',dependencies=[Depends(limiter.check)])
def refresh(request:Request,response:Response,body:S.Refresh=Body(default=S.Refresh()),db=Depends(get_db)):
    raw=body.refresh_token
    if not raw:
        cookie_origin(request);raw=request.cookies.get('ale_refresh')
    if not raw:fail(401)
    p=decode(raw,'refresh')
    # Lock user before session, matching password/status updates and avoiding inverted lock order.
    db.execute(select(table('users')).where(table('users').c.user_id==int(p['sub'])).with_for_update()).first()
    user,session=valid_session(db,p,lock=True)
    if not hmac.compare_digest(session['refresh_jti_hash'],digest(p['jti'])):fail(401)
    jti=secrets.token_urlsafe(32);s=table('auth_sessions')
    db.execute(s.update().where(s.c.session_id==p['sid']).values(refresh_jti_hash=digest(jti),expires_at=dbnow()+timedelta(seconds=REFRESH_SECONDS)))
    pair=tokens(user,p['sid'],jti);cookie(response,pair)
    return envelope(request,pair)

@router.post('/logout')
def logout(request:Request,response:Response,user=Depends(current_user),db=Depends(get_db)):
    cookie_origin(request)
    s=table('auth_sessions');db.execute(s.update().where(s.c.session_id==request.state.session_id).values(revoked_at=dbnow()))
    response.delete_cookie('ale_refresh',path='/api/v1/auth',httponly=True,secure=False,samesite='strict')
    return envelope(request)

@router.get('/me')
def me(request:Request,user=Depends(current_user)):
    permissions=['batch:read','sample:read']
    if user['role'] in ('admin','operator'):permissions+=['batch:write','sample:write']
    if user['role']=='admin':permissions+=['batch:delete','sample:delete','user:read','user:write','audit:read','invitation:write']
    return envelope(request,{'user':user,'permissions':permissions,'data_scope':'all' if user['role']=='admin' else 'own','environment':environment()})

@router.put('/password')
def password(body:S.ChangePassword,request:Request,user=Depends(current_user),db=Depends(get_db)):
    u=table('users');locked=db.execute(select(u).where(u.c.user_id==user['user_id']).with_for_update()).mappings().one()
    if not verify(body.old_password,locked['password_hash']):fail(401,'Invalid credentials')
    db.execute(u.update().where(u.c.user_id==user['user_id']).values(password_hash=hasher.hash(body.new_password)))
    revoke_all(db,user['user_id']);audit(db,user['user_id'],'update','user',user['user_id'])
    return envelope(request)
