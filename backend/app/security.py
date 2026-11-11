import hashlib
import hmac
import secrets
import time
import uuid
import threading
from collections import OrderedDict, deque
from datetime import timedelta
from urllib.parse import urlsplit
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, Request
from sqlalchemy import select
from .config import jwt_secret, ALLOWED_ORIGINS, COOKIE_SECURE
from .db import get_db, table
from .common import fail, dbnow, now

hasher=PasswordHasher()
DUMMY_HASH=hasher.hash(secrets.token_urlsafe(32))
ACCESS_SECONDS=3600
REFRESH_SECONDS=604800

def digest(text):return hashlib.sha256(text.encode()).hexdigest()
def verify(password, hashed):
    try:return hasher.verify(hashed or DUMMY_HASH,password) and bool(hashed)
    except (VerificationError,InvalidHashError):return False

def decode(token, kind):
    try:
        p=jwt.decode(token,jwt_secret(),algorithms=['HS256'],options={'require':['exp','iat','sub','sid','jti','ver','typ']})
        if p['typ']!=kind or not isinstance(p['ver'],int):fail(401)
        int(p['sub']);uuid.UUID(p['sid'])
        return p
    except (jwt.PyJWTError,ValueError,TypeError,KeyError):fail(401)

def valid_session(db,p,lock=False):
    s=table('auth_sessions');u=table('users')
    q=select(s).where(s.c.session_id==p['sid'],s.c.user_id==int(p['sub']))
    if lock:q=q.with_for_update()
    session=db.execute(q).mappings().first()
    user=db.execute(select(u).where(u.c.user_id==int(p['sub']))).mappings().first()
    if not session or session['revoked_at'] or session['expires_at']<=dbnow() or not user or user['status']!='active' or user['token_version']!=p['ver']:fail(401)
    return dict(user),dict(session)

def current_user(request:Request,db=Depends(get_db)):
    auth=request.headers.get('authorization','')
    if not auth.startswith('Bearer '):fail(401)
    p=decode(auth[7:],'access');user,session=valid_session(db,p)
    request.state.session_id=session['session_id']
    user['_session_id']=session['session_id']
    return user

def admin(user=Depends(current_user)):
    if user['role']!='admin':fail(403)
    return user

def writer(user=Depends(current_user)):
    if user['role'] not in ('admin','operator'):fail(403)
    return user

def tokens(user,sid,refresh_jti):
    issued=now()
    def token(kind,seconds,jti):
        return jwt.encode(dict(sub=str(user['user_id']),sid=sid,ver=user['token_version'],typ=kind,jti=jti,iat=issued,exp=issued+timedelta(seconds=seconds)),jwt_secret(),algorithm='HS256')
    return dict(access_token=token('access',ACCESS_SECONDS,str(uuid.uuid4())),refresh_token=token('refresh',REFRESH_SECONDS,refresh_jti),token_type='Bearer',expires_in=ACCESS_SECONDS,refresh_expires_in=REFRESH_SECONDS)

def new_session(db,user):
    sid=str(uuid.uuid4());jti=secrets.token_urlsafe(32)
    db.execute(table('auth_sessions').insert().values(session_id=sid,user_id=user['user_id'],refresh_jti_hash=digest(jti),expires_at=dbnow()+timedelta(seconds=REFRESH_SECONDS),created_at=dbnow()))
    return tokens(user,sid,jti)

def cookie(response,pair):
    response.set_cookie('ale_refresh',pair['refresh_token'],max_age=REFRESH_SECONDS,httponly=True,secure=COOKIE_SECURE,samesite='strict',path='/api/v1/auth')

def allowed_origin(origin):
    if origin in ALLOWED_ORIGINS:return True
    try:
        p=urlsplit(origin)
        return p.scheme in ('http','https') and p.hostname in ('localhost','127.0.0.1','172.16.10.3') and not p.username and not p.password and p.path in ('','/') and not p.query and not p.fragment
    except ValueError:return False

def cookie_origin(request):
    origin=request.headers.get('origin')
    if origin and not allowed_origin(origin):fail(403)
    if not origin and request.headers.get('sec-fetch-site')=='cross-site':fail(403)

def revoke_all(db,uid):
    u=table('users');s=table('auth_sessions')
    db.execute(u.update().where(u.c.user_id==uid).values(token_version=u.c.token_version+1))
    db.execute(s.update().where(s.c.user_id==uid,s.c.revoked_at.is_(None)).values(revoked_at=dbnow()))

class RateLimiter:
    """Bounded single-process limiter; client address is not taken from forwarded headers."""
    def __init__(self):self.entries=OrderedDict();self.lock=threading.Lock()
    def check(self,request:Request):
        key=request.client.host if request.client else 'unknown';t=time.monotonic()
        with self.lock:
            while self.entries and next(iter(self.entries.values()))[-1]<=t-60:self.entries.popitem(last=False)
            queue=self.entries.pop(key,deque())
            while queue and queue[0]<=t-60:queue.popleft()
            if len(queue)>=10:
                self.entries[key]=queue;fail(429,'Too many authentication attempts; try again later')
            queue.append(t);self.entries[key]=queue
            while len(self.entries)>10000:self.entries.popitem(last=False)
limiter=RateLimiter()
