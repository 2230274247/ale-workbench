"""Real MySQL migration regressions; all DDL is confined to disposable schemas."""
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import uuid

import pymysql
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ale_migrate_tests', ROOT / 'database/migrate.py')
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)
FILES = list(migrate.migration_files())
PHASE2 = [p for p in FILES if p.name.startswith(('0003_', '0004_'))]


@pytest.fixture
def mysql():
    user, password = migrate.load_admin_creds()
    conn = pymysql.connect(host=os.getenv('ALE_DB_HOST', '127.0.0.1' if os.name == 'nt' else '172.16.10.254'),
                           port=int(os.getenv('ALE_DB_PORT', '3307')), user=user, password=password,
                           charset='utf8mb4', autocommit=True)
    schema = 'ale_migration_test_' + uuid.uuid4().hex
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        conn.select_db(schema)
        with conn.cursor() as cur:
            for statement in [
                'CREATE TABLE experiment_plans (plan_id BIGINT UNSIGNED PRIMARY KEY)',
                'CREATE TABLE processes (process_id BIGINT UNSIGNED PRIMARY KEY)',
                'CREATE TABLE process_steps (step_id BIGINT UNSIGNED PRIMARY KEY)',
                "CREATE TABLE samples (sample_id BIGINT UNSIGNED PRIMARY KEY, status VARCHAR(24), row_version INT DEFAULT 7)",
                'CREATE TABLE sample_transitions (transition_id BIGINT UNSIGNED PRIMARY KEY, sample_id BIGINT UNSIGNED, event_type VARCHAR(32), event_at DATETIME NULL)',
                "CREATE TABLE audit_log (entity_type VARCHAR(32), CONSTRAINT chk_audit_entity CHECK(entity_type IN ('experiment_plan','process')))",
                "CREATE TABLE issues_links (entity_type VARCHAR(32), CONSTRAINT chk_il_entity CHECK(entity_type IN ('derived_result','instrument_dataset')))",
            ]:
                cur.execute(statement)
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS `{schema}`')
        conn.close()


def apply_sql(conn):
    with conn.cursor() as cur:
        for file in PHASE2:
            for statement in migrate.split_statements(file.read_text(encoding='utf-8')):
                executable = migrate.re.sub(r'^\s*(?:--[^\n]*(?:\n|$)\s*)+', '', statement)
                migrate.execute_resumable(cur, executable)


def read_business_rows(conn):
    with conn.cursor() as cur:
        rows = []
        for name in ('samples', 'sample_transitions', 'audit_log'):
            cur.execute(f'SELECT * FROM {name} ORDER BY 1')
            rows.append(cur.fetchall())
        return rows


def test_legacy_readonly_uses_latest_load_unload_id(mysql, capsys):
    with mysql.cursor() as cur:
        cur.executemany('INSERT INTO samples(sample_id,status) VALUES(%s,%s)',
                        [(1, 'in_process'), (2, 'in_process'), (3, 'in_process'),
                         (4, 'in_process'), (5, 'available'), (6, 'in_process')])
        # 1: no history; 2: unloaded; 3: active load despite later measure;
        # 4: reloaded; 5: not in_process; 6: receive only. event_at is not ordering.
        cur.executemany('INSERT INTO sample_transitions VALUES(%s,%s,%s,%s)', [
            (1, 2, 'load', '2026-01-02'), (2, 2, 'unload', '2026-01-01'),
            (3, 3, 'load', None), (4, 3, 'measure', None),
            (5, 4, 'load', None), (6, 4, 'unload', None), (7, 4, 'load', None),
            (8, 6, 'receive', None)])
    before = read_business_rows(mysql)
    with mysql.cursor() as cur:
        assert migrate.report_legacy_in_process(cur) == 3
        assert migrate.report_legacy_in_process(cur) == 3
    assert read_business_rows(mysql) == before
    assert 'without active load: 3; read-only detection, no data changed' in capsys.readouterr().out


def test_valid_sql_contract_and_resumable_replay(mysql):
    apply_sql(mysql)
    apply_sql(mysql)
    with mysql.cursor() as cur:
        migrate.validate_phase2(cur, '0003')
        migrate.validate_phase2(cur, '0004')
        # Actual server enforcement, with a valid referenced parent.
        cur.execute('INSERT INTO experiment_plans(plan_id) VALUES(1)')
        cur.execute("INSERT INTO experiment_plan_steps(plan_id,step_index,step_kind) VALUES(1,1,'wait')")
        for sql in [
            "INSERT INTO experiment_plan_steps(plan_id,step_index,step_kind) VALUES(1,0,'wait')",
            "INSERT INTO experiment_plan_steps(plan_id,step_index,step_kind) VALUES(1,2,'invalid')",
            "INSERT INTO experiment_plan_steps(plan_id,step_index,step_kind) VALUES(1,1,'wait')",
            'DELETE FROM experiment_plans WHERE plan_id=1',
            "INSERT INTO audit_log VALUES('invalid')",
        ]:
            with pytest.raises(pymysql.MySQLError):
                cur.execute(sql)
        cur.execute("INSERT INTO audit_log VALUES('experiment_plan_step')")


DRIFT = [
    ('ALTER TABLE experiment_plans MODIFY row_version BIGINT UNSIGNED NOT NULL DEFAULT 1', 'experiment_plans.row_version'),
    ('ALTER TABLE processes MODIFY row_version INT NOT NULL DEFAULT 1', 'processes.row_version'),
    ('ALTER TABLE processes MODIFY row_version INT UNSIGNED NULL DEFAULT 1', 'processes.row_version'),
    ('ALTER TABLE processes MODIFY row_version INT UNSIGNED NOT NULL DEFAULT 2', 'processes.row_version'),
    ('ALTER TABLE processes DROP COLUMN row_version', 'processes.row_version'),
    ('ALTER TABLE experiment_plan_steps MODIFY step_kind VARCHAR(64) NOT NULL', 'step_kind'),
    ('ALTER TABLE experiment_plan_steps MODIFY planned_parameters TEXT NULL', 'planned_parameters'),
    ('ALTER TABLE experiment_plan_steps MODIFY step_note TEXT NOT NULL', 'step_note'),
    ('ALTER TABLE experiment_plan_steps MODIFY created_at DATETIME NOT NULL', 'created_at'),
    ('ALTER TABLE experiment_plan_steps MODIFY step_id BIGINT UNSIGNED NOT NULL', 'step_id'),
    ('ALTER TABLE experiment_plan_steps ADD unexpected INT', 'column set'),
    ('ALTER TABLE experiment_plan_steps MODIFY step_note TEXT COLLATE utf8mb4_bin NULL', 'collation'),
    ('ALTER TABLE experiment_plan_steps DROP INDEX uk_plan_steps_order, ADD KEY uk_plan_steps_order(plan_id,step_index)', 'uk_plan_steps_order'),
    ('ALTER TABLE experiment_plan_steps DROP INDEX uk_plan_steps_order, ADD UNIQUE KEY uk_plan_steps_order(step_index,plan_id)', 'uk_plan_steps_order'),
    ('ALTER TABLE process_steps DROP FOREIGN KEY fk_steps_plan_step, ADD CONSTRAINT fk_steps_plan_step FOREIGN KEY(plan_step_id) REFERENCES processes(process_id) ON DELETE RESTRICT', 'fk_steps_plan_step'),
    ('ALTER TABLE sample_transitions DROP FOREIGN KEY fk_transition_step, ADD CONSTRAINT fk_transition_step FOREIGN KEY(step_id) REFERENCES process_steps(step_id) ON DELETE SET NULL', 'fk_transition_step'),
    ('ALTER TABLE experiment_plan_steps DROP FOREIGN KEY fk_plan_steps_plan, ADD CONSTRAINT fk_plan_steps_plan FOREIGN KEY(plan_id) REFERENCES experiment_plans(plan_id) ON DELETE CASCADE', 'fk_plan_steps_plan'),
    ('ALTER TABLE process_steps DROP FOREIGN KEY fk_steps_plan_step, ADD CONSTRAINT fk_steps_plan_step FOREIGN KEY(plan_step_id) REFERENCES experiment_plan_steps(step_id) ON DELETE RESTRICT ON UPDATE CASCADE', 'fk_steps_plan_step'),
    ('ALTER TABLE process_steps DROP FOREIGN KEY fk_steps_plan_step', 'fk_steps_plan_step'),
    ('ALTER TABLE experiment_plan_steps DROP CHECK chk_plan_steps_index, ADD CONSTRAINT chk_plan_steps_index CHECK(step_index >= 0)', 'chk_plan_steps_index'),
    ('ALTER TABLE experiment_plan_steps ALTER CHECK chk_plan_steps_index NOT ENFORCED', 'chk_plan_steps_index'),
    ("ALTER TABLE experiment_plan_steps DROP CHECK chk_plan_steps_kind, ADD CONSTRAINT chk_plan_steps_kind CHECK(step_kind IN ('o2_plasma','o3_purge','hf_purge','tma_purge','purge','wait','other','bad'))", 'chk_plan_steps_kind'),
    ("ALTER TABLE audit_log DROP CHECK chk_audit_entity, ADD CONSTRAINT chk_audit_entity CHECK(entity_type IN ('experiment_plan_step'))", 'chk_audit_entity'),
    ('ALTER TABLE audit_log ALTER CHECK chk_audit_entity NOT ENFORCED', 'chk_audit_entity'),
]


@pytest.mark.parametrize('sql,expected', DRIFT)
def test_schema_drift_is_rejected(mysql, sql, expected):
    apply_sql(mysql)
    with mysql.cursor() as cur:
        if sql.startswith('ALTER TABLE experiment_plan_steps MODIFY step_id'):
            cur.execute('ALTER TABLE process_steps DROP FOREIGN KEY fk_steps_plan_step')
        if 'ADD UNIQUE KEY uk_plan_steps_order(step_index,plan_id)' in sql:
            cur.execute('ALTER TABLE experiment_plan_steps ADD KEY ix_test_plan(plan_id)')
        if ' DROP FOREIGN KEY ' in sql and ', ADD CONSTRAINT ' in sql:
            drop, add = sql.split(', ADD CONSTRAINT ', 1)
            cur.execute(drop)
            cur.execute(sql.split(' DROP FOREIGN KEY ', 1)[0] + ' ADD CONSTRAINT ' + add)
        else:
            cur.execute(sql)
        with pytest.raises(RuntimeError, match=expected):
            migrate.validate_phase2(cur, '0004')


class KeepConnection:
    def __init__(self, conn):
        self.conn = conn
    def __getattr__(self, name):
        return getattr(self.conn, name)
    def close(self):
        pass


def configure_main(monkeypatch, mysql):
    monkeypatch.setattr(migrate.pymysql, 'connect', lambda **kwargs: KeepConnection(mysql))
    monkeypatch.setattr(migrate, 'migration_files', lambda: PHASE2)
    monkeypatch.setattr(migrate, 'snapshot', lambda conn: (Path('test_snapshot'), {}))
    monkeypatch.setattr(sys, 'argv', ['migrate.py'])


def test_main_rejects_partial_wrong_schema_before_applied_then_recovers(mysql, monkeypatch):
    configure_main(monkeypatch, mysql)
    with mysql.cursor() as cur:
        cur.execute('ALTER TABLE processes ADD row_version INT UNSIGNED NOT NULL DEFAULT 99')
    with pytest.raises(RuntimeError, match='processes.row_version'):
        migrate.main()
    with mysql.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM schema_migrations')
        assert cur.fetchone()[0] == 0
        cur.execute('SELECT version,sha256 FROM schema_migration_attempts')
        assert cur.fetchall() == (('0003', hashlib.sha256(PHASE2[0].read_bytes()).hexdigest()),)
        cur.execute('ALTER TABLE processes MODIFY row_version INT UNSIGNED NOT NULL DEFAULT 1')
    migrate.main()
    migrate.main()
    with mysql.cursor() as cur:
        cur.execute('SELECT version,sha256 FROM schema_migrations ORDER BY version')
        assert cur.fetchall() == tuple((p.stem.split('_')[0], hashlib.sha256(p.read_bytes()).hexdigest()) for p in PHASE2)


@pytest.mark.parametrize('status', [False, True])
def test_applied_schema_drift_rejected_by_status_and_rerun(mysql, monkeypatch, status):
    configure_main(monkeypatch, mysql)
    migrate.main()
    with mysql.cursor() as cur:
        cur.execute('ALTER TABLE audit_log ALTER CHECK chk_audit_entity NOT ENFORCED')
    before = read_business_rows(mysql)
    if status:
        monkeypatch.setattr(sys, 'argv', ['migrate.py', '--status'])
    with pytest.raises(RuntimeError, match='chk_audit_entity'):
        migrate.main()
    assert read_business_rows(mysql) == before


@pytest.mark.parametrize('status', [False, True])
def test_checksum_still_enforced_on_status_and_rerun(mysql, monkeypatch, status):
    configure_main(monkeypatch, mysql)
    migrate.main()
    with mysql.cursor() as cur:
        cur.execute("UPDATE schema_migrations SET sha256=%s WHERE version='0003'", ('0' * 64,))
    if status:
        monkeypatch.setattr(sys, 'argv', ['migrate.py', '--status'])
    with pytest.raises(RuntimeError, match='checksum changed'):
        migrate.main()


def test_interrupted_checksum_cannot_be_replaced(mysql, monkeypatch):
    configure_main(monkeypatch, mysql)
    with mysql.cursor() as cur:
        cur.execute('ALTER TABLE processes ADD row_version INT UNSIGNED NOT NULL DEFAULT 99')
    with pytest.raises(RuntimeError):
        migrate.main()
    with mysql.cursor() as cur:
        cur.execute("UPDATE schema_migration_attempts SET sha256=%s WHERE version='0003'", ('0' * 64,))
    with pytest.raises(RuntimeError, match='Interrupted migration checksum changed'):
        migrate.main()


def test_status_does_not_create_ledger(mysql, monkeypatch, capsys):
    configure_main(monkeypatch, mysql)
    monkeypatch.setattr(sys, 'argv', ['migrate.py', '--status'])
    migrate.main()
    assert 'No versioned migrations applied' in capsys.readouterr().out
    with mysql.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME LIKE 'schema_migration%'")
        assert cur.fetchone()[0] == 0


def test_main_preserves_legacy_values_and_history(mysql, monkeypatch, capsys):
    configure_main(monkeypatch, mysql)
    with mysql.cursor() as cur:
        cur.execute("INSERT INTO samples VALUES(1,'in_process',42)")
    before = read_business_rows(mysql)
    migrate.main()
    migrate.main()
    monkeypatch.setattr(sys, 'argv', ['migrate.py', '--status'])
    migrate.main()
    assert read_business_rows(mysql) == before
    assert capsys.readouterr().out.count('without active load: 1; read-only detection, no data changed') == 3


def test_0004_validation_precedes_ledger_insert(mysql, monkeypatch):
    configure_main(monkeypatch, mysql)
    execute = migrate.execute_resumable

    def interrupted_or_wrong_audit(cur, statement):
        execute(cur, statement)
        if 'DROP CHECK chk_audit_entity' in statement:
            cur.execute('ALTER TABLE audit_log ALTER CHECK chk_audit_entity NOT ENFORCED')

    monkeypatch.setattr(migrate, 'execute_resumable', interrupted_or_wrong_audit)
    with pytest.raises(RuntimeError, match='chk_audit_entity'):
        migrate.main()
    with mysql.cursor() as cur:
        cur.execute('SELECT version FROM schema_migrations')
        assert cur.fetchall() == (('0003',),)
    monkeypatch.setattr(migrate, 'execute_resumable', execute)
    migrate.main()
    with mysql.cursor() as cur:
        migrate.validate_phase2(cur, '0004')
        cur.execute('SELECT version FROM schema_migrations ORDER BY version')
        assert cur.fetchall() == (('0003',), ('0004',))


def test_missing_plan_table_rejected(mysql):
    apply_sql(mysql)
    with mysql.cursor() as cur:
        cur.execute('ALTER TABLE process_steps DROP FOREIGN KEY fk_steps_plan_step')
        cur.execute('DROP TABLE experiment_plan_steps')
        with pytest.raises(RuntimeError, match='experiment_plan_steps'):
            migrate.validate_phase2(cur, '0004')


def test_check_tokens_normalize_mysql_rendering_without_losing_grouping():
    assert migrate._check_tokens("(`step_kind` in (_utf8mb4\\'wait\\',_utf8mb4\\'other\\'))") == migrate._check_tokens("step_kind IN ('wait','other')")
    assert migrate._check_tokens("a AND (b OR c)") != migrate._check_tokens("(a AND b) OR c")
    assert migrate._check_tokens("entity_type IN ('Sample')") != migrate._check_tokens("entity_type IN ('sample')")
