"""Versioned MySQL migration. Backup first; never recreate existing scientific tables."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'database'))
from apply_schema import load_admin_creds, split_statements, _is_comment_only


def serialize(value):
    if isinstance(value, bytes):
        return {'$binary': base64.b64encode(value).decode()}
    return str(value)


def snapshot(conn):
    directory = ROOT / 'backups' / ('before_migration_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    directory.mkdir(parents=True, exist_ok=False)
    counts = {}
    with conn.cursor() as cur:
        cur.execute("SELECT TABLE_NAME,TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_TYPE,TABLE_NAME")
        objects = cur.fetchall()
        ddl = []
        for name, kind in objects:
            cur.execute(f'SHOW CREATE TABLE `{name}`')
            ddl.append(cur.fetchone()[1] + ';')
            if kind != 'BASE TABLE':
                continue
            cur.execute(f'SELECT * FROM `{name}`')
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
            counts[name] = len(rows)
            (directory / (name + '.json')).write_text(json.dumps({'columns': columns, 'rows': rows}, default=serialize, ensure_ascii=False), encoding='utf-8')
        (directory / 'schema.sql').write_text('\n\n'.join(ddl), encoding='utf-8')
    (directory / 'manifest.json').write_text(json.dumps({'created_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'row_counts': counts}, indent=2), encoding='utf-8')
    return directory, counts


def execute_resumable(cur, statement):
    # The SQL file, not Python-generated DDL, is the checksum source.
    match = re.match(r"^ALTER\s+TABLE\s+`?(\w+)`?\s+ADD\s+(COLUMN|CONSTRAINT)\s+`?(\w+)`?", statement.strip(), re.I)
    if match:
        name, kind, item = match.groups()
        catalog = 'COLUMNS' if kind.upper() == 'COLUMN' else 'TABLE_CONSTRAINTS'
        field = 'COLUMN_NAME' if kind.upper() == 'COLUMN' else 'CONSTRAINT_NAME'
        cur.execute(f'SELECT COUNT(*) FROM information_schema.{catalog} WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND {field}=%s', (name,item))
        if cur.fetchone()[0]:return
    drop = re.match(r'^ALTER\s+TABLE\s+`?(\w+)`?\s+DROP\s+CHECK\s+`?(\w+)`?$', statement.strip(), re.I)
    if drop:
        cur.execute("SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s", drop.groups())
        if not cur.fetchone()[0]: return
    cur.execute(statement)


# Keep these contracts in sync with the immutable 0003/0004 SQL.  Existence
# alone is insufficient after an interrupted ADD or CREATE IF NOT EXISTS.
PHASE2_COLUMNS = {
    'experiment_plans': {'row_version': ('int unsigned', 'NO', '1', '')},
    'processes': {'row_version': ('int unsigned', 'NO', '1', '')},
    'process_steps': {'plan_step_id': ('bigint unsigned', 'YES', None, '')},
    'sample_transitions': {'step_id': ('bigint unsigned', 'YES', None, '')},
    'experiment_plan_steps': {
        'step_id': ('bigint unsigned', 'NO', None, 'auto_increment'),
        'plan_id': ('bigint unsigned', 'NO', None, ''),
        'step_index': ('int unsigned', 'NO', None, ''),
        'step_kind': ('varchar(32)', 'NO', None, ''),
        'planned_parameters': ('json', 'YES', None, ''),
        'step_note': ('text', 'YES', None, ''),
        'created_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'DEFAULT_GENERATED'),
    },
}
PHASE2_FOREIGN_KEYS = {
    ('experiment_plan_steps', 'fk_plan_steps_plan'): ('plan_id', 'experiment_plans', 'plan_id'),
    ('process_steps', 'fk_steps_plan_step'): ('plan_step_id', 'experiment_plan_steps', 'step_id'),
    ('sample_transitions', 'fk_transition_step'): ('step_id', 'process_steps', 'step_id'),
}
PHASE2_CHECKS = {
    ('experiment_plan_steps', 'chk_plan_steps_index'): 'step_index >= 1',
    ('experiment_plan_steps', 'chk_plan_steps_kind'):
        "step_kind IN ('o2_plasma','o3_purge','hf_purge','tma_purge','purge','wait','other')",
}
AUDIT_CHECK_0004 = ("entity_type IN ('experiment_plan','experiment_plan_step','process','process_step',"
                    "'process_sample','sample','sample_transition','measurement','measurement_point',"
                    "'derived_result','instrument_dataset','finding','issue','batch','recipe','user','source_file')")
AUDIT_CHECK_0006 = AUDIT_CHECK_0004[:-1] + ",'chemistry_system','chemistry_species','chemistry_step_template')"

AUDIT_CHECK_0007 = AUDIT_CHECK_0006[:-1] + ",'step_parameter_template')"

def _check_tokens(clause):
    # MySQL adds backticks, redundant parentheses and charset introducers.
    # Preserve string contents/case and every operator; substring checks would
    # accept weakened constraints (e.g. an extra OR or an extra allowed value).
    clause = clause.replace("\\'", "'")
    clause = re.sub(r"_[a-zA-Z0-9]+(?=')", '', clause)
    tokens = re.findall(r"'(?:''|[^'])*'|`[^`]*`|>=|<=|<>|!=|[a-zA-Z_][a-zA-Z_0-9]*|[0-9]+|[^\s]", clause)
    # Strip only enclosing parentheses, keeping internal grouping significant.
    while tokens and tokens[0] == '(' and tokens[-1] == ')':
        depth = 0
        for i, token in enumerate(tokens):
            if token == '(':
                depth += 1
            elif token == ')':
                depth -= 1
            if depth == 0:
                break
        if i != len(tokens) - 1:
            break
        tokens = tokens[1:-1]
    return tuple(t if t.startswith("'") else t.strip('`').lower() for t in tokens)


def validate_phase2(cur, version):
    """Read-only contract validation, before ledger writes and on every recheck."""
    if version not in ('0003', '0004'):
        return
    problems = []
    cur.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='experiment_plans' AND COLUMN_NAME='process_flow'")
    generic_flow = bool(cur.fetchone()[0])
    for table, columns in PHASE2_COLUMNS.items():
        cur.execute("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,"
                    "GENERATION_EXPRESSION,COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        actual = {row[0]: row[1:] for row in cur.fetchall()}
        for column, expected in columns.items():
            row = actual.get(column)
            if row is None:
                problems.append(f'{table}.{column}: missing column')
                continue
            typ, nullable, default, extra, generated, collation = row
            default = str(default) if default is not None else None
            if default and default.lower() == 'current_timestamp()':
                default = 'CURRENT_TIMESTAMP'
            observed = (typ.lower(), nullable, default, extra.lower())
            normalized = (*expected[:3], expected[3].lower())
            if generic_flow and table == 'experiment_plan_steps' and column == 'step_kind' and typ.lower() == 'varchar(128)':
                normalized = ('varchar(128)', *normalized[1:])
            if observed != normalized or generated:
                problems.append(f'{table}.{column}: expected {normalized!r}, found {observed!r}; generated={generated!r}')
            if table == 'experiment_plan_steps' and column in ('step_kind', 'step_note') and collation != 'utf8mb4_0900_ai_ci':
                problems.append(f'{table}.{column}: unexpected collation {collation!r}')
        # 0006 adds step_name/custom_parameters to this table. Validation is
        # read-only and may run before or after 0006, so the legacy shape and
        # the extended shape are both accepted; anything else is drift.
        if table == 'experiment_plan_steps' and set(actual) not in (
                set(columns), set(columns) | {'step_name', 'custom_parameters'},
                set(columns) | {'step_name', 'custom_parameters', 'parameter_snapshot'}):
            problems.append('experiment_plan_steps: column set differs from 0003')
    cur.execute("SELECT TABLE_TYPE,ENGINE,TABLE_COLLATION FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='experiment_plan_steps'")
    if cur.fetchone() != ('BASE TABLE', 'InnoDB', 'utf8mb4_0900_ai_ci'):
        problems.append('experiment_plan_steps: expected InnoDB base table / utf8mb4_0900_ai_ci')
    cur.execute("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,IS_VISIBLE,INDEX_TYPE "
                "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                "AND TABLE_NAME='experiment_plan_steps' ORDER BY INDEX_NAME,SEQ_IN_INDEX")
    indexes = {}
    for name, non_unique, seq, column, prefix, visible, kind in cur.fetchall():
        indexes.setdefault(name, []).append((non_unique, seq, column, prefix, visible, kind))
    for name, columns in {'PRIMARY': ('step_id',), 'uk_plan_steps_order': ('plan_id', 'step_index')}.items():
        expected = [(0, i, c, None, 'YES', 'BTREE') for i, c in enumerate(columns, 1)]
        if indexes.get(name) != expected:
            problems.append(f'experiment_plan_steps.{name}: expected unique ordered columns {columns!r}')
    for (table, name), (column, target, target_column) in PHASE2_FOREIGN_KEYS.items():
        cur.execute("SELECT k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,"
                    "k.REFERENCED_COLUMN_NAME,r.DELETE_RULE,r.UPDATE_RULE,k.ORDINAL_POSITION "
                    "FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                    "ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME "
                    "AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND k.TABLE_NAME=%s AND k.CONSTRAINT_NAME=%s ORDER BY k.ORDINAL_POSITION", (table, name))
        rows = cur.fetchall()
        cur.execute('SELECT DATABASE()')
        schema = cur.fetchone()[0]
        expected = ((column, schema, target, target_column, 'RESTRICT', 'NO ACTION', 1),)
        if rows != expected:
            problems.append(f'{table}.{name}: expected FK {column} -> {target}.{target_column}, DELETE RESTRICT / UPDATE NO ACTION; found {rows!r}')
    checks = dict(PHASE2_CHECKS)
    if version == '0004':
        checks[('audit_log', 'chk_audit_entity')] = (AUDIT_CHECK_0004, AUDIT_CHECK_0006, AUDIT_CHECK_0007)
    for (table, name), expected in checks.items():
        if generic_flow and name == 'chk_plan_steps_kind': continue
        cur.execute("SELECT c.CHECK_CLAUSE,t.ENFORCED FROM information_schema.TABLE_CONSTRAINTS t "
                    "JOIN information_schema.CHECK_CONSTRAINTS c ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA "
                    "AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME WHERE t.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND t.TABLE_NAME=%s AND t.CONSTRAINT_NAME=%s AND t.CONSTRAINT_TYPE='CHECK'", (table, name))
        row = cur.fetchone()
        # A tuple accepts the pre- and post-0006 renderings of one named CHECK.
        accepted = expected if isinstance(expected, tuple) else (expected,)
        if row is None or row[1] != 'YES' or not any(_check_tokens(row[0]) == _check_tokens(clause) for clause in accepted):
            problems.append(f'{table}.{name}: missing, disabled or different CHECK; found {row!r}')
    if problems:
        raise RuntimeError('Phase2 schema validation failed:\n- ' + '\n- '.join(problems))
    print('Verified phase2 schema:', version)


# Phase 3 contract mirrors the immutable 0005 SQL. New tables have exact
# column/index/FK/CHECK sets; existing scientific tables retain their old fields.
PHASE3_NEW_TABLES = {'import_jobs', 'import_items', 'import_confirmations', 'source_file_occurrences'}
PHASE3_COLUMNS = {
    'import_jobs': {
        'job_id': ('bigint unsigned', 'NO', None, 'auto_increment'),
        'owner_user_id': ('bigint unsigned', 'NO', None, ''),
        'status': ('varchar(24)', 'NO', 'draft', ''),
        'row_version': ('int unsigned', 'NO', '1', ''),
        'created_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated'),
    },
    'import_items': {
        'item_id': ('bigint unsigned', 'NO', None, 'auto_increment'),
        'job_id': ('bigint unsigned', 'NO', None, ''),
        'filename': ('varchar(255)', 'NO', None, ''),
        'sha256': ('char(64)', 'NO', None, ''),
        'storage_key': ('varchar(255)', 'NO', None, ''),
        'parse_result': ('json', 'NO', None, ''),
        'confirmation': ('json', 'YES', None, ''),
        'status': ('varchar(24)', 'NO', 'pending', ''),
        'result': ('json', 'YES', None, ''),
        'created_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated'),
    },
    'import_confirmations': {
        'job_id': ('bigint unsigned', 'NO', None, ''),
        'confirmation_hash': ('char(64)', 'NO', None, ''),
        'result': ('json', 'NO', None, ''),
    },
    'source_file_occurrences': {
        'occurrence_id': ('bigint unsigned', 'NO', None, 'auto_increment'),
        'source_file_id': ('bigint unsigned', 'NO', None, ''),
        'import_item_id': ('bigint unsigned', 'NO', None, ''),
        'owner_user_id': ('bigint unsigned', 'NO', None, ''),
        'sample_id': ('bigint unsigned', 'YES', None, ''),
        'filename': ('varchar(255)', 'NO', None, ''),
        'notes': ('text', 'YES', None, ''),
        'created_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated'),
    },
    'measurements': {
        'source_file_id': ('bigint unsigned', 'YES', None, ''),
        'import_item_id': ('bigint unsigned', 'YES', None, ''),
        'import_locator': ('varchar(255)', 'YES', None, ''),
        'row_version': ('int unsigned', 'NO', '1', ''),
        'provenance': ('json', 'YES', None, ''),
    },
    'measurement_points': {'raw_values': ('json', 'YES', None, '')},
}
# (NON_UNIQUE, ordered column names). FK support indexes are explicit on new
# tables; MySQL creates fk_msr_source_file on the existing measurements table.
PHASE3_INDEXES = {
    'import_jobs': {'PRIMARY': (0, ('job_id',)), 'ix_import_jobs_owner': (1, ('owner_user_id',))},
    'import_items': {'PRIMARY': (0, ('item_id',)), 'ix_import_items_job': (1, ('job_id',))},
    'import_confirmations': {'PRIMARY': (0, ('job_id', 'confirmation_hash'))},
    'source_file_occurrences': {
        'PRIMARY': (0, ('occurrence_id',)),
        'uk_source_occurrence_item': (0, ('import_item_id',)),
        'ix_source_occurrences_source': (1, ('source_file_id',)),
        'ix_source_occurrences_owner': (1, ('owner_user_id',)),
        'ix_source_occurrences_sample': (1, ('sample_id',)),
    },
    'measurements': {
        'uk_msr_import_locator': (0, ('import_item_id', 'import_locator')),
        'fk_msr_source_file': (1, ('source_file_id',)),
    },
}
PHASE3_FOREIGN_KEYS = {
    ('import_jobs', 'fk_import_jobs_owner'): ('owner_user_id', 'users', 'user_id'),
    ('import_items', 'fk_import_items_job'): ('job_id', 'import_jobs', 'job_id'),
    ('import_confirmations', 'fk_import_confirmations_job'): ('job_id', 'import_jobs', 'job_id'),
    ('source_file_occurrences', 'fk_source_occurrences_source'): ('source_file_id', 'source_files', 'file_id'),
    ('source_file_occurrences', 'fk_source_occurrences_item'): ('import_item_id', 'import_items', 'item_id'),
    ('source_file_occurrences', 'fk_source_occurrences_owner'): ('owner_user_id', 'users', 'user_id'),
    ('source_file_occurrences', 'fk_source_occurrences_sample'): ('sample_id', 'samples', 'sample_id'),
    ('measurements', 'fk_msr_source_file'): ('source_file_id', 'source_files', 'file_id'),
    ('measurements', 'fk_msr_import_item'): ('import_item_id', 'import_items', 'item_id'),
}
PHASE3_CHECKS = {
    ('import_jobs', 'chk_import_jobs_status'): "status IN ('draft','completed')",
    ('import_items', 'chk_import_items_status'): "status IN ('pending','imported','original_only','skipped')",
}


def validate_phase3(cur, version):
    """Read-only validation after resumable DDL, before ledger insert and on replay."""
    if version != '0005':
        return
    problems = []
    cur.execute('SELECT DATABASE()')
    schema = cur.fetchone()[0]
    for table, columns in PHASE3_COLUMNS.items():
        cur.execute("SELECT TABLE_TYPE,ENGINE,TABLE_COLLATION FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        if cur.fetchone() != ('BASE TABLE', 'InnoDB', 'utf8mb4_0900_ai_ci'):
            problems.append(f'{table}: expected InnoDB base table / utf8mb4_0900_ai_ci')
        cur.execute("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,"
                    "GENERATION_EXPRESSION,COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        actual = {row[0]: row[1:] for row in cur.fetchall()}
        if table in PHASE3_NEW_TABLES and set(actual) != set(columns):
            problems.append(f'{table}: column set differs from 0005')
        for column, expected in columns.items():
            row = actual.get(column)
            if row is None:
                problems.append(f'{table}.{column}: missing column')
                continue
            typ, nullable, default, extra, generated, collation = row
            default = str(default) if default is not None else None
            if default and default.lower() == 'current_timestamp()':
                default = 'CURRENT_TIMESTAMP'
            observed = (typ.lower(), nullable, default, extra.lower())
            if observed != expected or generated:
                problems.append(f'{table}.{column}: expected {expected!r}, found {observed!r}; generated={generated!r}')
            expected_collation = 'utf8mb4_0900_ai_ci' if expected[0].startswith(('varchar(', 'char(', 'text')) else None
            if collation != expected_collation:
                problems.append(f'{table}.{column}: unexpected collation {collation!r}')
        cur.execute("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,IS_VISIBLE,INDEX_TYPE,EXPRESSION "
                    "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX", (table,))
        indexes = {}
        for name, non_unique, seq, column, prefix, visible, kind, expression in cur.fetchall():
            indexes.setdefault(name, []).append((non_unique, seq, column, prefix, visible, kind, expression))
        expected_indexes = PHASE3_INDEXES.get(table, {})
        relevant_indexes = {name for name, rows in indexes.items()
                            if table in PHASE3_NEW_TABLES or name in expected_indexes
                            or any(row[2] in columns for row in rows)}
        if relevant_indexes != set(expected_indexes):
            problems.append(f'{table}: index set differs from 0005')
        for name, (non_unique, ordered) in expected_indexes.items():
            expected = [(non_unique, i, column, None, 'YES', 'BTREE', None) for i, column in enumerate(ordered, 1)]
            if indexes.get(name) != expected:
                problems.append(f'{table}.{name}: expected ordered index {expected!r}; found {indexes.get(name)!r}')
        # All FKs for new tables are exact, including their names, order and rules.
        # On old tables inspect all FKs touching the new fields, retaining old FKs.
        cur.execute("SELECT k.CONSTRAINT_NAME,k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,"
                    "k.REFERENCED_COLUMN_NAME,r.DELETE_RULE,r.UPDATE_RULE,k.ORDINAL_POSITION "
                    "FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                    "ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME "
                    "AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND k.TABLE_NAME=%s ORDER BY k.CONSTRAINT_NAME,k.ORDINAL_POSITION", (table,))
        foreign_keys = {}
        for name, *row in cur.fetchall():
            foreign_keys.setdefault(name, []).append(tuple(row))
        expected_fks = {name: [(column, schema, target, target_column, 'RESTRICT', 'NO ACTION', 1)]
                        for (t, name), (column, target, target_column) in PHASE3_FOREIGN_KEYS.items() if t == table}
        relevant_fks = {name: rows for name, rows in foreign_keys.items()
                        if table in PHASE3_NEW_TABLES or name in expected_fks or any(row[0] in columns for row in rows)}
        if relevant_fks != expected_fks:
            problems.append(f'{table}: foreign keys differ from 0005; expected {expected_fks!r}, found {relevant_fks!r}')
        cur.execute("SELECT t.CONSTRAINT_NAME,c.CHECK_CLAUSE,t.ENFORCED FROM information_schema.TABLE_CONSTRAINTS t "
                    "JOIN information_schema.CHECK_CONSTRAINTS c ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA "
                    "AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME WHERE t.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND t.TABLE_NAME=%s AND t.CONSTRAINT_TYPE='CHECK'", (table,))
        checks = {name: (clause, enforced) for name, clause, enforced in cur.fetchall()}
        expected_checks = {name: clause for (t, name), clause in PHASE3_CHECKS.items() if t == table}
        if table in PHASE3_NEW_TABLES and set(checks) != set(expected_checks):
            problems.append(f'{table}: CHECK set differs from 0005')
        for name, expected in expected_checks.items():
            row = checks.get(name)
            if row is None or row[1] != 'YES' or not any(_check_tokens(row[0]) == _check_tokens(clause) for clause in (expected if isinstance(expected, tuple) else (expected,))):
                problems.append(f'{table}.{name}: missing, disabled or different CHECK; found {row!r}')
    if problems:
        raise RuntimeError('Phase3 schema validation failed:\n- ' + '\n- '.join(problems))
    print('Verified phase3 schema:', version)


# Phase 4 contract mirrors the immutable 0006 SQL: three new chemistry tables
# with exact column/index/FK/CHECK sets, plus additive columns and replaced
# CHECK clauses on existing scientific tables.
PHASE4_NEW_TABLES = {'chemistry_systems', 'chemistry_species', 'chemistry_step_templates'}
PHASE4_COLUMNS = {
    'chemistry_systems': {
        'system_id': ('bigint unsigned', 'NO', None, 'auto_increment'),
        'system_code': ('varchar(64)', 'NO', None, ''),
        'system_name': ('varchar(255)', 'NO', None, ''),
        'description': ('text', 'YES', None, ''),
        'status': ('varchar(24)', 'NO', 'active', ''),
        'owner_user_id': ('bigint unsigned', 'YES', None, ''),
        'row_version': ('int unsigned', 'NO', '1', ''),
        'created_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated'),
        'updated_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated on update current_timestamp'),
    },
    'chemistry_species': {
        'species_id': ('bigint unsigned', 'NO', None, 'auto_increment'),
        'system_id': ('bigint unsigned', 'NO', None, ''),
        'species_code': ('varchar(64)', 'NO', None, ''),
        'species_name': ('varchar(255)', 'NO', None, ''),
        'formula': ('varchar(64)', 'YES', None, ''),
        'role': ('varchar(24)', 'NO', None, ''),
        'default_unit': ('varchar(24)', 'YES', None, ''),
        'notes': ('text', 'YES', None, ''),
        'created_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated'),
    },
    'chemistry_step_templates': {
        'template_id': ('bigint unsigned', 'NO', None, 'auto_increment'),
        'system_id': ('bigint unsigned', 'NO', None, ''),
        'template_code': ('varchar(64)', 'NO', None, ''),
        'template_name': ('varchar(255)', 'NO', None, ''),
        'description': ('text', 'YES', None, ''),
        'steps': ('json', 'NO', None, ''),
        'created_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated'),
        'updated_at': ('datetime', 'NO', 'CURRENT_TIMESTAMP', 'default_generated on update current_timestamp'),
    },
    'audit_log': {},
    'experiment_plans': {
        'status': ('varchar(24)', 'NO', 'draft', ''),
    },
    'processes': {
        'chemistry_system_id': ('bigint unsigned', 'YES', None, ''),
    },
    'experiment_plan_steps': {
        'step_name': ('varchar(128)', 'YES', None, ''),
        'custom_parameters': ('json', 'YES', None, ''),
    },
    'process_steps': {
        'step_name': ('varchar(128)', 'YES', None, ''),
        'custom_parameters': ('json', 'YES', None, ''),
    },
}
PHASE4_INDEXES = {
    'chemistry_systems': {'PRIMARY': (0, ('system_id',)), 'uk_chemistry_systems_code': (0, ('system_code',)),
                          'ix_chemistry_systems_owner': (1, ('owner_user_id',))},
    'chemistry_species': {'PRIMARY': (0, ('species_id',)), 'uk_species_code': (0, ('system_id', 'species_code'))},
    'chemistry_step_templates': {'PRIMARY': (0, ('template_id',)), 'uk_templates_code': (0, ('system_id', 'template_code'))},
}
PHASE4_FOREIGN_KEYS = {
    ('chemistry_systems', 'fk_chemistry_systems_owner'): ('owner_user_id', 'users', 'user_id', 'SET NULL', 'CASCADE'),
    ('chemistry_species', 'fk_species_system'): ('system_id', 'chemistry_systems', 'system_id', 'CASCADE', 'CASCADE'),
    ('chemistry_step_templates', 'fk_templates_system'): ('system_id', 'chemistry_systems', 'system_id', 'CASCADE', 'CASCADE'),
    ('processes', 'fk_processes_chemistry'): ('chemistry_system_id', 'chemistry_systems', 'system_id', 'SET NULL', 'CASCADE'),
}
PHASE4_CHECKS = {
    ('chemistry_systems', 'chk_chemistry_systems_status'): "status IN ('active','superseded','experimental')",
    ('chemistry_species', 'chk_species_role'): "`role` IN ('precursor','reactant','purge','carrier','other')",
    ('experiment_plans', 'chk_plans_status'): "status IN ('draft','approved','running','completed','abandoned','archived')",
}
PHASE4_AUDIT_CHECK = AUDIT_CHECK_0006
PHASE4_PLAN_CHECKS = {
    ('experiment_plans', 'chk_plans_priority'): "priority IN ('high','normal','low')",
}


def validate_phase4(cur, version):
    """Read-only validation of the 0006 contract, before ledger writes and on replay."""
    if version != '0006':
        return
    problems = []
    cur.execute('SELECT DATABASE()')
    schema = cur.fetchone()[0]
    for table, columns in PHASE4_COLUMNS.items():
        cur.execute("SELECT TABLE_TYPE,ENGINE,TABLE_COLLATION FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        if cur.fetchone() != ('BASE TABLE', 'InnoDB', 'utf8mb4_0900_ai_ci'):
            problems.append(f'{table}: expected InnoDB base table / utf8mb4_0900_ai_ci')
        cur.execute("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,"
                    "GENERATION_EXPRESSION,COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        actual = {row[0]: row[1:] for row in cur.fetchall()}
        if table in PHASE4_NEW_TABLES and set(actual) != set(columns):
            problems.append(f'{table}: column set differs from 0006')
        for column, expected in columns.items():
            row = actual.get(column)
            if row is None:
                problems.append(f'{table}.{column}: missing column')
                continue
            typ, nullable, default, extra, generated, collation = row
            default = str(default) if default is not None else None
            if default and default.lower() == 'current_timestamp()':
                default = 'CURRENT_TIMESTAMP'
            observed = (typ.lower(), nullable, default, extra.lower())
            if observed != expected or generated:
                problems.append(f'{table}.{column}: expected {expected!r}, found {observed!r}; generated={generated!r}')
            if table in PHASE4_NEW_TABLES:
                expected_collation = 'utf8mb4_0900_ai_ci' if expected[0].startswith(('varchar(', 'char(', 'text')) else None
                if collation != expected_collation:
                    problems.append(f'{table}.{column}: unexpected collation {collation!r}')
        cur.execute("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,IS_VISIBLE,INDEX_TYPE,EXPRESSION "
                    "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX", (table,))
        indexes = {}
        for name, non_unique, seq, column, prefix, visible, kind, expression in cur.fetchall():
            indexes.setdefault(name, []).append((non_unique, seq, column, prefix, visible, kind, expression))
        expected_indexes = PHASE4_INDEXES.get(table, {})
        if table in PHASE4_NEW_TABLES:
            relevant = {name for name, rows in indexes.items()
                        if name in expected_indexes or any(row[2] in columns for row in rows)}
            if relevant != set(expected_indexes):
                problems.append(f'{table}: index set differs from 0006')
        for name, (non_unique, ordered) in expected_indexes.items():
            expected = [(non_unique, i, column, None, 'YES', 'BTREE', None) for i, column in enumerate(ordered, 1)]
            if indexes.get(name) != expected:
                problems.append(f'{table}.{name}: expected ordered index {expected!r}; found {indexes.get(name)!r}')
        cur.execute("SELECT k.CONSTRAINT_NAME,k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,"
                    "k.REFERENCED_COLUMN_NAME,r.DELETE_RULE,r.UPDATE_RULE,k.ORDINAL_POSITION "
                    "FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                    "ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME "
                    "AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND k.TABLE_NAME=%s ORDER BY k.CONSTRAINT_NAME,k.ORDINAL_POSITION", (table,))
        foreign_keys = {}
        for name, *row in cur.fetchall():
            foreign_keys.setdefault(name, []).append(tuple(row))
        expected_fks = {name: [(column, schema, target, target_column, delete, update, 1)]
                        for (t, name), (column, target, target_column, delete, update) in PHASE4_FOREIGN_KEYS.items() if t == table}
        relevant_fks = {name: rows for name, rows in foreign_keys.items()
                        if table in PHASE4_NEW_TABLES or name in expected_fks or any(row[0] in columns for row in rows)}
        if relevant_fks != expected_fks:
            problems.append(f'{table}: foreign keys differ from 0006; expected {expected_fks!r}, found {relevant_fks!r}')
        cur.execute("SELECT t.CONSTRAINT_NAME,c.CHECK_CLAUSE,t.ENFORCED FROM information_schema.TABLE_CONSTRAINTS t "
                    "JOIN information_schema.CHECK_CONSTRAINTS c ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA "
                    "AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME WHERE t.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND t.TABLE_NAME=%s AND t.CONSTRAINT_TYPE='CHECK'", (table,))
        checks = {name: (clause, enforced) for name, clause, enforced in cur.fetchall()}
        expected_checks = {name: clause for (t, name), clause in PHASE4_CHECKS.items() if t == table}
        expected_checks.update({name: clause for (t, name), clause in PHASE4_PLAN_CHECKS.items() if t == table})
        if table == 'audit_log':
            expected_checks['chk_audit_entity'] = (PHASE4_AUDIT_CHECK, AUDIT_CHECK_0007)
        if table in PHASE4_NEW_TABLES and set(checks) != set(expected_checks):
            problems.append(f'{table}: CHECK set differs from 0006')
        for name, expected in expected_checks.items():
            row = checks.get(name)
            if row is None or row[1] != 'YES' or not any(_check_tokens(row[0]) == _check_tokens(clause) for clause in (expected if isinstance(expected, tuple) else (expected,))):
                problems.append(f'{table}.{name}: missing, disabled or different CHECK; found {row!r}')
    if problems:
        raise RuntimeError('Phase4 schema validation failed:\n- ' + '\n- '.join(problems))
    print('Verified phase4 schema:', version)


PHASE5_NEW_TABLES = {'step_parameter_templates'}
PHASE5_COLUMNS = {
    'batches': {'archived_at': ('datetime','YES',None,'')},
    'processes': {'archived_at': ('datetime','YES',None,'')},
    'experiment_plan_steps': {'parameter_snapshot': ('json','YES',None,'')},
    'process_steps': {'parameter_snapshot': ('json','YES',None,'')},
    'audit_log': {},
    'step_parameter_templates': {
        'template_id': ('bigint unsigned','NO',None,'auto_increment'),
        'template_name': ('varchar(128)','NO',None,''),
        'owner_user_id': ('bigint unsigned','NO',None,''),
        'definition': ('json','NO',None,''),
        'row_version': ('int unsigned','NO','1',''),
        'created_at': ('datetime','NO','CURRENT_TIMESTAMP','default_generated'),
        'updated_at': ('datetime','NO','CURRENT_TIMESTAMP','default_generated on update current_timestamp'),
    },
}
PHASE5_INDEXES = {'step_parameter_templates': {
    'PRIMARY': (0, ('template_id',)),
    'ix_step_parameter_templates_owner': (1, ('owner_user_id',)),
}}
PHASE5_FOREIGN_KEYS = {('step_parameter_templates','fk_step_parameter_templates_owner'):
    ('owner_user_id','users','user_id','RESTRICT','NO ACTION')}
PHASE5_CHECKS = {}
PHASE5_PLAN_CHECKS = {}
PHASE5_AUDIT_CHECK = AUDIT_CHECK_0007


def validate_phase5(cur, version):
    """Read-only validation of the 0007 contract, before ledger writes and on replay."""
    if version != '0007':
        return
    problems = []
    cur.execute('SELECT DATABASE()')
    schema = cur.fetchone()[0]
    for table, columns in PHASE5_COLUMNS.items():
        cur.execute("SELECT TABLE_TYPE,ENGINE,TABLE_COLLATION FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        if cur.fetchone() != ('BASE TABLE', 'InnoDB', 'utf8mb4_0900_ai_ci'):
            problems.append(f'{table}: expected InnoDB base table / utf8mb4_0900_ai_ci')
        cur.execute("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,"
                    "GENERATION_EXPRESSION,COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        actual = {row[0]: row[1:] for row in cur.fetchall()}
        if table in PHASE5_NEW_TABLES and set(actual) != set(columns):
            problems.append(f'{table}: column set differs from 0007')
        for column, expected in columns.items():
            row = actual.get(column)
            if row is None:
                problems.append(f'{table}.{column}: missing column')
                continue
            typ, nullable, default, extra, generated, collation = row
            default = str(default) if default is not None else None
            if default and default.lower() == 'current_timestamp()':
                default = 'CURRENT_TIMESTAMP'
            observed = (typ.lower(), nullable, default, extra.lower())
            if observed != expected or generated:
                problems.append(f'{table}.{column}: expected {expected!r}, found {observed!r}; generated={generated!r}')
            if table in PHASE5_NEW_TABLES:
                expected_collation = 'utf8mb4_0900_ai_ci' if expected[0].startswith(('varchar(', 'char(', 'text')) else None
                if collation != expected_collation:
                    problems.append(f'{table}.{column}: unexpected collation {collation!r}')
        cur.execute("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,IS_VISIBLE,INDEX_TYPE,EXPRESSION "
                    "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX", (table,))
        indexes = {}
        for name, non_unique, seq, column, prefix, visible, kind, expression in cur.fetchall():
            indexes.setdefault(name, []).append((non_unique, seq, column, prefix, visible, kind, expression))
        expected_indexes = PHASE5_INDEXES.get(table, {})
        if table in PHASE5_NEW_TABLES:
            relevant = {name for name, rows in indexes.items()
                        if name in expected_indexes or any(row[2] in columns for row in rows)}
            if relevant != set(expected_indexes):
                problems.append(f'{table}: index set differs from 0007')
        for name, (non_unique, ordered) in expected_indexes.items():
            expected = [(non_unique, i, column, None, 'YES', 'BTREE', None) for i, column in enumerate(ordered, 1)]
            if indexes.get(name) != expected:
                problems.append(f'{table}.{name}: expected ordered index {expected!r}; found {indexes.get(name)!r}')
        cur.execute("SELECT k.CONSTRAINT_NAME,k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,"
                    "k.REFERENCED_COLUMN_NAME,r.DELETE_RULE,r.UPDATE_RULE,k.ORDINAL_POSITION "
                    "FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                    "ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME "
                    "AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND k.TABLE_NAME=%s ORDER BY k.CONSTRAINT_NAME,k.ORDINAL_POSITION", (table,))
        foreign_keys = {}
        for name, *row in cur.fetchall():
            foreign_keys.setdefault(name, []).append(tuple(row))
        expected_fks = {name: [(column, schema, target, target_column, delete, update, 1)]
                        for (t, name), (column, target, target_column, delete, update) in PHASE5_FOREIGN_KEYS.items() if t == table}
        relevant_fks = {name: rows for name, rows in foreign_keys.items()
                        if table in PHASE5_NEW_TABLES or name in expected_fks or any(row[0] in columns for row in rows)}
        if relevant_fks != expected_fks:
            problems.append(f'{table}: foreign keys differ from 0007; expected {expected_fks!r}, found {relevant_fks!r}')
        cur.execute("SELECT t.CONSTRAINT_NAME,c.CHECK_CLAUSE,t.ENFORCED FROM information_schema.TABLE_CONSTRAINTS t "
                    "JOIN information_schema.CHECK_CONSTRAINTS c ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA "
                    "AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME WHERE t.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND t.TABLE_NAME=%s AND t.CONSTRAINT_TYPE='CHECK'", (table,))
        checks = {name: (clause, enforced) for name, clause, enforced in cur.fetchall()}
        expected_checks = {name: clause for (t, name), clause in PHASE5_CHECKS.items() if t == table}
        expected_checks.update({name: clause for (t, name), clause in PHASE5_PLAN_CHECKS.items() if t == table})
        if table == 'audit_log':
            expected_checks['chk_audit_entity'] = PHASE5_AUDIT_CHECK
        if table in PHASE5_NEW_TABLES and set(checks) != set(expected_checks):
            problems.append(f'{table}: CHECK set differs from 0007')
        for name, expected in expected_checks.items():
            row = checks.get(name)
            if row is None or row[1] != 'YES' or not any(_check_tokens(row[0]) == _check_tokens(clause) for clause in (expected if isinstance(expected, tuple) else (expected,))):
                problems.append(f'{table}.{name}: missing, disabled or different CHECK; found {row!r}')
    if problems:
        raise RuntimeError('Phase5 schema validation failed:\n- ' + '\n- '.join(problems))
    print('Verified phase5 schema:', version)


SAMPLE_VOID_CHECK = "((voided_at IS NULL) AND (void_reason IS NULL) AND (voided_by_user_id IS NULL)) OR ((voided_at IS NOT NULL) AND (void_reason IS NOT NULL) AND (CHAR_LENGTH(TRIM(void_reason)) > 0) AND (voided_by_user_id IS NOT NULL))"

def validate_sample_void(cur,version):
    """Validate additive 0008 definitions on apply, interrupted retry and status."""
    if version!='0008':return
    expected={'voided_at':('datetime','YES',None,''),
              'void_reason':('varchar(2000)','YES',None,''),
              'voided_by_user_id':('bigint unsigned','YES',None,'')}
    for column,contract in expected.items():
        cur.execute("SELECT COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,GENERATION_EXPRESSION,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='samples' AND COLUMN_NAME=%s",(column,))
        row=cur.fetchone()
        if row is None or tuple(row[:4])!=contract or row[4] or row[5]!=('utf8mb4_0900_ai_ci' if column=='void_reason' else None):
            raise RuntimeError('Sample void column contract mismatch: '+column)
    cur.execute("SELECT k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,k.REFERENCED_COLUMN_NAME,r.DELETE_RULE,r.UPDATE_RULE,k.ORDINAL_POSITION FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() AND k.TABLE_NAME='samples' AND k.CONSTRAINT_NAME='fk_samples_void_actor'")
    rows=cur.fetchall()
    cur.execute('SELECT DATABASE()');schema=cur.fetchone()[0]
    if tuple(rows)!=(('voided_by_user_id',schema,'users','user_id','RESTRICT','NO ACTION',1),):
        raise RuntimeError('Sample void actor foreign key contract mismatch')
    cur.execute("SELECT c.CHECK_CLAUSE,t.ENFORCED FROM information_schema.TABLE_CONSTRAINTS t JOIN information_schema.CHECK_CONSTRAINTS c ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME WHERE t.CONSTRAINT_SCHEMA=DATABASE() AND t.TABLE_NAME='samples' AND t.CONSTRAINT_NAME='chk_samples_void_metadata'")
    row=cur.fetchone()
    if row is None or row[1]!='YES' or _check_tokens(row[0])!=_check_tokens(SAMPLE_VOID_CHECK):
        raise RuntimeError('Sample void metadata CHECK contract mismatch')
    print('Verified sample void schema:',version)



AI_NEW_TABLES = {'ai_conversations', 'ai_config', 'ai_budget_periods', 'ai_requests', 'ai_messages', 'ai_tool_traces'}
AI_COLUMNS = {'ai_config': {'config_id': ('int unsigned', 'NO', None, ''),
               'settings': ('json', 'NO', None, ''),
               'key_ciphertext': ('text', 'YES', None, ''),
               'discovered_models': ('json', 'YES', None, ''),
               'revision': ('int unsigned', 'NO', '1', ''),
               'updated_by': ('bigint unsigned', 'YES', None, ''),
               'updated_at': ('datetime',
                              'NO',
                              'CURRENT_TIMESTAMP',
                              'default_generated')},
 'ai_budget_periods': {'period': ('char(7)', 'NO', None, ''),
                       'charged_tokens': ('bigint unsigned', 'NO', '0', ''),
                       'reserved_tokens': ('bigint unsigned', 'NO', '0', ''),
                       'charged_cost': ('decimal(24,8)', 'NO', '0.00000000', ''),
                       'reserved_cost': ('decimal(24,8)', 'NO', '0.00000000', '')},
 'ai_conversations': {'conversation_id': ('char(36)', 'NO', None, ''),
                      'owner_user_id': ('bigint unsigned', 'NO', None, ''),
                      'busy_request_id': ('char(36)', 'YES', None, ''),
                      'created_at': ('datetime',
                                     'NO',
                                     'CURRENT_TIMESTAMP',
                                     'default_generated'),
                      'updated_at': ('datetime',
                                     'NO',
                                     'CURRENT_TIMESTAMP',
                                     'default_generated')},
 'ai_requests': {'request_id': ('char(36)', 'NO', None, ''),
                 'owner_user_id': ('bigint unsigned', 'NO', None, ''),
                 'conversation_id': ('char(36)', 'YES', None, ''),
                 'request_hash': ('char(64)', 'NO', None, ''),
                 'purpose': ('varchar(12)', 'NO', None, ''),
                 'status': ('varchar(12)', 'NO', None, ''),
                 'period': ('char(7)', 'NO', None, ''),
                 'reserved_tokens': ('bigint unsigned', 'NO', None, ''),
                 'reserved_cost': ('decimal(24,8)', 'NO', None, ''),
                 'prompt_tokens': ('bigint unsigned', 'NO', '0', ''),
                 'completion_tokens': ('bigint unsigned', 'NO', '0', ''),
                 'cache_hit_tokens': ('bigint unsigned', 'NO', '0', ''),
                 'cache_miss_tokens': ('bigint unsigned', 'NO', '0', ''),
                 'charged_tokens': ('bigint unsigned', 'NO', '0', ''),
                 'charged_cost': ('decimal(24,8)', 'NO', '0.00000000', ''),
                 'usage_estimated': ('tinyint unsigned', 'NO', '0', ''),
                 'provider_calls': ('int unsigned', 'NO', '0', ''),
                 'result': ('json', 'YES', None, ''),
                 'created_at': ('datetime',
                                'NO',
                                'CURRENT_TIMESTAMP',
                                'default_generated'),
                 'finished_at': ('datetime', 'YES', None, '')},
 'ai_messages': {'message_id': ('bigint unsigned',
                                'NO',
                                None,
                                'auto_increment'),
                 'conversation_id': ('char(36)', 'NO', None, ''),
                 'request_id': ('char(36)', 'NO', None, ''),
                 'role': ('varchar(12)', 'NO', None, ''),
                 'content': ('text', 'NO', None, ''),
                 'created_at': ('datetime',
                                'NO',
                                'CURRENT_TIMESTAMP',
                                'default_generated')},
 'ai_tool_traces': {'trace_id': ('bigint unsigned',
                                 'NO',
                                 None,
                                 'auto_increment'),
                    'request_id': ('char(36)', 'NO', None, ''),
                    'tool_name': ('varchar(64)', 'NO', None, ''),
                    'status': ('varchar(12)', 'NO', None, ''),
                    'sources': ('json', 'NO', None, ''),
                    'result_bytes': ('int unsigned', 'NO', None, ''),
                    'created_at': ('datetime',
                                   'NO',
                                   'CURRENT_TIMESTAMP',
                                   'default_generated')}}
AI_INDEXES = {'ai_config': {'PRIMARY': (0, ('config_id',)), 'fk_ai_config_actor': (1, ('updated_by',))},
 'ai_budget_periods': {'PRIMARY': (0, ('period',))},
 'ai_conversations': {'PRIMARY': (0, ('conversation_id',)),
                      'ix_ai_conversations_owner': (1, ('owner_user_id',))},
 'ai_requests': {'PRIMARY': (0, ('request_id',)),
                 'ix_ai_requests_owner_day': (1,
                                              ('owner_user_id', 'created_at')),
                 'ix_ai_requests_period': (1, ('period',)),
                 'ix_ai_requests_conversation': (1, ('conversation_id',))},
 'ai_messages': {'PRIMARY': (0, ('message_id',)),
                 'ix_ai_messages_conversation': (1,
                                                 ('conversation_id',
                                                  'message_id')),
                 'ix_ai_messages_request': (1, ('request_id',))},
 'ai_tool_traces': {'PRIMARY': (0, ('trace_id',)),
                    'ix_ai_tool_traces_request': (1, ('request_id',))}}
AI_FOREIGN_KEYS = {('ai_config', 'fk_ai_config_actor'): ('updated_by', 'users', 'user_id'),
 ('ai_conversations', 'fk_ai_conversations_owner'): ('owner_user_id',
                                                     'users',
                                                     'user_id'),
 ('ai_requests', 'fk_ai_requests_owner'): ('owner_user_id', 'users', 'user_id'),
 ('ai_requests', 'fk_ai_requests_conversation'): ('conversation_id',
                                                  'ai_conversations',
                                                  'conversation_id'),
 ('ai_requests', 'fk_ai_requests_period'): ('period',
                                            'ai_budget_periods',
                                            'period'),
 ('ai_messages', 'fk_ai_messages_conversation'): ('conversation_id',
                                                  'ai_conversations',
                                                  'conversation_id'),
 ('ai_messages', 'fk_ai_messages_request'): ('request_id',
                                             'ai_requests',
                                             'request_id'),
 ('ai_tool_traces', 'fk_ai_tool_traces_request'): ('request_id',
                                                   'ai_requests',
                                                   'request_id')}
AI_CHECKS = {('ai_config', 'chk_ai_config_singleton'): 'config_id = 1',
 ('ai_budget_periods', 'chk_ai_budget_cost'): 'charged_cost >= 0 AND '
                                              'reserved_cost >= 0',
 ('ai_requests', 'chk_ai_requests_status'): 'status IN '
                                            "('pending','completed','failed')",
 ('ai_requests', 'chk_ai_requests_purpose'): 'purpose IN '
                                             "('chat','test','models')",
 ('ai_requests', 'chk_ai_requests_cost'): 'reserved_cost >= 0 AND charged_cost '
                                          '>= 0',
 ('ai_messages', 'chk_ai_messages_role'): "role IN ('user','assistant')",
 ('ai_tool_traces', 'chk_ai_tool_traces_status'): 'status IN '
                                                  "('completed','denied')"}

AI_CHECKS[('ai_budget_periods', 'chk_ai_budget_cost')] = '(charged_cost >= 0) AND (reserved_cost >= 0)'
AI_CHECKS[('ai_requests', 'chk_ai_requests_cost')] = '(reserved_cost >= 0) AND (charged_cost >= 0)'

def validate_ai(cur, version):
    """Read-only validation after resumable DDL, before ledger insert and on replay."""
    if version != '0009':
        return
    problems = []
    cur.execute('SELECT DATABASE()')
    schema = cur.fetchone()[0]
    for table, columns in AI_COLUMNS.items():
        cur.execute("SELECT TABLE_TYPE,ENGINE,TABLE_COLLATION FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        if cur.fetchone() != ('BASE TABLE', 'InnoDB', 'utf8mb4_0900_ai_ci'):
            problems.append(f'{table}: expected InnoDB base table / utf8mb4_0900_ai_ci')
        cur.execute("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,"
                    "GENERATION_EXPRESSION,COLLATION_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        actual = {row[0]: row[1:] for row in cur.fetchall()}
        if table in AI_NEW_TABLES and set(actual) != set(columns):
            problems.append(f'{table}: column set differs from 0009')
        for column, expected in columns.items():
            row = actual.get(column)
            if row is None:
                problems.append(f'{table}.{column}: missing column')
                continue
            typ, nullable, default, extra, generated, collation = row
            default = str(default) if default is not None else None
            if default and default.lower() == 'current_timestamp()':
                default = 'CURRENT_TIMESTAMP'
            observed = (typ.lower(), nullable, default, extra.lower())
            if observed != expected or generated:
                problems.append(f'{table}.{column}: expected {expected!r}, found {observed!r}; generated={generated!r}')
            expected_collation = 'utf8mb4_0900_ai_ci' if expected[0].startswith(('varchar(', 'char(', 'text')) else None
            if collation != expected_collation:
                problems.append(f'{table}.{column}: unexpected collation {collation!r}')
        cur.execute("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,IS_VISIBLE,INDEX_TYPE,EXPRESSION "
                    "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
                    "AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX", (table,))
        indexes = {}
        for name, non_unique, seq, column, prefix, visible, kind, expression in cur.fetchall():
            indexes.setdefault(name, []).append((non_unique, seq, column, prefix, visible, kind, expression))
        expected_indexes = AI_INDEXES.get(table, {})
        relevant_indexes = {name for name, rows in indexes.items()
                            if table in AI_NEW_TABLES or name in expected_indexes
                            or any(row[2] in columns for row in rows)}
        if relevant_indexes != set(expected_indexes):
            problems.append(f'{table}: index set differs from 0009')
        for name, (non_unique, ordered) in expected_indexes.items():
            expected = [(non_unique, i, column, None, 'YES', 'BTREE', None) for i, column in enumerate(ordered, 1)]
            if indexes.get(name) != expected:
                problems.append(f'{table}.{name}: expected ordered index {expected!r}; found {indexes.get(name)!r}')
        # All FKs for new tables are exact, including their names, order and rules.
        # On old tables inspect all FKs touching the new fields, retaining old FKs.
        cur.execute("SELECT k.CONSTRAINT_NAME,k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,"
                    "k.REFERENCED_COLUMN_NAME,r.DELETE_RULE,r.UPDATE_RULE,k.ORDINAL_POSITION "
                    "FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                    "ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME "
                    "AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND k.TABLE_NAME=%s ORDER BY k.CONSTRAINT_NAME,k.ORDINAL_POSITION", (table,))
        foreign_keys = {}
        for name, *row in cur.fetchall():
            foreign_keys.setdefault(name, []).append(tuple(row))
        expected_fks = {name: [(column, schema, target, target_column, 'RESTRICT', 'NO ACTION', 1)]
                        for (t, name), (column, target, target_column) in AI_FOREIGN_KEYS.items() if t == table}
        relevant_fks = {name: rows for name, rows in foreign_keys.items()
                        if table in AI_NEW_TABLES or name in expected_fks or any(row[0] in columns for row in rows)}
        if relevant_fks != expected_fks:
            problems.append(f'{table}: foreign keys differ from 0009; expected {expected_fks!r}, found {relevant_fks!r}')
        cur.execute("SELECT t.CONSTRAINT_NAME,c.CHECK_CLAUSE,t.ENFORCED FROM information_schema.TABLE_CONSTRAINTS t "
                    "JOIN information_schema.CHECK_CONSTRAINTS c ON c.CONSTRAINT_SCHEMA=t.CONSTRAINT_SCHEMA "
                    "AND c.CONSTRAINT_NAME=t.CONSTRAINT_NAME WHERE t.CONSTRAINT_SCHEMA=DATABASE() "
                    "AND t.TABLE_NAME=%s AND t.CONSTRAINT_TYPE='CHECK'", (table,))
        checks = {name: (clause, enforced) for name, clause, enforced in cur.fetchall()}
        expected_checks = {name: clause for (t, name), clause in AI_CHECKS.items() if t == table}
        if table in AI_NEW_TABLES and set(checks) != set(expected_checks):
            problems.append(f'{table}: CHECK set differs from 0009')
        for name, expected in expected_checks.items():
            row = checks.get(name)
            if row is None or row[1] != 'YES' or not any(_check_tokens(row[0]) == _check_tokens(clause) for clause in (expected if isinstance(expected, tuple) else (expected,))):
                problems.append(f'{table}.{name}: missing, disabled or different CHECK; found {row!r}')
    if problems:
        raise RuntimeError('AI schema validation failed:\n- ' + '\n- '.join(problems))
    print('Verified AI schema:', version)


def validate_process_flow(cur, version):
    if version != '0010': return
    for name in ('experiment_plans','processes'):
        cur.execute("SELECT COLUMN_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='process_flow'", (name,))
        if cur.fetchone() != ('json','YES'): raise RuntimeError('Invalid flow column: '+name)
    for name, check in (('experiment_plan_steps','chk_plan_steps_kind'),('process_steps','chk_steps_kind')):
        cur.execute("SELECT COLUMN_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='step_kind'", (name,))
        if cur.fetchone() != ('varchar(128)','NO'): raise RuntimeError('Invalid classification column: '+name)
        cur.execute("SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s", (name,check))
        if cur.fetchone()[0]: raise RuntimeError('Legacy classification check still present: '+name)
    print('Verified generic process flow: 0010')


SAMPLE_LIFECYCLE_COLUMNS = {
    'archived_at': ('datetime', 'YES', None, ''),
    'archived_by_user_id': ('bigint unsigned', 'YES', None, ''),
}


def validate_sample_lifecycle(cur, version):
    """Validate the additive 0011 sample archive metadata; read-only, replay-safe."""
    if version != '0011':
        return
    for column, contract in SAMPLE_LIFECYCLE_COLUMNS.items():
        cur.execute("SELECT COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,GENERATION_EXPRESSION,COLLATION_NAME "
                    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='samples' "
                    "AND COLUMN_NAME=%s", (column,))
        row = cur.fetchone()
        if row is None or tuple(row[:4]) != contract or row[4] or row[5] is not None:
            raise RuntimeError('Sample lifecycle column contract mismatch: ' + column)
    cur.execute("SELECT k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,"
                "k.REFERENCED_COLUMN_NAME,r.DELETE_RULE,r.UPDATE_RULE,k.ORDINAL_POSITION "
                "FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                "ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME "
                "AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE() "
                "AND k.TABLE_NAME='samples' AND k.CONSTRAINT_NAME='fk_samples_archive_actor'")
    rows = cur.fetchall()
    cur.execute('SELECT DATABASE()')
    schema = cur.fetchone()[0]
    if tuple(rows) != (('archived_by_user_id', schema, 'users', 'user_id', 'RESTRICT', 'NO ACTION', 1),):
        raise RuntimeError('Sample archive actor foreign key contract mismatch')
    print('Verified sample lifecycle schema:', version)


def validate_all_lifecycle(cur, version):
    if version != '0012': return
    for name in ('batches', 'experiment_plans', 'processes'):
        for column, typ in (('voided_at','datetime'),('void_reason','varchar(2000)'),('voided_by_user_id','bigint unsigned')):
            cur.execute("SELECT COLUMN_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s", (name,column))
            if cur.fetchone() != (typ,'YES'): raise RuntimeError('Lifecycle column mismatch: '+name+'.'+column)
        cur.execute("SELECT DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s", (name,'fk_'+name+'_void_actor'))
        if cur.fetchone() != ('RESTRICT',): raise RuntimeError('Lifecycle FK mismatch: '+name)
        cur.execute("SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME=%s", ('chk_'+name+'_void_metadata',))
        if not cur.fetchone(): raise RuntimeError('Lifecycle CHECK missing: '+name)
    cur.execute("SELECT COLUMN_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='experiment_plans' AND COLUMN_NAME='archive_previous_status'")
    if cur.fetchone() != ('varchar(24)','YES'): raise RuntimeError('Plan archive recovery metadata missing')
    print('Verified all-record lifecycle: 0012')


def verify_original_values(conn,directory):
    """Compare every pre-existing field using the consistent pre-DDL backup.

    New nullable columns are intentionally excluded. Ledger entries are additive.
    This is a deployment-time check; run migrations before allowing writers.
    """
    from collections import Counter
    checked=0
    with conn.cursor() as cur:
        for file in sorted(directory.glob('*.json')):
            if file.stem in ('manifest','schema_migrations','schema_migration_attempts'):continue
            saved=json.loads(file.read_text(encoding='utf-8'))
            columns=','.join('`'+name+'`' for name in saved['columns'])
            cur.execute(f'SELECT {columns} FROM `{file.stem}`')
            actual=json.loads(json.dumps(cur.fetchall(),default=serialize,ensure_ascii=False))
            encode=lambda row:json.dumps(row,ensure_ascii=False,sort_keys=True)
            if Counter(map(encode,saved['rows']))!=Counter(map(encode,actual)):
                raise RuntimeError('Original value preservation failed: '+file.stem)
            checked+=len(actual)
    print('Verified all original field values preserved:',checked,'rows')

def report_legacy_in_process(cur):
    """Report current anomalies only; never invent transitions or change status."""
    cur.execute("SELECT COUNT(*) FROM samples s WHERE s.status='in_process' AND NOT EXISTS ("
                "SELECT 1 FROM sample_transitions t WHERE t.sample_id=s.sample_id AND t.event_type='load' "
                "AND NOT EXISTS (SELECT 1 FROM sample_transitions newer WHERE newer.sample_id=s.sample_id "
                "AND newer.event_type IN ('load','unload') AND newer.transition_id>t.transition_id))")
    count = cur.fetchone()[0]
    print(f'Legacy in_process samples without active load: {count}; read-only detection, no data changed; no history synthesized.')
    return count


def migration_files():
    return sorted((ROOT / 'database/migrations').glob('*.sql'))


def show_status(cur):
    cur.execute("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='schema_migrations'")
    if not cur.fetchone()[0]:
        print('No versioned migrations applied')
        return
    cur.execute('SELECT version,filename,sha256,applied_at FROM schema_migrations ORDER BY version')
    applied = cur.fetchall()
    files = {file.stem.split('_')[0]: file for file in migration_files()}
    for version, filename, digest, applied_at in applied:
        file = files.get(version)
        if file is None or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Applied migration checksum changed or file missing: ' + filename)
        validate_phase2(cur, version)
        validate_phase3(cur, version)
        validate_phase4(cur, version)
        validate_phase5(cur, version)
        validate_sample_void(cur, version)
        validate_ai(cur, version)
        validate_process_flow(cur, version)
        validate_sample_lifecycle(cur, version)
        validate_all_lifecycle(cur, version)
        if version=='0014':validate_quick(cur)
        if version=='0015':validate_quick_sources(cur)
        if version=='0016':validate_quick_excel_fields(cur)
        print(version, filename, applied_at)


def validate_quick(cur):
    required={'quick_materials':('material_id','owner_user_id','canonical_name','aliases'),
              'quick_runs':('process_id','owner_user_id','experiment_date','daily_no','sequence_id','previous_process_id','payload','request_key','request_hash'),
              'quick_revisions':('revision_id','process_id','actor_user_id','version','snapshot','reason'),
              'quick_templates':('template_id','owner_user_id','name','snapshot','version'),
              'quick_imports':('token','owner_user_id','process_id','sha256','filename','preview','confirmation'),
              'quick_exports':('export_id','owner_user_id','manifest','sha256')}
    for name,columns in required.items():
        cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s',(name,))
        actual={r[0] for r in cur.fetchall()}
        if not set(columns)<=actual:raise RuntimeError('Incomplete V2.2 schema: '+name)
    cur.execute("SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME IN ('quick_materials','quick_runs','quick_revisions','quick_templates','quick_imports','quick_exports')")
    if cur.fetchone()[0]!=10:raise RuntimeError('V2.2 foreign key validation failed')


def validate_quick_sources(cur):
    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='quick_sources'")
    if not {'source_id','owner_user_id','canonical_name'}<={r[0] for r in cur.fetchall()}:raise RuntimeError('Incomplete source catalog schema')
    cur.execute("SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='quick_sources'")
    if cur.fetchone()[0]!=1:raise RuntimeError('Source catalog ownership constraint missing')


def validate_quick_excel_fields(cur):
    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='quick_runs'")
    if not {'external_experiment_id','external_batch_id','process_type','rf_icp_power_w','bias_power_w','equipment','chamber_pressure_pa','r1_temp_c','r2_temp_c','n2_flow_sccm','started_at','ended_at','note'}<={r[0] for r in cur.fetchall()}:
        raise RuntimeError('Incomplete 0016 quick_runs projection columns')
    for name,columns in {'quick_results':('run_id','result_id','ordinal','thickness_before_nm','thickness_after_nm','effective_cycles','result_label','use_for_model_override'),
                         'quick_steps':('run_id','step_id','group_id','ordinal','source_label','pulse_ms','purge_s','wait_s','delta_p_pa','delta_p_pa_min','delta_p_pa_max')}.items():
        cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s',(name,))
        if not set(columns)<={r[0] for r in cur.fetchall()}:raise RuntimeError('Incomplete 0016 schema: '+name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--database', default='ale_workbench', help='Existing production or explicit *_test database')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]+',args.database) or (args.database!='ale_workbench' and not args.database.endswith('_test')):
        raise RuntimeError('Only the existing production or an explicit *_test database is allowed')
    user, password = load_admin_creds()
    conn = pymysql.connect(host=os.getenv('ALE_DB_HOST', '127.0.0.1' if os.name == 'nt' else '172.16.10.254'), port=int(os.getenv('ALE_DB_PORT', '3307')),
                           user=user, password=password, database=args.database, charset='utf8mb4', autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK('ale_workbench_migrations',10)")
            if cur.fetchone()[0] != 1:
                raise RuntimeError('Another migration is running')
            report_legacy_in_process(cur)
            if args.status:
                show_status(cur)
                return
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        backup, counts = snapshot(conn)
        conn.commit()
        print('Backup:', backup.name, 'existing rows:', sum(counts.values()))
        applied_count = 0
        with conn.cursor() as cur:
            cur.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(32) PRIMARY KEY, filename VARCHAR(255) NOT NULL, sha256 CHAR(64) NOT NULL, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB')
            cur.execute('CREATE TABLE IF NOT EXISTS schema_migration_attempts (version VARCHAR(32) PRIMARY KEY, sha256 CHAR(64) NOT NULL, started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB')
            attempted_count = 0
            for file in migration_files():
                version = file.stem.split('_')[0]
                digest = hashlib.sha256(file.read_bytes()).hexdigest()
                cur.execute('SELECT sha256 FROM schema_migrations WHERE version=%s', (version,))
                applied = cur.fetchone()
                if applied:
                    if applied[0] != digest:
                        raise RuntimeError('Applied migration checksum changed: ' + file.name)
                    validate_phase2(cur, version)
                    validate_phase3(cur, version)
                    validate_phase4(cur, version)
                    validate_phase5(cur, version)
                    validate_sample_void(cur, version)
                    validate_ai(cur, version)
                    validate_process_flow(cur, version)
                    validate_sample_lifecycle(cur, version)
                    validate_all_lifecycle(cur, version)
                    if version=='0014':validate_quick(cur)
                    if version=='0015':validate_quick_sources(cur)
                    print('Already applied:', file.name)
                    continue
                cur.execute('SELECT sha256 FROM schema_migration_attempts WHERE version=%s', (version,))
                attempt = cur.fetchone()
                if attempt and attempt[0] != digest:
                    raise RuntimeError('Interrupted migration checksum changed: ' + file.name)
                if not attempt:
                    cur.execute('INSERT INTO schema_migration_attempts(version,sha256) VALUES(%s,%s)', (version,digest))
                    attempted_count += 1
                for statement in split_statements(file.read_text(encoding='utf-8')):
                    if statement.strip() and not _is_comment_only(statement):
                        executable = re.sub(r'^\s*(?:--[^\n]*(?:\n|$)\s*)+', '', statement)
                        execute_resumable(cur, executable)
                if version == '0014':
                    validate_quick(cur)
                    cur.execute("SELECT Host FROM mysql.user WHERE User='ale_app'")
                    for (host,) in cur.fetchall():
                        for name in ('materials','runs','revisions','templates','imports','exports'):
                            cur.execute(f"GRANT SELECT, INSERT, UPDATE ON `{args.database}`.`quick_{name}` TO %s@%s",('ale_app',host))
                if version == '0015':
                    validate_quick_sources(cur)
                    cur.execute("SELECT Host FROM mysql.user WHERE User='ale_app'")
                    for (host,) in cur.fetchall():
                        cur.execute(f"GRANT SELECT, INSERT, UPDATE ON `{args.database}`.`quick_sources` TO %s@%s",('ale_app',host))
                if version == '0016':
                    validate_quick_excel_fields(cur)
                    cur.execute("SELECT Host FROM mysql.user WHERE User='ale_app'")
                    for (host,) in cur.fetchall():
                        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{args.database}`.`quick_results` TO %s@%s",('ale_app',host))
                        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{args.database}`.`quick_steps` TO %s@%s",('ale_app',host))
                if version == '0002':
                    for table, column in [('users','token_version'),('batches','row_version'),('samples','row_version')]:
                        cur.execute('SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s', (table,column))
                        if not cur.fetchone()[0]:
                            cur.execute(f'ALTER TABLE `{table}` ADD COLUMN `{column}` INT UNSIGNED NOT NULL DEFAULT 1')
                validate_phase2(cur, version)
                validate_phase3(cur, version)
                validate_phase4(cur, version)
                validate_phase5(cur, version)
                validate_sample_void(cur, version)
                validate_ai(cur, version)
                validate_process_flow(cur, version)
                validate_sample_lifecycle(cur, version)
                validate_all_lifecycle(cur, version)
                cur.execute('INSERT INTO schema_migrations(version,filename,sha256) VALUES(%s,%s,%s)', (version,file.name,digest))
                applied_count += 1
                print('Applied:', file.name)
            for table, count in counts.items():
                cur.execute(f'SELECT COUNT(*) FROM `{table}`')
                expected_count = count + (applied_count if table == 'schema_migrations' else attempted_count if table == 'schema_migration_attempts' else 0)
                if cur.fetchone()[0] != expected_count:
                    raise RuntimeError('Row preservation check failed: ' + table)
            cur.execute("SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME='chk_il_entity'")
            clause = cur.fetchone()[0]
            assert 'derived_result' in clause and 'instrument_dataset' in clause
        verify_original_values(conn,backup)
        print('Verified: all pre-existing row counts and field values preserved; nine issue entity types enforced.')
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK('ale_workbench_migrations')")
        conn.close()

if __name__ == '__main__':
    main()
