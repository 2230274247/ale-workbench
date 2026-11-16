"""Safe restore: drill targets only, verified backup, verified result.

    python database/restore_db.py --backup "H:/ALE_Backups/<id>" --target ale_restore_drill_test --replace
    python database/restore_db.py --backup "<id>" --target ale_drill_test --verify-only

Hard rules implemented here:
* the target must end with `_test` and must differ from the production schema;
* production can never be named as a target, with any flag combination;
* the backup must be complete and its SHA-256 must match the manifest;
* the dump must not contain CREATE DATABASE / USE, so a mis-aimed import cannot
  write into the live schema;
* after the import the real rows are read back and compared with the manifest:
  table/view/foreign-key counts, exact per-table row counts, revision history,
  referential integrity and the originals digest list.
Exit 0 only when every check passes.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p0_utils as U

PROTECTED = {'mysql', 'sys', 'information_schema', 'performance_schema'}


def parse_args():
    parser = argparse.ArgumentParser(description='Restore an ALE backup into an independent test schema')
    parser.add_argument('--backup', required=True, help='backup directory containing manifest.json')
    parser.add_argument('--target', required=True, help='target database; must end with _test')
    parser.add_argument('--replace', action='store_true', help='drop the target schema first')
    parser.add_argument('--verify-only', action='store_true', help='check backup + target without importing')
    parser.add_argument('--originals-root', default=None,
                        help='where originals must exist after restore (default: manifest root)')
    parser.add_argument('--restore-originals-to', default=None,
                        help='copy originals here and verify each digest')
    parser.add_argument('--drop-target', action='store_true',
                        help='drop the drill schema after a successful verification')
    parser.add_argument('--report', default=None, help='report path (default: <backup root>/_reports)')
    return parser.parse_args()


def production_names():
    names = {U.PRODUCTION_DATABASE}
    try:
        text = (U.ROOT / 'database' / '.appcreds').read_text(encoding='utf-8-sig')
    except OSError:
        return names
    for line in text.splitlines():
        key, _, value = line.strip().partition('=')
        if key.strip() == 'database' and value.strip():
            names.add(value.strip())
    return names


def guard_target(target):
    if target in PROTECTED:
        raise SystemExit(f'Refusing: {target} is a system schema')
    if target in production_names() or target == U.PRODUCTION_DATABASE:
        raise SystemExit('Refusing: the production database can never be a restore target. '
                         'Restore into an independent *_test schema instead.')
    if not target.endswith(U.TEST_SUFFIX) or target == U.PRODUCTION_DATABASE:
        raise SystemExit('Refusing: the restore target must end with _test '
                         f'(got {target!r})')


def verify_backup(directory):
    """Integrity of the backup itself, before anything is written."""
    manifest_path = directory / 'manifest.json'
    failures = []
    if not manifest_path.is_file():
        raise SystemExit(f'Refusing: {directory} has no manifest.json (incomplete or failed backup)')
    manifest = U.read_json(manifest_path)
    if manifest.get('status') != 'complete':
        raise SystemExit('Refusing: manifest status is not "complete"')
    info = manifest['database']
    dump = directory / info['dump_file']
    if not dump.is_file():
        raise SystemExit(f'Refusing: dump file missing: {dump.name}')
    digest = U.sha256_file(dump)
    if digest != info['dump_sha256']:
        raise SystemExit(f'Refusing: dump SHA-256 mismatch (expected {info["dump_sha256"]}, got {digest})')
    sums_path = directory / 'SHA256SUMS'
    if sums_path.is_file():
        for line in sums_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            expected, _, rel = line.partition('  ')
            path = directory / rel
            if not path.is_file():
                failures.append(f'missing file from SHA256SUMS: {rel}')
            elif U.sha256_file(path) != expected:
                failures.append(f'SHA-256 mismatch: {rel}')
    unsafe = U.dump_safety_scan(dump)
    if unsafe:
        failures.append('dump contains schema switching statements: ' + ', '.join(unsafe))
    return manifest, failures


def verify_target(manifest, target, originals_root, restore_originals_to):
    """Read the restored data back; return (failures, details)."""
    expected = manifest['database']
    failures = []
    details = {}
    conn = U.connect(target)
    try:
        stats = U.object_stats(conn, target)
        details['tables'] = stats['table_count']
        details['views'] = stats['view_count']
        details['foreign_keys'] = stats['foreign_keys']
        if stats['table_count'] != expected['table_count']:
            failures.append(f'table count {stats["table_count"]} != backup {expected["table_count"]}')
        if stats['view_count'] != expected['view_count']:
            failures.append(f'view count {stats["view_count"]} != backup {expected["view_count"]}')
        if stats['foreign_keys'] != expected['foreign_keys']:
            failures.append(f'foreign key count {stats["foreign_keys"]} != backup {expected["foreign_keys"]}')
        missing = sorted(set(expected['tables']) - set(stats['tables']))
        if missing:
            failures.append('missing tables: ' + ', '.join(missing))

        counts = U.row_counts(conn, target, [t for t in expected['tables'] if t in stats['tables']])
        details['rows'] = counts
        details['row_total'] = sum(counts.values())
        mismatched = {name: (expected['row_counts'].get(name), actual)
                      for name, actual in counts.items()
                      if expected['row_counts'].get(name) != actual}
        if mismatched:
            sample = ', '.join(f'{k}: backup={v[0]} restored={v[1]}' for k, v in list(mismatched.items())[:6])
            failures.append(f'{len(mismatched)} table(s) with row count mismatch ({sample})')
        details['row_mismatches'] = mismatched

        orphans = U.orphan_report(conn, target)
        broken = [o for o in orphans if o.get('orphans')]
        errors = [o for o in orphans if o.get('error')]
        details['relations_checked'] = len(orphans)
        details['orphans'] = broken
        if broken:
            failures.append(f'{len(broken)} broken relation(s): ' + ', '.join(
                f'{o["relation"]}={o["orphans"]}' for o in broken[:5]))
        if errors:
            failures.append('relations that could not be checked: ' + ', '.join(
                f'{o["relation"]}({o["error"]})' for o in errors[:3]))

        state = U.migration_state(conn, target)
        details['migration_applied'] = state.get('applied_versions', [])
        if state.get('applied_versions', []) != expected.get('migrations_applied', []):
            failures.append('migration ledger differs from the backup manifest')
        elif state.get('applied_versions') and max(state['applied_versions']) != expected.get('migration_version'):
            failures.append('migration head differs from the backup manifest')

        # Revision history is the scientific audit trail: it must exist for every edited run.
        if 'quick_runs' in counts and 'quick_revisions' in counts:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM {U.quote(target)}.quick_revisions')
                revisions = int(cur.fetchone()[0])
                cur.execute(f'SELECT COUNT(DISTINCT process_id) FROM {U.quote(target)}.quick_revisions')
                distinct = int(cur.fetchone()[0])
                cur.execute(f'SELECT COUNT(*) FROM {U.quote(target)}.quick_runs')
                runs = int(cur.fetchone()[0])
            details['revisions'] = {'rows': revisions, 'runs_with_history': distinct, 'runs': runs}
            if expected['row_counts'].get('quick_revisions') != revisions:
                failures.append('revision history row count mismatch')
    finally:
        conn.close()

    originals = manifest.get('originals') or {}
    if originals.get('skipped'):
        details['originals'] = {'status': 'not in backup'}
    else:
        expected_files = originals.get('files', 0)
        if restore_originals_to:
            source = Path(manifest['_directory']) / 'originals'
            copied, bad = copy_and_verify(source, Path(restore_originals_to))
            details['originals'] = {'copied': copied, 'verified_to': str(restore_originals_to)}
            if bad:
                failures.append(f'{len(bad)} original file(s) failed digest verification')
            if copied != expected_files:
                failures.append(f'originals copied {copied} != backup {expected_files}')
        else:
            root = Path(originals_root or originals.get('root') or U.originals_root())
            present, missing, bad = check_originals(root, manifest['_directory'])
            details['originals'] = {'root': str(root), 'present': present,
                                    'missing': missing[:10], 'missing_count': len(missing),
                                    'corrupt': bad}
            if missing:
                failures.append(f'{len(missing)} original file(s) recorded in the backup are absent')
            if bad:
                failures.append(f'{len(bad)} original file(s) have a different SHA-256')
    return failures, details


def copy_and_verify(source, destination):
    copied = 0
    bad = []
    if not source.is_dir():
        return 0, bad
    for path in sorted(source.rglob('*')):
        if not path.is_file():
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if U.sha256_file(target) != U.sha256_file(path):
            bad.append(str(target))
        copied += 1
    return copied, bad


def check_originals(root, backup_directory):
    """Compare the backup's originals digest list with what exists on disk."""
    listing = Path(backup_directory) / 'originals.sha256'
    present = 0
    missing = []
    bad = []
    if not listing.is_file():
        return 0, missing, bad
    for line in listing.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition('  ')
        path = Path(root) / rel
        if not path.is_file():
            missing.append(rel)
            continue
        if U.sha256_file(path) != digest:
            bad.append(rel)
            continue
        present += 1
    return present, missing, bad


def main():
    args = parse_args()
    guard_target(args.target)
    directory = Path(args.backup).resolve()
    if not directory.is_dir():
        raise SystemExit(f'Backup directory not found: {directory}')
    log_path = directory.parent / 'backup.log'

    manifest, integrity = verify_backup(directory)
    manifest['_directory'] = str(directory)
    print(f'Backup     {manifest["backup_id"]}  ({manifest["created_at_local"]})')
    print(f'  database {manifest["database"]["name"]}  rows={manifest["database"]["row_total"]}  '
          f'migration={manifest["database"]["migration_version"]}  '
          f'app={manifest["software"]["app_version"]}')
    print(f'  sha256   {manifest["database"]["dump_sha256"]}')
    if integrity:
        for item in integrity:
            print(f'  INTEGRITY  {item}', file=sys.stderr)
        raise SystemExit('Refusing: backup integrity check failed')
    print('  integrity verified (SHA-256, archives, digest list)')

    conn = U.connect()
    try:
        exists = U.database_exists(conn, args.target)
        if args.verify_only:
            if not exists:
                raise SystemExit(f'Target {args.target} does not exist; nothing to verify')
        else:
            if exists and not args.replace:
                raise SystemExit(f'Target {args.target} already exists. Pass --replace to drop and recreate it.')
            if exists:
                with conn.cursor() as cur:
                    cur.execute('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s',
                                (args.target,))
                    if cur.fetchone()[0] and not args.replace:
                        raise SystemExit('Target is not empty; --replace is required')
            U.create_database(conn, args.target, drop=exists)
            U.grant_app_read(conn, args.target)
    finally:
        conn.close()

    if not args.verify_only:
        print(f'Restoring into {args.target} ...')
        U.import_database(args.target, directory / manifest['database']['dump_file'], log_path)

    failures, details = verify_target(manifest, args.target, args.originals_root,
                                      args.restore_originals_to)
    report = {
        'restored_at_utc': U.utc_now().isoformat(),
        'backup_id': manifest['backup_id'],
        'backup_created_at': manifest['created_at_local'],
        'target': args.target,
        'verify_only': args.verify_only,
        'manifest_database': manifest['database']['name'],
        'result': 'passed' if not failures else 'failed',
        'failures': failures,
        'details': details,
        'software': manifest['software'],
    }
    report_dir = Path(args.report).parent if args.report else directory.parent / '_reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report) if args.report else report_dir / f'restore_{U.utc_stamp()}_{args.target}.json'
    U.write_json(report_path, report)

    print(f'Verified   tables={details["tables"]} views={details["views"]} '
          f'fk={details["foreign_keys"]} rows={details["row_total"]}')
    if 'revisions' in details:
        print(f'  revisions {details["revisions"]["rows"]} rows across '
              f'{details["revisions"]["runs_with_history"]} run(s)')
    if details.get('originals'):
        print(f'  originals {details["originals"]}')
    if failures:
        for item in failures:
            print(f'  FAILED  {item}', file=sys.stderr)
        U.log_line(log_path, f'RESTORE_VERIFY_FAILED target={args.target} '
                             f'backup={manifest["backup_id"]} failures={len(failures)}')
        print(f'Report     {report_path}', file=sys.stderr)
        return 3

    U.log_line(log_path, f'RESTORE_OK target={args.target} backup={manifest["backup_id"]} '
                         f'rows={details["row_total"]}')
    print('Restore verification PASSED')
    print(f'Report     {report_path}')
    if args.drop_target:
        conn = U.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS {U.quote(args.target)}')
        finally:
            conn.close()
        print(f'Dropped drill schema {args.target}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
