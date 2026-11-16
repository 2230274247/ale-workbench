"""Pre-upgrade gate: check, back up, rehearse on a copy, then stop for a human.

    python database/pre_upgrade_check.py                 # checks + pre-upgrade backup + report
    python database/pre_upgrade_check.py --rehearse      # additionally migrate a *_test copy
    python database/pre_upgrade_check.py --status        # read-only, no backup

Nothing in this script applies DDL to the production database. A production
upgrade happens only when a person runs:
    python database/migrate.py --confirm-production
after reading the generated report.

Rollback boundary: reverting the code alone is NOT a safe rollback once DDL ran.
The report records the backup id, the migration head and the git commit so the
matching data+code pair can be restored together.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p0_utils as U

PYTHON = sys.executable
REPORT_DIR = U.ROOT / 'reports' / 'p0'


def parse_args():
    parser = argparse.ArgumentParser(description='ALE Workbench pre-upgrade gate')
    parser.add_argument('--database', default=U.PRODUCTION_DATABASE)
    parser.add_argument('--status', action='store_true', help='read-only checks, no backup, no rehearsal')
    parser.add_argument('--skip-backup', action='store_true')
    parser.add_argument('--rehearse', action='store_true', help='migrate a throw-away copy of this database')
    parser.add_argument('--keep-rehearsal', action='store_true', help='keep the rehearsal schema for inspection')
    parser.add_argument('--report', default=None)
    return parser.parse_args()


def run(command, env_extra=None, timeout=1800, cwd=None):
    env = os.environ.copy()
    env.update(env_extra or {})
    completed = subprocess.run(command, cwd=cwd or U.ROOT, env=env, capture_output=True,
                               text=True, timeout=timeout, check=False)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def code_reflection(database):
    """Does the current code accept the current schema (read-only reflection)?"""
    probe = ('import sys\n'
             'from app.db import metadata\n'
             'try:\n'
             '    m = metadata()\n'
             '    print(len(m.tables))\n'
             'except Exception as exc:\n'
             '    print(type(exc).__name__)\n'
             '    sys.exit(1)\n')
    env = {'ALE_DB_NAME': database}
    env['ALE_ENVIRONMENT'] = 'testing' if database.endswith(U.TEST_SUFFIX) else 'production'
    code, out, err = run([PYTHON, '-c', probe], env, cwd=U.ROOT / 'backend')
    return {'ok': code == 0, 'tables': out if code == 0 else None,
            'error': None if code == 0 else (err.splitlines()[-1] if err else out)}


def rehearsal(database, information):
    """Restore the fresh backup into a scratch schema and migrate the copy."""
    stamp = U.utc_stamp()
    scratch = f'{database[:40]}_up{stamp}_test'.lower()
    log_path = Path(information['backup_root']) / 'backup.log'
    steps = []
    conn = U.connect()
    try:
        U.create_database(conn, scratch, drop=True)
        U.grant_app_read(conn, scratch)
        steps.append(('create', True, scratch))
    finally:
        conn.close()
    U.import_database(scratch, Path(information['backup_dir']) / 'database.sql.gz', log_path)
    steps.append(('restore-copy', True, scratch))

    code, out, err = run([PYTHON, str(U.ROOT / 'database' / 'migrate.py'), '--database', scratch], timeout=3600)
    steps.append(('migrate-copy', code == 0, (err or out).splitlines()[-1] if (err or out) else ''))

    conn = U.connect(scratch)
    try:
        after_stats = U.object_stats(conn, scratch)
        after_counts = U.row_counts(conn, scratch, after_stats['tables'])
    finally:
        conn.close()
    before = information['row_counts']
    preserved = {name: (before.get(name), after_counts.get(name))
                 for name in before if after_counts.get(name) != before.get(name)}
    steps.append(('row-preservation', not preserved,
                  ', '.join(f'{k}: {v[0]}->{v[1]}' for k, v in list(preserved.items())[:5])))

    reflection = code_reflection(scratch)
    steps.append(('code-vs-new-schema', reflection['ok'], reflection.get('error') or 'ok'))

    return {'scratch': scratch, 'steps': steps, 'preserved': not preserved,
            'table_count_before': information['table_count'],
            'table_count_after': after_stats['table_count'],
            'reflection': reflection}


def main():
    args = parse_args()
    database = args.database
    report = {'generated_at_utc': U.utc_now().isoformat(),
              'database': database,
              'is_production': database == U.PRODUCTION_DATABASE,
              'checks': [],
              'verdict': 'NOT_READY'}

    def check(name, ok, detail):
        report['checks'].append({'check': name, 'ok': bool(ok), 'detail': detail})
        print(f'  [{"OK" if ok else "FAIL"}] {name}: {detail}')
        return ok

    print(f'Pre-upgrade check for {database}')
    report['software'] = {'app_version': U.app_version(), 'git': U.git_state()}
    print(f'  app_version {report["software"]["app_version"]}  '
          f'git {report["software"]["git"].get("commit") or "unknown"}'
          f'{" (dirty)" if report["software"]["git"].get("dirty") else ""}')

    conn = U.connect(database)
    try:
        server = U.server_info(conn)
        stats = U.object_stats(conn, database)
        counts = U.row_counts(conn, database, stats['tables'])
        migrations = U.migration_state(conn, database)
    finally:
        conn.close()
    report['server'] = server
    report['migration'] = migrations
    report['table_count'] = stats['table_count']
    report['row_counts'] = counts
    report['row_total'] = sum(counts.values())

    check('database-reachable', True, f'{server["hostname"]}:{server["port"]} MySQL {server["version"]}')
    check('tables-present', stats['table_count'] > 0,
          f'{stats["table_count"]} tables, {stats["view_count"]} views, {stats["foreign_keys"]} foreign keys')
    check('migration-checksums', not migrations['checksum_drift'],
          'ledger matches shipped files' if not migrations['checksum_drift']
          else f'{len(migrations["checksum_drift"])} applied migration(s) changed on disk')
    check('migration-ledger-known', not migrations['unknown_in_db'],
          'no unknown versions' if not migrations['unknown_in_db']
          else str([m['version'] for m in migrations['unknown_in_db']]))
    pending = migrations['pending']
    check('pending-migrations', True,
          'none (database already at code version)' if not pending
          else f'{len(pending)} pending: ' + ', '.join(p['filename'] for p in pending))
    reflection = code_reflection(database)
    check('code-accepts-current-schema', reflection['ok'],
          f'reflected {reflection["tables"]} tables' if reflection['ok'] else str(reflection['error']))
    report['reflection'] = reflection

    information = {'table_count': stats['table_count'], 'row_counts': counts}
    backup_ok = True
    if args.status or args.skip_backup:
        check('pre-upgrade-backup', True, 'skipped by flag (NOT acceptable for a real upgrade)')
        report['backup'] = None
        report['verdict'] = 'CHECKS_ONLY'
    else:
        root = U.default_backup_root()
        code, out, err = run([PYTHON, str(U.ROOT / 'database' / 'backup_db.py'),
                              '--database', database, '--reason', 'pre_upgrade'])
        backup_ok = code == 0
        backup_dir = None
        if backup_ok and out:
            for line in out.splitlines():
                if line.startswith('Backup complete: '):
                    backup_dir = line.split(': ', 1)[1].strip()
        check('pre-upgrade-backup', backup_ok,
              backup_dir if backup_ok else (err.splitlines()[-1] if err else 'backup failed'))
        report['backup'] = {'directory': backup_dir, 'root': str(root), 'ok': backup_ok,
                            'stdout_tail': out.splitlines()[-4:] if out else []}
        information.update(backup_dir=backup_dir, backup_root=str(root))

    if args.rehearse and backup_ok and not args.status:
        print('  rehearsing migration on a copy ...')
        try:
            result = rehearsal(database, information)
            for name, ok, detail in result['steps']:
                check('rehearsal-' + name, ok, detail)
            report['rehearsal'] = result
        except Exception as exc:
            check('rehearsal', False, f'{type(exc).__name__}: {exc}')
            report['rehearsal'] = {'error': str(exc)}
        else:
            scratch = result['scratch']
            if args.keep_rehearsal:
                print(f'  rehearsal schema kept: {scratch}')
            else:
                conn = U.connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute(f'DROP DATABASE IF EXISTS {U.quote(scratch)}')
                finally:
                    conn.close()
    elif args.rehearse:
        check('rehearsal', False, 'not attempted: a verified backup is required first')

    failures = [c for c in report['checks'] if not c['ok']]
    if not failures and report['migration']['pending'] and report.get('rehearsal'):
        report['verdict'] = 'READY_FOR_MANUAL_APPROVAL'
    elif not failures and not report['migration']['pending']:
        report['verdict'] = 'ALREADY_UP_TO_DATE'
    elif report['verdict'] != 'CHECKS_ONLY':
        report['verdict'] = 'NOT_READY'

    report['manual_steps'] = [
        '1. Read this report and the restore drill result.',
        '2. Stop the workbench (do not stop MySQL).',
        f'3. python database/migrate.py --database {database} --confirm-production',
        '4. Start the workbench; the launcher refuses to start if the schema is incomplete.',
        '5. Record the backup id and migration head in progress_log.md.',
        'Rollback: restore the recorded backup into production is NOT automated. '
        'Use database/restore_db.py against a *_test copy to confirm the backup first, '
        'then ask the maintainer before touching production; reverting code alone is unsafe.',
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = U.utc_stamp()
    report_path = Path(args.report) if args.report else REPORT_DIR / f'pre_upgrade_{stamp}.json'
    U.write_json(report_path, report)
    markdown = report_path.with_suffix('.md')
    markdown.write_text(render(report), encoding='utf-8')
    print(f'Verdict: {report["verdict"]}')
    print(f'Report: {report_path}')
    print(f'Human-readable: {markdown}')
    return 0 if report['verdict'] in ('READY_FOR_MANUAL_APPROVAL', 'ALREADY_UP_TO_DATE', 'CHECKS_ONLY') else 4


def render(report):
    lines = [f'# 升级前检查 · {report["database"]}', '',
             f'- 生成时间：{report["generated_at_utc"]}',
             f'- 软件版本：{report["software"]["app_version"]}',
             f'- 代码版本：{report["software"]["git"].get("commit") or "unknown"}'
             f'{"（有未提交改动）" if report["software"]["git"].get("dirty") else ""}',
             f'- 数据库：{report["database"]}（{report["table_count"]} 表，'
             f'{report["row_total"]} 行，迁移头 {report["migration"].get("target_version")}）',
             f'- 结论：**{report["verdict"]}**', '', '## 检查项', '',
             '| 检查 | 结果 | 说明 |', '|---|---|---|']
    for item in report['checks']:
        lines.append(f'| {item["check"]} | {"通过" if item["ok"] else "未通过"} | {item["detail"]} |')
    backup = report.get('backup')
    if backup:
        lines += ['', '## 升级前备份', '', f'- 目录：`{backup.get("directory")}`',
                  f'- 结果：{"完成" if backup.get("ok") else "失败"}']
    rehearsal = report.get('rehearsal')
    if rehearsal and 'steps' in rehearsal:
        lines += ['', '## 副本演练', '', f'- 演练库：`{rehearsal["scratch"]}`（已按需清理）',
                  f'- 表数：{rehearsal["table_count_before"]} → {rehearsal["table_count_after"]}']
    lines += ['', '## 人工执行步骤', ''] + [f'{step}' for step in report['manual_steps']]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    sys.exit(main())
