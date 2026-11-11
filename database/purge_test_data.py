"""Purge user-confirmed test accounts, business rows and their originals.

Default is a dry run. ``--execute`` performs, inside one transaction:

1. a full snapshot under ``backups/before_account_purge_*`` (same format as migrate.py);
2. deletion of every business row, then sessions, invitations and users;
3. removal of content-addressed originals whose SHA is no longer referenced,
   only after re-verifying the file bytes against its SHA-256 name.

Never touches ``schema_migrations``, ``schema_migration_attempts`` or
``app_settings``; never issues DDL; never prints credentials or password hashes.
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

import pymysql
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'database'))
sys.path.insert(0, str(ROOT / 'backend'))
from apply_schema import load_admin_creds  # noqa: E402
from migrate import snapshot  # noqa: E402

KEEP = {'schema_migrations', 'schema_migration_attempts', 'app_settings'}

# Children before parents; every step is a plain DELETE (no cascade, no DDL).
ORDER = [
    'ai_messages', 'ai_tool_traces', 'ai_requests', 'ai_conversations',
    'ai_budget_periods', 'ai_config',
    'measurement_points', 'sample_transitions', 'derived_results',
    'instrument_datapoints', 'instrument_channels', 'instrument_datasets',
    'measurements',
    'source_file_occurrences', 'import_confirmations', 'import_items', 'import_jobs',
    'process_samples', 'process_steps', 'processes',
    'experiment_plan_steps', 'experiment_plans',
    'samples', 'batches', 'recipes', 'source_files', 'optical_models',
    'chemistry_step_templates', 'chemistry_species', 'chemistry_systems',
    'step_parameter_templates',
    'issues_links', 'issues', 'findings', 'attachments',
    'audit_log', 'auth_sessions', 'invitations', 'users',
]

# SHA sources that may reference an original without a source_files row.
SHA_SOURCES = [('source_files', 'file_sha256'), ('import_items', 'sha256'),
               ('attachments', 'file_sha256'), ('batches', 'source_zip_sha256')]


def originals_root():
    return Path(os.getenv('ALE_ORIGINALS_ROOT', ROOT / 'storage' / 'originals'))


def sha_set(cur):
    values = set()
    for table, column in SHA_SOURCES:
        try:
            cur.execute(f'SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL')
        except pymysql.err.ProgrammingError:
            continue
        values.update(row[0] for row in cur.fetchall())
    return values


def storage_path(sha):
    return originals_root() / sha[:2] / sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--allow-production', action='store_true',
                        help='required to purge a database whose name does not end with _test')
    args = parser.parse_args()
    db_name = os.getenv('ALE_DB_NAME', 'ale_workbench')
    if not db_name.endswith('_test') and not args.allow_production:
        raise SystemExit('Refusing to purge a non-test database; use an independent *_test database '
                         'or pass --allow-production after explicit approval')
    user, password = load_admin_creds()
    conn = pymysql.connect(host=os.getenv('ALE_DB_HOST', '127.0.0.1' if os.name == 'nt' else '172.16.10.254'),
                           port=int(os.getenv('ALE_DB_PORT', '3307')), user=user, password=password,
                           database=db_name, charset='utf8mb4', autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT GET_LOCK(%s,10)', ('ale_workbench_migrations',))
            if cur.fetchone()[0] != 1:
                raise RuntimeError('Another migration or purge is running')
            cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'")
            existing = {r[0] for r in cur.fetchall()}
            missing = [t for t in ORDER if t not in existing]
            if missing:
                raise RuntimeError('Unexpected schema, missing tables: ' + ', '.join(missing))
            counts = {}
            for table in ORDER:
                cur.execute(f'SELECT COUNT(*) FROM `{table}`')
                counts[table] = cur.fetchone()[0]
            shas = sha_set(cur)
            files = {sha: storage_path(sha) for sha in sorted(shas)}
            print('DRY RUN' if not args.execute else 'EXECUTE')
            print('rows:', {k: v for k, v in counts.items() if v})
            print('referenced originals:', len(files))
            for sha, path in files.items():
                state = 'missing'
                if path.is_file():
                    state = 'verified' if hashlib.sha256(path.read_bytes()).hexdigest() == sha else 'MISMATCH'
                print(' ', sha[:12], state, path.stat().st_size if path.exists() else '-')
            if not args.execute:
                print('No change. Re-run with --execute to apply.')
                return
            backup, backup_counts = snapshot(conn)
            conn.commit()
            print('backup:', backup.name, 'tables:', len(backup_counts), 'rows:', sum(backup_counts.values()))
            with conn.cursor() as cur:
                cur.execute('START TRANSACTION')
                cur.execute('UPDATE samples SET parent_sample_id=NULL')
                cur.execute('UPDATE source_files SET is_duplicate_of=NULL')
                for table in ORDER:
                    cur.execute(f'DELETE FROM `{table}`')
                cur.execute('SELECT COUNT(*) FROM users')
                if cur.fetchone()[0] != 0:
                    raise RuntimeError('User deletion incomplete')
                conn.commit()
            print('deleted rows:', sum(counts.values()))
            removed, kept = [], []
            for sha, path in files.items():
                if not path.is_file():
                    continue
                if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                    kept.append((sha, 'content mismatch'))
                    continue
                path.unlink()
                removed.append(sha)
            with conn.cursor() as cur:
                remaining = sha_set(cur)
            print('originals removed:', len(removed), 'kept:', kept, 'still referenced:', sorted(remaining))
            for directory in sorted(originals_root().glob('[0-9a-f][0-9a-f]')):
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                print('remaining users:', cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM schema_migrations")
                print('migrations kept:', cur.fetchone()[0])
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK('ale_workbench_migrations')")
        conn.close()


if __name__ == '__main__':
    main()
