"""Create an independent test database and originals directory.

Copies schema objects and the migration ledger only; never copies business rows,
scientific measurements or original files. Refuses to target the production DB.

Usage (from H:\\ALE_AI):
    python database/setup_test_env.py
    ALE_TEST_DB_NAME=ale_workbench_test ALE_TEST_ORIGINALS_ROOT=storage-test/originals ...
"""
import argparse
import os
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'database'))
from apply_schema import load_admin_creds  # noqa: E402

PRODUCTION = 'ale_workbench'
LEDGER_TABLES = ('schema_migrations', 'schema_migration_attempts')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', default=os.getenv('ALE_TEST_DB_NAME', 'ale_workbench_test'))
    parser.add_argument('--originals', default=os.getenv('ALE_TEST_ORIGINALS_ROOT', str(ROOT / 'storage-test' / 'originals')))
    parser.add_argument('--replace', action='store_true', help='drop and recreate the target database')
    args = parser.parse_args()
    target = args.target
    if target == PRODUCTION or not target.endswith('_test'):
        raise SystemExit('Refusing: test database name must end with _test and differ from production')
    user, password = load_admin_creds()
    host = os.getenv('ALE_DB_HOST', '127.0.0.1' if os.name == 'nt' else '172.16.10.254')
    port = int(os.getenv('ALE_DB_PORT', '3307'))
    conn = pymysql.connect(host=host, port=port, user=user, password=password, charset='utf8mb4', autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (target,))
            exists = cur.fetchone()
            if exists and args.replace:
                cur.execute(f'DROP DATABASE `{target}`')
                exists = None
            if not exists:
                cur.execute(f'CREATE DATABASE `{target}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
            # The application account needs DML on the independent database.
            for host_name in ('127.0.0.1', 'localhost'):
                cur.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON `{target}`.* TO 'ale_app'@'{host_name}'")
            cur.execute('FLUSH PRIVILEGES')
            cur.execute(f'USE `{target}`')
            cur.execute("SELECT TABLE_NAME,TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_TYPE,TABLE_NAME", (PRODUCTION,))
            objects = cur.fetchall()
            cur.execute('SET FOREIGN_KEY_CHECKS=0')
            created = {'BASE TABLE': 0, 'VIEW': 0}
            for name, kind in objects:
                cur.execute(f'SHOW CREATE TABLE `{PRODUCTION}`.`{name}`')
                ddl = cur.fetchone()[1]
                cur.execute(f'DROP { "VIEW" if kind != "BASE TABLE" else "TABLE" } IF EXISTS `{name}`')
                cur.execute(ddl.replace(f'`{PRODUCTION}`.', ''))
                created['BASE TABLE' if kind == 'BASE TABLE' else 'VIEW'] += 1
            cur.execute('SET FOREIGN_KEY_CHECKS=1')
            for table in LEDGER_TABLES:
                cur.execute(f'SELECT COUNT(*) FROM `{PRODUCTION}`.`{table}`')
                if cur.fetchone()[0] == 0:
                    continue
                cur.execute(f'SHOW COLUMNS FROM `{PRODUCTION}`.`{table}`')
                columns = [row[0] for row in cur.fetchall()]
                cur.execute(f'SELECT * FROM `{PRODUCTION}`.`{table}`')
                rows = cur.fetchall()
                placeholders = ','.join(['%s'] * len(columns))
                cur.executemany(f'INSERT INTO `{table}` (`' + '`,`'.join(columns) + f'`) VALUES ({placeholders})', rows)
            cur.execute('SELECT COUNT(*) FROM users')
            users = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM schema_migrations')
            migrations = cur.fetchone()[0]
        originals = Path(args.originals)
        originals.mkdir(parents=True, exist_ok=True)
        print(f'target={target} tables={created["BASE TABLE"]} views={created["VIEW"]} '
              f'users={users} migrations={migrations} originals={originals}')
        print('No business rows or original files were copied.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
