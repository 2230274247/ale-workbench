"""Verified database + originals backup for ALE Workbench.

    python database/backup_db.py                      # production, manual
    python database/backup_db.py --reason pre_upgrade # labelled backup
    python database/backup_db.py --keep 30            # retention in days
    python database/backup_db.py --list               # list existing backups

Output layout (default H:\\ALE_Backups, outside the project):

    <stamp>_<db>_<reason>/
        database.sql.gz     consistent logical dump (InnoDB single transaction)
        manifest.json       time, db, software version, migration version, counts, SHA-256
        originals/          copy of storage/originals (content-addressed originals)
        originals.sha256    per-file digest list
        SHA256SUMS          digest of every file in the backup
        FAILED.json         only present when a step failed (partial backup)

The manifest is written last: its presence is the proof that the backup completed.
Exit code 0 only for a verified, complete backup.
"""
import argparse
import gzip
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p0_utils as U


def parse_args():
    parser = argparse.ArgumentParser(description='Verified ALE Workbench backup')
    parser.add_argument('--database', default=U.PRODUCTION_DATABASE,
                        help='production database or an explicit *_test database')
    parser.add_argument('--reason', default='manual', help='manual | pre_upgrade | pre_migration | daily')
    parser.add_argument('--backup-root', default=str(U.default_backup_root()))
    parser.add_argument('--keep', type=int, default=int(os.getenv('ALE_BACKUP_KEEP_DAYS', '30')),
                        help='retention in days (0 disables pruning)')
    parser.add_argument('--no-originals', action='store_true', help='skip the originals copy')
    parser.add_argument('--originals-root', default=str(U.originals_root()))
    parser.add_argument('--allow-inside-project', action='store_true',
                        help='permit a backup root inside the project (not recommended)')
    parser.add_argument('--list', action='store_true', help='list existing backups and exit')
    return parser.parse_args()


def backup_root(args):
    root = Path(args.backup_root)
    if U.is_inside(root, U.ROOT) and not args.allow_inside_project:
        raise SystemExit(f'Refusing: backup root {root} is inside the project. '
                         'Choose a location outside it, or pass --allow-inside-project.')
    return root


def list_backups(root):
    if not root.is_dir():
        print(f'No backups yet at {root}')
        return
    rows = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name.startswith('_'):
            continue
        manifest = directory / 'manifest.json'
        size = sum(f.stat().st_size for f in directory.rglob('*') if f.is_file())
        if not manifest.is_file():
            rows.append((directory.name, 'INCOMPLETE', '-', '-', f'{size / 1048576:.1f} MB'))
            continue
        data = U.read_json(manifest)
        database = data.get('database') or {}
        rows.append((directory.name, data.get('status', '?'), database.get('name', '-'),
                     str(database.get('row_total', '-')), f'{size / 1048576:.1f} MB'))
    if not rows:
        print(f'No backups yet at {root}')
        return
    print(f'{len(rows)} backup(s) in {root}')
    for name, status, database, rows_total, size in rows:
        print(f'  {name}  status={status} db={database} rows={rows_total} size={size}')


def copy_originals(source_root, destination_root, log_path):
    """Copy every original, verifying each copy against the source digest."""
    source_root = Path(source_root)
    entries = U.originals_inventory(source_root)
    copied = 0
    if entries:
        for entry in entries:
            source = source_root / entry['path']
            target = Path(destination_root) / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if U.sha256_file(target) != entry['sha256']:
                raise RuntimeError(f'originals copy verification failed for {entry["path"]}')
            copied += 1
    lines = [f'{e["sha256"]}  {e["path"]}' for e in entries]
    manifest_path = Path(destination_root).parent / 'originals.sha256'
    manifest_path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    return {'root': str(source_root), 'files': len(entries), 'copied': copied,
            'bytes': sum(e['bytes'] for e in entries),
            'manifest': manifest_path.name,
            'manifest_sha256': U.sha256_file(manifest_path)}


def verify_archive(path, log_path):
    """Full decompression: proves gzip CRC and that DDL/DML are present."""
    size = 0
    has_table = False
    has_insert = False
    with gzip.open(path, 'rb') as stream:
        while True:
            chunk = stream.read(U.CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if not has_table and b'CREATE TABLE' in chunk:
                has_table = True
            if not has_insert and (b'INSERT INTO' in chunk or b'/*!40000 ALTER TABLE' in chunk):
                has_insert = True
    if size == 0 or not has_table:
        raise RuntimeError('backup archive does not contain schema DDL')
    return {'uncompressed_bytes': size, 'has_ddl': has_table, 'has_rows': has_insert}


def write_sums(directory):
    directory = Path(directory)
    lines = []
    for path in sorted(directory.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS':
            lines.append(f'{U.sha256_file(path)}  {path.relative_to(directory).as_posix()}')
    (directory / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def prune(root, database, keep_days, current, log_path):
    if keep_days <= 0:
        return []
    cutoff = U.utc_now().timestamp() - keep_days * 86400
    removed = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory == current:
            continue
        manifest = directory / 'manifest.json'
        if not manifest.is_file():
            continue
        try:
            data = U.read_json(manifest)
        except Exception:
            continue
        if data.get('database', {}).get('name') != database:
            continue
        created = directory.stat().st_mtime
        if created < cutoff:
            shutil.rmtree(directory)
            removed.append(directory.name)
    if removed:
        U.log_line(log_path, f'BACKUP_PRUNED keep_days={keep_days} count={len(removed)} '
                             f'names={",".join(removed)}')
    return removed


def main():
    args = parse_args()
    root = backup_root(args)
    log_path = root / 'backup.log'
    if args.list:
        list_backups(root)
        return 0

    database = args.database
    if not re.fullmatch(r'[A-Za-z0-9_]+', database):
        raise SystemExit('Invalid database name')
    root.mkdir(parents=True, exist_ok=True)
    stamp = U.utc_stamp()
    reason = re.sub(r'[^A-Za-z0-9_-]', '-', args.reason)[:32] or 'manual'
    directory = root / f'{stamp}_{database}_{reason}'
    suffix = 1
    while directory.exists():
        suffix += 1
        directory = root / f'{stamp}_{database}_{reason}-{suffix}'
    directory.mkdir(parents=True)
    U.log_line(log_path, f'BACKUP_START target={directory.name} database={database} reason={reason}')

    stage = 'connect'
    try:
        conn = U.connect(database)
        try:
            server = U.server_info(conn)
            stats = U.object_stats(conn, database)
            counts = U.row_counts(conn, database, stats['tables'])
            migrations = U.migration_state(conn, database)
            data_bytes = U.data_bytes(conn, database)
        finally:
            conn.close()
        if not stats['tables']:
            raise RuntimeError(f'database {database} has no tables')

        stage = 'space'
        originals = U.originals_inventory(args.originals_root) if not args.no_originals else []
        required = data_bytes + sum(e['bytes'] for e in originals) + 200 * 1024 * 1024
        available = U.free_bytes(root)
        if available < required:
            raise RuntimeError(f'not enough free space on {root.parent}: '
                               f'{available // 1048576} MB available, about {required // 1048576} MB required')

        stage = 'dump'
        dump = U.dump_database(database, directory / 'database.sql.gz', log_path)
        stage = 'verify-archive'
        archive = verify_archive(dump, log_path)
        dump_sha = U.sha256_file(dump)

        stage = 'originals'
        if not args.no_originals:
            originals_report = copy_originals(args.originals_root, directory / 'originals', log_path)
            originals_report['skipped'] = False
        else:
            originals_report = {'skipped': True, 'files': 0, 'note': 'skipped by --no-originals'}

        stage = 'manifest'
        manifest = {
            'format': 'ale-workbench-backup/1',
            'status': 'complete',
            'backup_id': directory.name,
            'created_at_utc': U.utc_now().isoformat(),
            'created_at_local': U.utc_now().astimezone().isoformat(),
            'reason': reason,
            'software': {
                'app_version': U.app_version(),
                'git': U.git_state(),
                'script': 'database/backup_db.py',
            },
            'environment': {
                'name': os.getenv('ALE_ENVIRONMENT', 'production'),
                'label': os.getenv('ALE_ENVIRONMENT_LABEL', '生产环境'),
                'database': database,
                'host': server['hostname'],
                'port': server['port'],
                'is_production': database == U.PRODUCTION_DATABASE,
            },
            'database': {
                'name': database,
                'mysql_version': server['version'],
                'sql_mode': server['sql_mode'],
                'dump_file': dump.name,
                'dump_bytes': dump.stat().st_size,
                'dump_sha256': dump_sha,
                'archive': archive,
                'table_count': stats['table_count'],
                'view_count': stats['view_count'],
                'foreign_keys': stats['foreign_keys'],
                'tables': stats['tables'],
                'views': stats['views'],
                'row_counts': counts,
                'row_total': sum(counts.values()),
                'migration_version': migrations.get('target_version'),
                'migrations_applied': migrations.get('applied_versions', []),
                'migrations_pending': [m['filename'] for m in migrations.get('pending', [])],
            },
            'originals': originals_report,
            'retention': {'keep_days': args.keep},
            'restore': {
                'script': 'database/restore_db.py',
                'command': f'python database/restore_db.py --backup "{directory}" '
                           f'--target <name>_test --replace',
            },
        }
        U.write_json(directory / 'manifest.json', manifest)
        stage = 'sums'
        write_sums(directory)
        removed = prune(root, database, args.keep, directory, log_path)
        U.log_line(log_path, f'BACKUP_OK id={directory.name} rows={manifest["database"]["row_total"]} '
                             f'bytes={dump.stat().st_size} sha256={dump_sha} '
                             f'originals={originals_report.get("files", 0)} pruned={len(removed)}')
    except Exception as exc:
        failure = {'status': 'failed', 'stage': stage, 'backup_id': directory.name,
                   'created_at_utc': U.utc_now().isoformat(),
                   'error': f'{type(exc).__name__}: {exc}'}
        try:
            U.write_json(directory / 'FAILED.json', failure)
            U.log_line(log_path, f'BACKUP_FAILED stage={stage} id={directory.name} '
                                 f'error={type(exc).__name__}')
        finally:
            print(f'BACKUP FAILED at stage "{stage}": {exc}', file=sys.stderr)
            print(f'Partial output kept for diagnosis: {directory}', file=sys.stderr)
        return 2

    print(f'Backup complete: {directory}')
    print(f'  database      {database} (MySQL {server["version"]})')
    print(f'  rows          {manifest["database"]["row_total"]} across {stats["table_count"]} tables')
    print(f'  migration     {manifest["database"]["migration_version"]} '
          f'({len(manifest["database"]["migrations_applied"])} applied)')
    print(f'  dump          {manifest["database"]["dump_bytes"] / 1048576:.2f} MB  '
          f'sha256={dump_sha[:16]}...')
    print(f'  originals     {originals_report.get("files", 0)} file(s)'
          + (' (skipped)' if originals_report.get('skipped') else ''))
    if removed:
        print(f'  pruned        {len(removed)} backup(s) older than {args.keep} days')
    print(f'  log           {log_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
