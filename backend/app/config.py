"""Configuration: never include credential values in diagnostics."""
import configparser
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
load_dotenv(BACKEND / '.env', override=False)

# The only database that holds real scientific records. Environment isolation is
# enforced by name so a forgotten variable can never surface as a production write.
PRODUCTION_DATABASE = 'ale_workbench'
TEST_DATABASE_SUFFIX = '_test'


def environment():
    """Deployment identity comes only from explicit instance configuration."""
    name = os.getenv('ALE_ENVIRONMENT', 'production')
    if name not in ('production', 'testing'):
        raise RuntimeError('ALE_ENVIRONMENT must be production or testing')
    default_label = '生产环境' if name == 'production' else '测试环境'
    default_instance = ('ale-workbench-production' if name == 'production'
                        else 'ale-workbench-testing')
    return {'name': name,
            'label': os.getenv('ALE_ENVIRONMENT_LABEL', default_label),
            'instance_id': os.getenv('ALE_INSTANCE_ID', default_instance)}


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


def database_name():
    """Resolve and validate the target schema before any connection is created.

    testing  -> must end with `_test` and defaults to `<production>_test`
    production -> may never be pointed at a scratch schema by accident; a `_test`
                  name is tolerated so read-only harnesses can run with the label
                  untouched, but it is never treated as the production database.
    """
    explicit = os.getenv('ALE_DB_NAME', '').strip()
    name = explicit or (PRODUCTION_DATABASE + TEST_DATABASE_SUFFIX
                        if environment()['name'] == 'testing'
                        else credentials().get('database', PRODUCTION_DATABASE))
    if not re.fullmatch(r'[A-Za-z0-9_]+', name):
        raise RuntimeError('ALE_DB_NAME may contain only letters, digits and underscores')
    if environment()['name'] == 'testing' and not name.endswith(TEST_DATABASE_SUFFIX):
        raise RuntimeError(
            'ALE_ENVIRONMENT=testing requires an independent database ending with '
            f'{TEST_DATABASE_SUFFIX}; refusing to connect to {name!r}')
    return name


def database_url():
    c = credentials()
    return URL.create('mysql+pymysql', username='ale_app', password=os.getenv('ALE_DB_PASSWORD', c.get('password')),
                      host=os.getenv('ALE_DB_HOST', '127.0.0.1' if os.name == 'nt' else '172.16.10.254'),
                      port=int(os.getenv('ALE_DB_PORT', '3307')),
                      database=database_name(),
                      query={'charset': 'utf8mb4'})


def jwt_secret():
    value = os.getenv('ALE_JWT_SECRET', '')
    if len(value) < 32:
        raise RuntimeError('Configure ALE_JWT_SECRET in backend/.env (at least 32 characters)')
    return value

COOKIE_SECURE = os.getenv('ALE_COOKIE_SECURE', 'false').lower() == 'true'
ALLOWED_ORIGINS = tuple(x.strip() for x in os.getenv('ALE_ALLOWED_ORIGINS', '').split(',') if x.strip())
