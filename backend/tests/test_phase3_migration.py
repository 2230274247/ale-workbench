"""Phase 3 metadata regressions; real DDL tests require explicit opt-in.

ALE_PHASE3_MIGRATION_DB_TESTS=1 enables disposable-schema MySQL tests only.
The normal suite never applies 0005 to ale_workbench or writes to MySQL.
"""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import sys
import uuid

import pymysql
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ale_phase3_migrate_tests', ROOT / 'database/migrate.py')
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)
SQL = ROOT / 'database/migrations/0005_import_management.sql'


class Catalog:
    """Server-shaped metadata, parsed independently from the migration SQL."""
    schema = 'phase3_catalog_test'

    def __init__(self):
        self.columns = {}
        self.indexes = {}
        self.fks = {}
        self.checks = {}
        self.tables = {}
        for statement in statements():
            create = re.match(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*)\) ENGINE=', statement, re.S)
            alter = re.match(r'ALTER TABLE (\w+) ADD (COLUMN|CONSTRAINT) (.*)', statement, re.S)
            if create:
                table, body = create.groups()
                lines = [line.strip().rstrip(',') for line in body.strip().splitlines()]
            else:
                assert alter, statement
                table, kind, definition = alter.groups()
                lines = [definition if kind == 'COLUMN' else 'CONSTRAINT ' + definition]
            self.tables[table] = ('BASE TABLE', 'InnoDB', 'utf8mb4_0900_ai_ci')
            self.columns.setdefault(table, {})
            self.indexes.setdefault(table, {})
            self.fks.setdefault(table, {})
            self.checks.setdefault(table, {})
            for line in lines:
                fk = re.match(r'CONSTRAINT (\w+) FOREIGN KEY\((\w+)\) REFERENCES (\w+)\((\w+)\) ON DELETE (RESTRICT) ON UPDATE (NO ACTION)', line)
                check = re.match(r'CONSTRAINT (\w+) CHECK\((.*)\)', line)
                index = re.match(r'(?:(PRIMARY) KEY|UNIQUE KEY (\w+)|KEY (\w+)|CONSTRAINT (\w+) UNIQUE)\(([^)]+)\)', line)
                if fk:
                    name, column, target, target_column, delete, update = fk.groups()
                    self.fks[table][name] = [(column, self.schema, target, target_column, delete, update, 1)]
                    # MySQL creates a support index if the leftmost columns are absent.
                    if not any(rows[0][2] == column for rows in self.indexes[table].values()):
                        self.add_index(table, name, 1, [column])
                elif check:
                    name, clause = check.groups()
                    self.checks[table][name] = (clause, 'YES')
                elif index:
                    primary, unique, ordinary, constraint, columns = index.groups()
                    name = 'PRIMARY' if primary else unique or ordinary or constraint
                    cols = columns.split(',')
                    self.add_index(table, name, int(bool(ordinary)), cols)
                    # MySQL drops a redundant auto-created FK index once a covering index is added.
                    for fkname, rows in self.fks[table].items():
                        if fkname != name and fkname in self.indexes[table] and cols[0] == rows[0][0]:
                            del self.indexes[table][fkname]
                else:
                    col = re.match(r'(\w+) (BIGINT UNSIGNED|INT UNSIGNED|VARCHAR\(\d+\)|CHAR\(\d+\)|DATETIME|JSON|TEXT) (.*)', line)
                    assert col, line
                    name, typ, suffix = col.groups()
                    nullable = 'NO' if 'NOT NULL' in suffix else 'YES'
                    default = re.search(r"DEFAULT ('[^']*'|\w+)", suffix)
                    default = default.group(1).strip("'") if default else None
                    extra = 'auto_increment' if 'AUTO_INCREMENT' in suffix else 'default_generated' if default == 'CURRENT_TIMESTAMP' else ''
                    collation = 'utf8mb4_0900_ai_ci' if typ.startswith(('CHAR', 'VARCHAR', 'TEXT')) else None
                    self.columns[table][name] = (typ.lower(), nullable, default, extra, '', collation)
                    if 'PRIMARY KEY' in suffix:
                        self.add_index(table, 'PRIMARY', 0, [name])
        self.rows = ()

    def add_index(self, table, name, non_unique, columns):
        self.indexes[table][name] = [(non_unique, i, c, None, 'YES', 'BTREE', None) for i, c in enumerate(columns, 1)]

    def execute(self, sql, args=()):
        if sql == 'SELECT DATABASE()':
            self.rows = ((self.schema,),)
        elif 'information_schema.TABLES' in sql:
            self.rows = (self.tables[args[0]],) if args[0] in self.tables else ()
        elif 'information_schema.COLUMNS' in sql:
            self.rows = tuple((name, *row) for name, row in self.columns.get(args[0], {}).items())
        elif 'information_schema.STATISTICS' in sql:
            self.rows = tuple((name, *row) for name, rows in self.indexes.get(args[0], {}).items() for row in rows)
        elif 'information_schema.KEY_COLUMN_USAGE' in sql:
            self.rows = tuple((name, *row) for name, rows in self.fks.get(args[0], {}).items() for row in rows)
        elif 'information_schema.CHECK_CONSTRAINTS' in sql:
            self.rows = tuple((name, *row) for name, row in self.checks.get(args[0], {}).items())
        else:
            raise AssertionError('Validation must be read-only: ' + sql)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def statements():
    return [re.sub(r'^\s*(?:--[^\n]*(?:\n|$)\s*)+', '', s)
            for s in migrate.split_statements(SQL.read_text(encoding='utf-8'))]


def test_sql_matches_strict_contract_without_database_writes():
    migrate.validate_phase3(Catalog(), '0005')


@pytest.mark.parametrize('part,value', [(0, 'bigint'), (1, 'YES'), (2, '2'), (3, 'invisible'), (4, '1'), (5, 'utf8mb4_bin')])
def test_column_drift_rejected(part, value):
    catalog = Catalog()
    row = list(catalog.columns['import_jobs']['row_version'])
    row[part] = value
    catalog.columns['import_jobs']['row_version'] = tuple(row)
    with pytest.raises(RuntimeError, match='import_jobs.row_version'):
        migrate.validate_phase3(catalog, '0005')


@pytest.mark.parametrize('mutation,expected', [
    ('missing_column', 'missing column'), ('extra_column', 'column set'),
    ('table_engine', 'InnoDB'), ('table_collation', 'utf8mb4_0900_ai_ci'),
    ('nonunique', 'uk_msr_import_locator'), ('reordered', 'uk_msr_import_locator'),
    ('prefix', 'uk_msr_import_locator'), ('invisible', 'uk_msr_import_locator'),
    ('expression', 'uk_msr_import_locator'), ('index_kind', 'uk_msr_import_locator'),
    ('extra_index', 'index set'), ('extra_measurement_index', 'index set'), ('missing_index', 'index set'),
    ('fk_target', 'foreign keys'), ('fk_delete', 'foreign keys'),
    ('fk_update', 'foreign keys'), ('fk_schema', 'foreign keys'),
    ('extra_fk', 'foreign keys'), ('missing_fk', 'foreign keys'),
    ('check_disabled', 'CHECK'), ('check_weakened', 'CHECK'), ('extra_check', 'CHECK set'),
    ('string_case', 'CHECK'), ('missing_table', 'InnoDB'),
])
def test_drift_is_rejected(mutation, expected):
    c = Catalog()
    if mutation == 'missing_column':
        del c.columns['measurements']['provenance']
    elif mutation == 'extra_column':
        c.columns['import_items']['unexpected'] = c.columns['import_items']['filename']
    elif mutation.startswith('table_'):
        c.tables['import_items'] = ('BASE TABLE', 'MyISAM', 'utf8mb4_0900_ai_ci') if mutation == 'table_engine' else ('BASE TABLE', 'InnoDB', 'utf8mb4_bin')
    elif mutation in ('nonunique', 'reordered', 'prefix', 'invisible', 'expression', 'index_kind'):
        rows = c.indexes['measurements']['uk_msr_import_locator']
        if mutation == 'reordered':
            rows[0], rows[1] = (0, 1, 'import_locator', None, 'YES', 'BTREE', None), (0, 2, 'import_item_id', None, 'YES', 'BTREE', None)
        else:
            row = list(rows[0])
            pos, value = {'nonunique': (0, 1), 'prefix': (3, 8), 'invisible': (4, 'NO'), 'expression': (6, 'lower(import_locator)'), 'index_kind': (5, 'HASH')}[mutation]
            row[pos] = value
            rows[0] = tuple(row)
    elif mutation == 'extra_index':
        c.add_index('import_jobs', 'unexpected', 0, ['status'])
    elif mutation == 'extra_measurement_index':
        c.add_index('measurements', 'unexpected_unique', 0, ['import_locator'])
    elif mutation == 'missing_index':
        del c.indexes['import_confirmations']['PRIMARY']
    elif mutation.startswith('fk_'):
        row = list(c.fks['import_items']['fk_import_items_job'][0])
        pos, value = {'fk_target': (2, 'users'), 'fk_delete': (4, 'CASCADE'), 'fk_update': (5, 'CASCADE'), 'fk_schema': (1, 'other_db')}[mutation]
        row[pos] = value
        c.fks['import_items']['fk_import_items_job'] = [tuple(row)]
    elif mutation == 'extra_fk':
        c.fks['import_jobs']['unexpected'] = copy.deepcopy(c.fks['import_jobs']['fk_import_jobs_owner'])
    elif mutation == 'missing_fk':
        del c.fks['import_jobs']['fk_import_jobs_owner']
    elif mutation == 'check_disabled':
        clause, _ = c.checks['import_jobs']['chk_import_jobs_status']
        c.checks['import_jobs']['chk_import_jobs_status'] = (clause, 'NO')
    elif mutation == 'check_weakened':
        c.checks['import_jobs']['chk_import_jobs_status'] = ("status IN ('draft','completed') OR 1=1", 'YES')
    elif mutation == 'extra_check':
        c.checks['import_jobs']['unexpected'] = ('row_version >= 1', 'YES')
    elif mutation == 'string_case':
        c.checks['import_jobs']['chk_import_jobs_status'] = ("status IN ('DRAFT','completed')", 'YES')
    elif mutation == 'missing_table':
        del c.tables['import_items']
    with pytest.raises(RuntimeError, match=expected):
        migrate.validate_phase3(c, '0005')


def test_other_versions_do_not_query_phase3():
    class NoQueries:
        def execute(self, *args):
            raise AssertionError('Unexpected phase3 query')
    for version in ('0001', '0002', '0003', '0004'):
        migrate.validate_phase3(NoQueries(), version)


def test_status_checks_checksum_then_phase3(monkeypatch):
    class StatusCatalog(Catalog):
        digest = hashlib.sha256(SQL.read_bytes()).hexdigest()
        def execute(self, sql, args=()):
            if "TABLE_NAME='schema_migrations'" in sql:
                self.rows = ((1,),)
            elif sql.startswith('SELECT version,filename,sha256,applied_at'):
                self.rows = (('0005', SQL.name, self.digest, None),)
            else:
                super().execute(sql, args)
    monkeypatch.setattr(migrate, 'migration_files', lambda: [SQL])
    c = StatusCatalog()
    migrate.show_status(c)
    del c.columns['measurements']['row_version']
    with pytest.raises(RuntimeError, match='measurements.row_version'):
        migrate.show_status(c)
    c.digest = '0' * 64
    with pytest.raises(RuntimeError, match='checksum changed'):
        migrate.show_status(c)


class LedgerCatalog(Catalog):
    """Exercise the real runner and checksum/ledger flow without any DB writes."""
    def __init__(self):
        super().__init__()
        self.applied = None
        self.attempt = None

    def execute(self, sql, args=()):
        if sql.startswith('CREATE TABLE IF NOT EXISTS schema_migration'):
            self.rows = ()
        elif sql.startswith("SELECT GET_LOCK") or sql.startswith("SELECT RELEASE_LOCK"):
            self.rows = ((1,),)
        elif sql.startswith('SET TRANSACTION') or sql.startswith('START TRANSACTION'):
            self.rows = ()
        elif sql == 'SELECT sha256 FROM schema_migrations WHERE version=%s':
            self.rows = ((self.applied,),) if self.applied else ()
        elif sql == 'SELECT sha256 FROM schema_migration_attempts WHERE version=%s':
            self.rows = ((self.attempt,),) if self.attempt else ()
        elif sql.startswith('INSERT INTO schema_migration_attempts'):
            self.attempt = args[1]
        elif sql.startswith('INSERT INTO schema_migrations'):
            self.applied = args[2]
        elif sql.startswith('SELECT CHECK_CLAUSE'):
            self.rows = (("entity_type IN ('derived_result','instrument_dataset')",),)
        else:
            super().execute(sql, args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class CatalogConnection:
    def __init__(self, catalog):
        self.catalog = catalog

    def cursor(self):
        return self.catalog

    def commit(self):
        pass

    def close(self):
        pass


def configure_catalog_runner(monkeypatch, catalog):
    monkeypatch.setattr(migrate, 'load_admin_creds', lambda: ('test', 'test'))
    monkeypatch.setattr(migrate.pymysql, 'connect', lambda **kwargs: CatalogConnection(catalog))
    monkeypatch.setattr(migrate, 'migration_files', lambda: [SQL])
    monkeypatch.setattr(migrate, 'snapshot', lambda conn: (Path('test_snapshot'), {}))
    monkeypatch.setattr(migrate, 'report_legacy_in_process', lambda cur: 0)
    # Simulate every additive DDL already present after an interrupted attempt.
    monkeypatch.setattr(migrate, 'execute_resumable', lambda cur, statement: None)
    monkeypatch.setattr(sys, 'argv', ['migrate.py'])


def test_main_validation_precedes_ledger_and_recovers(monkeypatch):
    c = LedgerCatalog()
    configure_catalog_runner(monkeypatch, c)
    good = c.columns['measurements']['row_version']
    c.columns['measurements']['row_version'] = ('int unsigned', 'NO', '99', '', '', None)
    with pytest.raises(RuntimeError, match='measurements.row_version'):
        migrate.main()
    assert c.applied is None
    assert c.attempt == hashlib.sha256(SQL.read_bytes()).hexdigest()
    c.columns['measurements']['row_version'] = good
    migrate.main()
    assert c.applied == c.attempt
    migrate.main()
    c.columns['measurements']['row_version'] = ('int unsigned', 'NO', '99', '', '', None)
    with pytest.raises(RuntimeError, match='measurements.row_version'):
        migrate.main()


@pytest.mark.parametrize('applied', [False, True])
def test_main_preserves_checksum_enforcement(monkeypatch, applied):
    c = LedgerCatalog()
    configure_catalog_runner(monkeypatch, c)
    if applied:
        c.applied = '0' * 64
    else:
        c.attempt = '0' * 64
    with pytest.raises(RuntimeError, match='checksum changed'):
        migrate.main()


@pytest.fixture
def mysql_phase3():
    if os.getenv('ALE_PHASE3_MIGRATION_DB_TESTS') != '1':
        pytest.skip('Read-only default; opt in to disposable-schema DDL with ALE_PHASE3_MIGRATION_DB_TESTS=1')
    user, password = migrate.load_admin_creds()
    conn = pymysql.connect(host=os.getenv('ALE_DB_HOST', '127.0.0.1' if os.name == 'nt' else '172.16.10.254'),
                           port=int(os.getenv('ALE_DB_PORT', '3307')), user=user, password=password,
                           charset='utf8mb4', autocommit=True)
    schema = 'ale_phase3_migration_test_' + uuid.uuid4().hex
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
            conn.select_db(schema)
            for table, pk in [('users', 'user_id'), ('samples', 'sample_id'), ('source_files', 'file_id'), ('measurements', 'measurement_id'), ('measurement_points', 'point_id')]:
                cur.execute(f'CREATE TABLE {table} ({pk} BIGINT UNSIGNED PRIMARY KEY) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci')
            cur.execute('INSERT INTO measurements VALUES(7)')
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS `{schema}`')
        conn.close()


def apply_phase3(conn):
    with conn.cursor() as cur:
        for statement in statements():
            migrate.execute_resumable(cur, statement)


def test_real_mysql_replay_preservation_and_constraints(mysql_phase3):
    conn = mysql_phase3
    apply_phase3(conn)
    apply_phase3(conn)
    with conn.cursor() as cur:
        migrate.validate_phase3(cur, '0005')
        cur.execute('SELECT measurement_id,row_version,source_file_id,import_item_id,import_locator,provenance FROM measurements')
        assert cur.fetchall() == ((7, 1, None, None, None, None),)
        cur.execute('INSERT INTO users VALUES(1)')
        cur.execute('INSERT INTO source_files VALUES(1)')
        cur.execute('INSERT INTO import_jobs(job_id,owner_user_id) VALUES(1,1)')
        cur.execute("INSERT INTO import_items(item_id,job_id,filename,sha256,storage_key,parse_result) VALUES(1,1,'a.csv',REPEAT('a',64),'a','{}')")
        cur.execute("INSERT INTO import_confirmations VALUES(1,REPEAT('b',64),'{}')")
        cur.execute("INSERT INTO source_file_occurrences(source_file_id,import_item_id,owner_user_id,filename) VALUES(1,1,1,'mine.csv')")
        cur.execute("UPDATE measurements SET import_item_id=1,import_locator='sheet:1' WHERE measurement_id=7")
        for statement in [
            "INSERT INTO import_jobs(owner_user_id,status) VALUES(1,'bad')",
            "UPDATE import_items SET status='bad' WHERE item_id=1",
            "INSERT INTO import_confirmations VALUES(1,REPEAT('b',64),'{}')",
            "INSERT INTO source_file_occurrences(source_file_id,import_item_id,owner_user_id,filename) VALUES(1,1,1,'again.csv')",
            "INSERT INTO measurements(measurement_id,import_item_id,import_locator) VALUES(8,1,'sheet:1')",
            'DELETE FROM import_jobs WHERE job_id=1',
            'DELETE FROM source_files WHERE file_id=1',
        ]:
            with pytest.raises(pymysql.MySQLError):
                cur.execute(statement)


def test_real_interruption_resumes_but_rejects_wrong_existing_column(mysql_phase3):
    conn = mysql_phase3
    with conn.cursor() as cur:
        cur.execute('ALTER TABLE measurements ADD row_version INT UNSIGNED NOT NULL DEFAULT 99')
    apply_phase3(conn)
    with conn.cursor() as cur:
        with pytest.raises(RuntimeError, match='measurements.row_version'):
            migrate.validate_phase3(cur, '0005')
        cur.execute('ALTER TABLE measurements MODIFY row_version INT UNSIGNED NOT NULL DEFAULT 1')
    apply_phase3(conn)
    with conn.cursor() as cur:
        migrate.validate_phase3(cur, '0005')
