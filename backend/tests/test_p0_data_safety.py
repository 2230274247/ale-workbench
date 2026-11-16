"""P0 data-safety tests: environment isolation, backup integrity, restore guards.

These tests exercise real MySQL. They run only when ALE_DB_NAME points at an
independent `*_test` schema; the restore drills always write to a freshly created
`*_test` schema and never read from or write to the production database.
"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv('ALE_DB_NAME', '').endswith('_test'),
    reason='Independent test database required')

ROOT = Path(__file__).resolve().parents[2]
DATABASE_DIR = ROOT / 'database'
PYTHON = sys.executable
TEST_DB = os.getenv('ALE_DB_NAME', 'ale_workbench_test')

sys.path.insert(0, str(DATABASE_DIR))
import p0_utils as U  # noqa: E402


def run(*args, env_extra=None, timeout=900):
    env = os.environ.copy()
    env.setdefault('ALE_DB_HOST', '127.0.0.1')
    env.setdefault('ALE_DB_PORT', '3307')
    env.update(env_extra or {})
    return subprocess.run([PYTHON, *map(str, args)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout, check=False)


def backup_fixture(tmp_path, reason='pytest'):
    root = tmp_path / 'backups'
    return run(DATABASE_DIR / 'backup_db.py', '--database', TEST_DB, '--reason', reason,
               '--backup-root', root, '--keep', '0', '--no-originals'), root


# ---------------------------------------------------------------- environment isolation

def test_testing_environment_refuses_production_database():
    probe = subprocess.run([PYTHON, '-c', 'from app.config import database_name; print(database_name())'],
                           cwd=ROOT / 'backend', capture_output=True, text=True, timeout=120,
                           env={**os.environ, 'ALE_ENVIRONMENT': 'testing',
                                'ALE_DB_NAME': 'ale_workbench'})
    assert probe.returncode != 0
    assert 'ending with _test' in (probe.stderr + probe.stdout)


def test_testing_environment_defaults_to_test_database():
    probe = subprocess.run([PYTHON, '-c',
                            'from app.config import database_name, environment;'
                            'print(environment()["name"], database_name())'],
                           cwd=ROOT / 'backend', capture_output=True, text=True, timeout=120,
                           env={k: v for k, v in os.environ.items()
                                if k not in ('ALE_DB_NAME', 'ALE_ENVIRONMENT')}
                           | {'ALE_ENVIRONMENT': 'testing'})
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == 'testing ale_workbench_test'


def test_originals_root_follows_test_database():
    probe = subprocess.run([PYTHON, '-c',
                            'from app.original_storage import originals_root; print(originals_root())'],
                           cwd=ROOT / 'backend', capture_output=True, text=True, timeout=120,
                           env={k: v for k, v in os.environ.items()
                                if k != 'ALE_ORIGINALS_ROOT'} | {'ALE_DB_NAME': TEST_DB})
    assert probe.returncode == 0, probe.stderr
    assert 'storage-test' in probe.stdout


def test_migrate_refuses_production_without_confirmation():
    before = U.migration_state(U.connect(TEST_DB), TEST_DB)['applied_versions']
    result = run(DATABASE_DIR / 'migrate.py', env_extra={'ALE_DB_NAME': TEST_DB})
    assert result.returncode != 0
    assert '--confirm-production' in (result.stdout + result.stderr)
    after = U.migration_state(U.connect(TEST_DB), TEST_DB)['applied_versions']
    assert before == after


# ---------------------------------------------------------------- backup integrity

def test_backup_refuses_root_inside_project(tmp_path):
    result = run(DATABASE_DIR / 'backup_db.py', '--database', TEST_DB,
                 '--backup-root', ROOT / 'backups' / 'p0-inside-project')
    assert result.returncode != 0
    assert 'inside the project' in (result.stdout + result.stderr)


def test_backup_creates_verifiable_manifest(tmp_path):
    result, root = backup_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    directory = Path(result.stdout.split('Backup complete: ')[1].splitlines()[0].strip())
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'complete'
    assert manifest['database']['name'] == TEST_DB
    assert manifest['software']['app_version']
    assert manifest['database']['migration_version']
    assert manifest['database']['dump_sha256'] == U.sha256_file(directory / 'database.sql.gz')
    assert manifest['database']['row_counts']['schema_migrations'] > 0
    # SHA256SUMS must cover every file and be self-consistent
    sums = (directory / 'SHA256SUMS').read_text(encoding='utf-8').splitlines()
    assert sums
    for line in sums:
        digest, _, rel = line.partition('  ')
        assert U.sha256_file(directory / rel) == digest
    # the dump must not be able to switch schema during a restore
    assert U.dump_safety_scan(directory / 'database.sql.gz') == []


def test_corrupted_backup_is_rejected(tmp_path):
    result, _ = backup_fixture(tmp_path, reason='corrupt')
    assert result.returncode == 0, result.stderr
    directory = Path(result.stdout.split('Backup complete: ')[1].splitlines()[0].strip())
    dump = directory / 'database.sql.gz'
    payload = bytearray(dump.read_bytes())
    payload[len(payload) // 2] ^= 0xFF
    dump.write_bytes(payload)
    verify = run(DATABASE_DIR / 'restore_db.py', '--backup', directory,
                 '--target', f'ale_p0_{uuid.uuid4().hex[:8]}_test', '--verify-only')
    assert verify.returncode != 0
    assert 'SHA-256 mismatch' in (verify.stdout + verify.stderr)


# ---------------------------------------------------------------- restore guards and drills

def test_restore_refuses_production_target(tmp_path):
    result, _ = backup_fixture(tmp_path, reason='guard')
    directory = Path(result.stdout.split('Backup complete: ')[1].splitlines()[0].strip())
    refused = run(DATABASE_DIR / 'restore_db.py', '--backup', directory,
                  '--target', 'ale_workbench', '--replace')
    assert refused.returncode != 0
    assert 'production database can never be a restore target' in (refused.stdout + refused.stderr)


def test_restore_refuses_non_test_target(tmp_path):
    result, _ = backup_fixture(tmp_path, reason='guard2')
    directory = Path(result.stdout.split('Backup complete: ')[1].splitlines()[0].strip())
    refused = run(DATABASE_DIR / 'restore_db.py', '--backup', directory, '--target', 'ale_dev')
    assert refused.returncode != 0
    assert 'must end with _test' in (refused.stdout + refused.stderr)


def test_real_restore_round_trip_preserves_rows(tmp_path):
    result, _ = backup_fixture(tmp_path, reason='roundtrip')
    assert result.returncode == 0, result.stderr
    directory = Path(result.stdout.split('Backup complete: ')[1].splitlines()[0].strip())
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    target = f'ale_p0_roundtrip_{uuid.uuid4().hex[:8]}_test'
    try:
        restored = run(DATABASE_DIR / 'restore_db.py', '--backup', directory,
                       '--target', target, '--replace')
        assert restored.returncode == 0, restored.stderr + restored.stdout
        report_path = Path(restored.stdout.split('Report     ')[1].splitlines()[0].strip())
        report = json.loads(report_path.read_text(encoding='utf-8'))
        assert report['result'] == 'passed'
        assert report['details']['tables'] == manifest['database']['table_count']
        assert report['details']['rows'] == manifest['database']['row_counts']
        assert report['details']['orphans'] == []
        # read the restored data back through the application account, not just root
        probe = subprocess.run(
            [PYTHON, '-c',
             'from app.db import engine;'
             'from sqlalchemy import text;'
             'conn = engine().connect();'
             'print(conn.execute(text("SELECT COUNT(*) FROM quick_runs")).scalar());'
             'conn.close()'],
            cwd=ROOT / 'backend', capture_output=True, text=True, timeout=120,
            env={**os.environ, 'ALE_DB_NAME': target, 'ALE_ENVIRONMENT': 'testing'})
        assert probe.returncode == 0, probe.stderr
        assert int(probe.stdout.strip()) == manifest['database']['row_counts']['quick_runs']
    finally:
        conn = U.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS `{target}`')
        finally:
            conn.close()


def test_restore_verification_detects_missing_revisions(tmp_path):
    result, _ = backup_fixture(tmp_path, reason='detect')
    assert result.returncode == 0, result.stderr
    directory = Path(result.stdout.split('Backup complete: ')[1].splitlines()[0].strip())
    target = f'ale_p0_detect_{uuid.uuid4().hex[:8]}_test'
    try:
        restored = run(DATABASE_DIR / 'restore_db.py', '--backup', directory,
                       '--target', target, '--replace')
        assert restored.returncode == 0, restored.stderr + restored.stdout
        conn = U.connect(target)
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM quick_revisions')
                revisions = int(cur.fetchone()[0])
                if revisions == 0:
                    pytest.skip('test database has no revision history to remove')
                cur.execute('DELETE FROM quick_revisions ORDER BY revision_id LIMIT 1')
        finally:
            conn.close()
        verify = run(DATABASE_DIR / 'restore_db.py', '--backup', directory,
                     '--target', target, '--verify-only')
        assert verify.returncode == 3
        assert 'row count mismatch' in (verify.stdout + verify.stderr)
    finally:
        conn = U.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS `{target}`')
        finally:
            conn.close()


# ---------------------------------------------------------------- static guards

def test_migrations_contain_no_destructive_statements():
    """Comments are stripped first: the footer of 0016 documents the prohibition."""
    forbidden = ('drop table', 'drop column', 'truncate', 'delete from')
    for file in sorted((DATABASE_DIR / 'migrations').glob('*.sql')):
        sql = '\n'.join(line.split('--', 1)[0] for line in
                        file.read_text(encoding='utf-8').splitlines())
        text = sql.lower()
        for token in forbidden:
            assert token not in text, f'{file.name} contains {token}'


def test_gitignore_covers_credentials_and_real_data():
    lines = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    entries = {line.strip() for line in lines if line.strip() and not line.startswith('#')}
    for required in ('backend/.env', 'database/.dbcreds', 'database/.appcreds',
                     'mysql_data/', 'storage/', 'backups/*'):
        assert required in entries, f'.gitignore missing {required}'
