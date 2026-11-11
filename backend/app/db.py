from functools import lru_cache
from sqlalchemy import MetaData, create_engine, event
from .config import database_url

class MigrationRequired(RuntimeError):
    pass

@lru_cache
def engine():
    e = create_engine(database_url(), pool_pre_ping=True, hide_parameters=True, echo=False,
                      isolation_level="READ COMMITTED",
                      connect_args={'connect_timeout': 5})
    @event.listens_for(e, 'connect')
    def utc(dbapi_connection, _):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")
    return e

@lru_cache
def metadata():
    m = MetaData()
    m.reflect(bind=engine(), views=False)
    for name in ('users','invitations'):
        if name not in m.tables or 'account_purpose' not in m.tables[name].c:
            raise MigrationRequired('Required migration 0013_account_purpose.sql is missing')
    for name, columns in {
        'ai_config': ('config_id','settings','key_ciphertext','revision','discovered_models'),
        'ai_budget_periods': ('period','charged_tokens','reserved_tokens','charged_cost','reserved_cost'),
        'ai_conversations': ('conversation_id','owner_user_id','busy_request_id'),
        'ai_requests': ('request_id','owner_user_id','reserved_cost','result','usage_estimated'),
        'ai_messages': ('message_id','conversation_id','content'),
        'ai_tool_traces': ('trace_id','request_id','sources'),
        'import_jobs': ('owner_user_id','status','row_version'), 'import_items': ('parse_result','confirmation','result'),
        'import_confirmations': ('confirmation_hash','result'), 'source_file_occurrences': ('import_item_id','owner_user_id'),
        'measurements': ('source_file_id','import_item_id','row_version','provenance'), 'measurement_points': ('raw_values',),
        'experiment_plans': ('row_version','voided_at','archive_previous_status'), 'processes': ('row_version','chemistry_system_id','archived_at','voided_at'),
        'experiment_plan_steps': ('step_id','planned_parameters','step_name','custom_parameters','parameter_snapshot'),
        'process_steps': ('plan_step_id','step_name','custom_parameters','parameter_snapshot'),
        'chemistry_systems': ('system_id','system_code','status','owner_user_id','row_version'),
        'step_parameter_templates': ('template_id','template_name','owner_user_id','definition','row_version','created_at','updated_at'),
        'chemistry_species': ('species_id','system_id','species_code','role'),
        'chemistry_step_templates': ('template_id','system_id','template_code','steps'),
        'sample_transitions': ('step_id',), 'users': ('token_version','account_purpose'), 'batches': ('row_version','archived_at','voided_at'), 'samples': ('row_version','voided_at','void_reason','voided_by_user_id','archived_at','archived_by_user_id'),
        'auth_sessions': ('session_id','refresh_jti_hash','revoked_at'),
        'invitations': ('invitation_id','code_hash','account_purpose'), 'app_settings': ('setting_key','setting_value')
    }.items():
        if name not in m.tables or any(c not in m.tables[name].c for c in columns):
            raise MigrationRequired('Required application migration is missing')
    return m

def table(name):
    return metadata().tables[name]

def get_db():
    with engine().begin() as connection:
        yield connection
