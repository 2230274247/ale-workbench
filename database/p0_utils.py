"""Shared plumbing for the P0 data-safety scripts (backup / restore / pre-upgrade).

Design rules:
* No credential is ever printed, logged or written to a manifest. Passwords reach
  the MySQL clients only through a temporary --defaults-extra-file that is removed
  immediately after use.
* Production and test targets are separated by name; production is never a default
  restore target.
* Every check returns data, never raises for an expected condition, so callers can
  report all findings at once.
"""
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_DATABASE = 'ale_workbench'
TEST_SUFFIX = '_test'
CHUNK = 1024 * 1024

# Ordered list used in reports and restore verification. Only includes tables that
# carry scientific meaning or traceability; empty tables are still reported as 0.
KEY_TABLES = (
    'users', 'batches', 'samples', 'experiment_plans', 'experiment_plan_steps',
    'processes', 'process_steps', 'process_samples', 'sample_transitions',
    'measurements', 'measurement_points', 'derived_results', 'source_files',
    'source_file_occurrences', 'import_jobs', 'import_items', 'attachments',
    'audit_log', 'quick_runs', 'quick_results', 'quick_steps', 'quick_revisions',
    'quick_imports', 'quick_materials', 'quick_sources', 'quick_templates',
    'schema_migrations', 'schema_migration_attempts',
)

# (child table, child column, parent table, parent column) - referential integrity
# checks that must survive a restore.
KEY_RELATIONS = (
    ('quick_runs', 'process_id', 'processes', 'process_id'),
    ('quick_results', 'run_id', 'quick_runs', 'process_id'),
    ('quick_steps', 'run_id', 'quick_runs', 'process_id'),
    ('quick_revisions', 'process_id', 'quick_runs', 'process_id'),
    ('quick_imports', 'process_id', 'quick_runs', 'process_id'),
    ('process_steps', 'process_id', 'processes', 'process_id'),
    ('process_samples', 'process_id', 'processes', 'process_id'),
    ('process_samples', 'sample_id', 'samples', 'sample_id'),
    ('sample_transitions', 'sample_id', 'samples', 'sample_id'),
    ('measurements', 'sample_id', 'samples', 'sample_id'),
    ('experiment_plan_steps', 'plan_id', 'experiment_plans', 'plan_id'),
)


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def utc_stamp(moment=None):
    return (moment or utc_now()).strftime('%Y%m%dT%H%M%SZ')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def app_version():
    sys.path.insert(0, str(ROOT / 'backend'))
    try:
        from app.version import APP_VERSION
        return APP_VERSION
    finally:
        sys.path.pop(0)


def git_state():
    """Code identity next to the data identity; missing git is not an error."""
    state = {'commit': None, 'dirty': None, 'branch': None}
    if not (ROOT / '.git').exists():
        return state
    for key, args in (('commit', ['rev-parse', 'HEAD']),
                      ('branch', ['rev-parse', '--abbrev-ref', 'HEAD']),
                      ('dirty', ['status', '--porcelain'])):
        try:
            out = subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                                 text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            return state
        if out.returncode != 0:
            continue
        value = out.stdout.strip()
        state[key] = bool(value) if key == 'dirty' else value
    return state


def db_settings():
    return {
        'host': os.getenv('ALE_DB_HOST', '127.0.0.1'),
        'port': int(os.getenv('ALE_DB_PORT', '3307')),
    }


def admin_credentials():
    sys.path.insert(0, str(ROOT / 'database'))
    try:
        from apply_schema import load_admin_creds
        user, password = load_admin_creds()
    finally:
        sys.path.pop(0)
    if not user:
        raise RuntimeError('MySQL administrator credentials are not configured in database/.dbcreds')
    return user, password


def mysql_client(name):
    """Locate mysql.exe / mysqldump.exe: ALE_MYSQL_BIN, bundled server, then PATH."""
    candidates = []
    configured = os.getenv('ALE_MYSQL_BIN', '').strip()
    if configured:
        candidates.append(Path(configured) / (name + '.exe'))
        candidates.append(Path(configured) / name)
    candidates.append(ROOT / 'mysql-server' / 'bin' / (name + '.exe'))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f'{name} was not found. Set ALE_MYSQL_BIN to the MySQL bin directory.')


class ClientDefaults:
    """Temporary credential file for mysql clients; removed on exit."""

    def __init__(self):
        handle, path = tempfile.mkstemp(prefix='ale-mysql-', suffix='.cnf')
        user, password = admin_credentials()
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write('[client]\n')
            stream.write(f'user={user}\n')
            stream.write(f'password={password}\n')
        self.path = path

    def __enter__(self):
        return self.path

    def __exit__(self, *_):
        Path(self.path).unlink(missing_ok=True)

    @staticmethod
    def redact(text):
        """Clients may echo the option name; never let a password reach a log."""
        return '\n'.join(line for line in (text or '').splitlines()
                         if 'password' not in line.lower())


def connect(database=None, autocommit=True):
    import pymysql
    settings = db_settings()
    user, password = admin_credentials()
    return pymysql.connect(host=settings['host'], port=settings['port'], user=user,
                           password=password, database=database, charset='utf8mb4',
                           autocommit=autocommit, connect_timeout=10)


def quote(name):
    return '`' + name.replace('`', '``') + '`'


def server_info(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT VERSION(), @@hostname, @@port, @@lower_case_table_names')
        version, hostname, port, lower = cur.fetchone()
        cur.execute('SELECT @@sql_mode')
        sql_mode = cur.fetchone()[0]
    return {'version': version, 'hostname': hostname, 'port': int(port),
            'lower_case_table_names': int(lower), 'sql_mode': sql_mode}


def database_exists(conn, name):
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (name,))
        return cur.fetchone()[0] > 0


def object_stats(conn, database):
    with conn.cursor() as cur:
        cur.execute("SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_TYPE, TABLE_NAME", (database,))
        rows = cur.fetchall()
        cur.execute('SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS '
                    'WHERE CONSTRAINT_SCHEMA=%s', (database,))
        foreign_keys = cur.fetchone()[0]
    tables = [name for name, kind in rows if kind == 'BASE TABLE']
    views = [name for name, kind in rows if kind != 'BASE TABLE']
    return {'tables': tables, 'views': views,
            'table_count': len(tables), 'view_count': len(views),
            'foreign_keys': foreign_keys}


def row_counts(conn, database, tables):
    """Exact counts. Used as the authoritative comparison for backup vs restore."""
    counts = {}
    with conn.cursor() as cur:
        for name in tables:
            cur.execute(f'SELECT COUNT(*) FROM {quote(database)}.{quote(name)}')
            counts[name] = int(cur.fetchone()[0])
    return counts


def data_bytes(conn, database):
    with conn.cursor() as cur:
        cur.execute('SELECT COALESCE(SUM(DATA_LENGTH + INDEX_LENGTH),0) FROM information_schema.TABLES '
                    'WHERE TABLE_SCHEMA=%s', (database,))
        return int(cur.fetchone()[0] or 0)


def migration_state(conn, database):
    """Applied ledger plus the ledger of files shipped with this code."""
    state = {'applied': [], 'pending': [], 'unknown_in_db': [], 'checksum_drift': []}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
                    "AND TABLE_NAME='schema_migrations'", (database,))
        if not cur.fetchone()[0]:
            return state
        cur.execute(f'SELECT version, filename, sha256, applied_at FROM '
                    f'{quote(database)}.schema_migrations ORDER BY version')
        applied = {row[0]: {'filename': row[1], 'sha256': row[2], 'applied_at': str(row[3])}
                   for row in cur.fetchall()}
    files = sorted((ROOT / 'database' / 'migrations').glob('*.sql'))
    shipped = {}
    for file in files:
        version = file.stem.split('_')[0]
        shipped[version] = {'filename': file.name, 'sha256': sha256_file(file)}
    for version in sorted(shipped):
        if version not in applied:
            state['pending'].append(shipped[version])
        elif applied[version]['sha256'] != shipped[version]['sha256']:
            state['checksum_drift'].append({'version': version, 'applied': applied[version],
                                            'shipped': shipped[version]})
    for version in sorted(applied):
        if version not in shipped:
            state['unknown_in_db'].append({'version': version, **applied[version]})
    state['applied'] = [{'version': v, **applied[v]} for v in sorted(applied)]
    state['applied_versions'] = sorted(applied)
    state['target_version'] = max(shipped) if shipped else None
    return state


def originals_root():
    configured = os.getenv('ALE_ORIGINALS_ROOT', '').strip()
    if configured:
        return Path(configured)
    return ROOT / 'storage' / 'originals'


def originals_inventory(root):
    """Every regular file with its digest, relative to the originals root."""
    root = Path(root)
    entries = []
    if not root.is_dir():
        return entries
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        entries.append({'path': path.relative_to(root).as_posix(),
                        'bytes': stat.st_size, 'sha256': sha256_file(path)})
    return entries


def default_backup_root():
    configured = os.getenv('ALE_BACKUP_ROOT', '').strip()
    return Path(configured) if configured else ROOT.parent / 'ALE_Backups'


def is_inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def free_bytes(path):
    target = Path(path)
    while not target.exists() and target != target.parent:
        target = target.parent
    return shutil.disk_usage(target).free


def log_line(log_path, message):
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().astimezone().strftime('%Y-%m-%d %H:%M:%S%z')
    with open(log_path, 'a', encoding='utf-8') as stream:
        stream.write(f'{stamp} {message}\n')


def write_json(path, payload):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                         encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def looks_like_scratch(name):
    return name.endswith(TEST_SUFFIX) and name != PRODUCTION_DATABASE


def dump_database(database, target_gz, log_path):
    """Consistent logical dump (InnoDB single transaction) streamed through gzip."""
    target_gz = Path(target_gz)
    target_gz.parent.mkdir(parents=True, exist_ok=True)
    settings = db_settings()
    with ClientDefaults() as defaults, tempfile.TemporaryFile() as errors:
        command = [mysql_client('mysqldump'),
                   f'--defaults-extra-file={defaults}',
                   f'--host={settings["host"]}', f'--port={settings["port"]}',
                   '--single-transaction', '--quick', '--skip-lock-tables',
                   '--default-character-set=utf8mb4', '--no-tablespaces',
                   '--routines', '--triggers', '--hex-blob',
                   '--max-allowed-packet=512M',
                   database]  # positional, never --databases: keeps CREATE DATABASE/USE out
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        with gzip.open(target_gz, 'wb', compresslevel=6) as stream:
            while True:
                chunk = process.stdout.read(CHUNK)
                if not chunk:
                    break
                stream.write(chunk)
        process.stdout.close()
        code = process.wait()
        errors.seek(0)
        detail = ClientDefaults.redact(errors.read().decode('utf-8', 'replace')).strip()
    if code != 0:
        target_gz.unlink(missing_ok=True)
        log_line(log_path, f'BACKUP_FAILED stage=dump database={database} exit={code}')
        raise RuntimeError('mysqldump failed: ' + (detail or f'exit code {code}'))
    if target_gz.stat().st_size == 0:
        target_gz.unlink(missing_ok=True)
        raise RuntimeError('mysqldump produced an empty file')
    with gzip.open(target_gz, 'rb') as stream:
        if not stream.read(1024):
            target_gz.unlink(missing_ok=True)
            raise RuntimeError('backup archive is not readable')
    return target_gz


def import_database(database, source_gz, log_path):
    """Restore a gzip dump into an existing empty database."""
    unsafe = dump_safety_scan(source_gz)
    if unsafe:
        raise RuntimeError('refusing to import a dump that switches schema: '
                           + '; '.join(unsafe[:3]))
    settings = db_settings()
    with ClientDefaults() as defaults, tempfile.TemporaryFile() as errors:
        command = [mysql_client('mysql'),
                   f'--defaults-extra-file={defaults}',
                   f'--host={settings["host"]}', f'--port={settings["port"]}',
                   '--default-character-set=utf8mb4', '--max-allowed-packet=512M',
                   '--database', database]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        with gzip.open(source_gz, 'rb') as stream:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                process.stdin.write(chunk)
        process.stdin.close()
        code = process.wait()
        errors.seek(0)
        detail = ClientDefaults.redact(errors.read().decode('utf-8', 'replace')).strip()
    if code != 0:
        log_line(log_path, f'RESTORE_FAILED stage=import database={database} exit={code}')
        raise RuntimeError('mysql import failed: ' + (detail or f'exit code {code}'))


def dump_safety_scan(path):
    """A dump must never carry its own CREATE DATABASE / USE: that would let a
    restore aimed at a drill schema silently write the production schema."""
    findings = []
    pattern = re.compile(rb'^\s*(CREATE\s+DATABASE|USE\s+)', re.I | re.M)
    with gzip.open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            for match in pattern.finditer(chunk):
                statement = match.group(0).decode('utf-8', 'replace').strip()
                findings.append(statement)
                if len(findings) >= 5:
                    return findings
    return findings


def create_database(conn, name, drop=False):
    with conn.cursor() as cur:
        if drop:
            cur.execute(f'DROP DATABASE IF EXISTS {quote(name)}')
        cur.execute(f'CREATE DATABASE {quote(name)} CHARACTER SET utf8mb4 '
                    'COLLATE utf8mb4_0900_ai_ci')


def grant_app_read(conn, name):
    """Read-only grant so a drill database can be inspected by the app account."""
    with conn.cursor() as cur:
        cur.execute("SELECT Host FROM mysql.user WHERE User='ale_app'")
        for (host,) in cur.fetchall():
            cur.execute(f"GRANT SELECT ON {quote(name)}.* TO %s@%s", ('ale_app', host))
        cur.execute('FLUSH PRIVILEGES')


def orphan_report(conn, database):
    """Referential integrity that foreign keys alone cannot protect across restores."""
    findings = []
    with conn.cursor() as cur:
        for child, child_column, parent, parent_column in KEY_RELATIONS:
            try:
                cur.execute(
                    f'SELECT COUNT(*) FROM {quote(database)}.{quote(child)} c '
                    f'LEFT JOIN {quote(database)}.{quote(parent)} p '
                    f'ON p.{quote(parent_column)} = c.{quote(child_column)} '
                    f'WHERE c.{quote(child_column)} IS NOT NULL AND p.{quote(parent_column)} IS NULL')
                count = int(cur.fetchone()[0])
            except Exception as exc:  # table absent in an older schema: report, do not crash
                findings.append({'relation': f'{child}.{child_column}->{parent}.{parent_column}',
                                 'error': type(exc).__name__})
                continue
            findings.append({'relation': f'{child}.{child_column}->{parent}.{parent_column}',
                             'orphans': count})
    return findings
