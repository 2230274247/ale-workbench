"""Configuration: never include credential values in diagnostics."""
import configparser
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
load_dotenv(BACKEND / '.env', override=False)


def environment():
    """Deployment identity comes only from explicit instance configuration."""
    name = os.getenv('ALE_ENVIRONMENT', 'production')
    if name not in ('production', 'testing'):
        raise RuntimeError('ALE_ENVIRONMENT must be production or testing')
    return {'name': name,
            'label': os.getenv('ALE_ENVIRONMENT_LABEL', '生产环境'),
            'instance_id': os.getenv('ALE_INSTANCE_ID', 'ale-workbench-production')}


def credentials():
    text = (ROOT / 'database' / '.appcreds').read_text(encoding='utf-8-sig')
    accounts = []
    if any(line.strip().startswith('[') for line in text.splitlines()):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        accounts = [dict(parser[s]) for s in parser.sections()]
    else:
        account = {}
        common = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(('#', ';')) or '=' not in line:
                continue
            key, value = (v.strip() for v in line.split('=', 1))
            if key == 'user' and 'user' in account:
                accounts.append({**common, **account})
                account = {}
            if key in ('host', 'port', 'database'):
                common[key] = value
            else:
                account[key] = value
        if account:
            accounts.append({**common, **account})
    account = next((a for a in accounts if a.get('user', a.get('username')) == 'ale_app'), None)
    if account is None:
        raise RuntimeError('Application database account ale_app is not configured')
    return account


def database_url():
    c = credentials()
    return URL.create('mysql+pymysql', username='ale_app', password=os.getenv('ALE_DB_PASSWORD', c.get('password')),
                      host=os.getenv('ALE_DB_HOST', '127.0.0.1' if os.name == 'nt' else '172.16.10.254'),
                      port=int(os.getenv('ALE_DB_PORT', '3307')),
                      database=os.getenv('ALE_DB_NAME', c.get('database', 'ale_workbench')),
                      query={'charset': 'utf8mb4'})


def jwt_secret():
    value = os.getenv('ALE_JWT_SECRET', '')
    if len(value) < 32:
        raise RuntimeError('Configure ALE_JWT_SECRET in backend/.env (at least 32 characters)')
    return value

COOKIE_SECURE = os.getenv('ALE_COOKIE_SECURE', 'false').lower() == 'true'
ALLOWED_ORIGINS = tuple(x.strip() for x in os.getenv('ALE_ALLOWED_ORIGINS', '').split(',') if x.strip())
