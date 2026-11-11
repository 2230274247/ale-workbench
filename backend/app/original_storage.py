"""Content-addressed originals. No filename ever participates in a filesystem path."""
import hashlib
import os
import re
import tempfile
from pathlib import Path
from sqlalchemy import event, text
from threading import Lock

_POOL_SETUP = Lock()


def lock_original(db, sha256, timeout=5):
    """Serialize storage writers/GC across processes until connection return.

    Locks outlive commit, including its failure window. Pool reset releases only
    our own advisory locks; rollback fixtures keep their locks until teardown.
    """
    storage_key(sha256)
    pool = db.engine.pool
    with _POOL_SETUP:
        if not getattr(pool, '_ale_original_locks', False):
            def release(connection, record, reset_state):
                names = record.info.pop('ale_original_locks', set())
                cleanup = record.info.pop('ale_original_cleanup', {})
                if connection is not None and names:
                    # Resolve any uncommitted transaction before inspecting references.
                    connection.rollback()
                    try:
                        with connection.cursor() as cursor:
                            for sha in cleanup:
                                if not _has_references(cursor, sha):
                                    remove_temporary_original(sha, cleanup[sha])
                    finally:
                        connection.rollback()
                        with connection.cursor() as cursor:
                            for name in names:
                                cursor.execute('SELECT RELEASE_LOCK(%s)', (name,))
            event.listen(pool, 'reset', release)
            pool._ale_original_locks = True
    # MySQL lock names have a 64-character limit; the full SHA is already unique.
    name = sha256
    names = db.info.setdefault('ale_original_locks', set())
    if name in names:
        return True
    if db.scalar(text('SELECT GET_LOCK(:name, :timeout)'), {'name': name, 'timeout': timeout}) != 1:
        return False
    names.add(name)
    return True


def _has_references(cursor, sha256):
    # Legacy attachments and batch ZIPs may refer directly to an original without
    # a source_files/import_items row. Preserve these bytes on task deletion too.
    for table_name, column in (('import_items', 'sha256'),
                               ('source_files', 'file_sha256'),
                               ('attachments', 'file_sha256'),
                               ('batches', 'source_zip_sha256')):
        cursor.execute(f'SELECT 1 FROM {table_name} WHERE {column}=%s LIMIT 1', (sha256,))
        if cursor.fetchone():
            return True
    return False


def remove_temporary_original(sha256, root):
    """Caller must hold the SHA lock and prove no DB references after commit."""
    path = root / storage_key(sha256)
    if path.is_symlink() or path.parent.is_symlink() or root.is_symlink():
        return False
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        # A cleanup failure must never turn a committed task deletion into failure.
        return False
from .config import ROOT
from .common import fail


def originals_root():
    return Path(os.getenv('ALE_ORIGINALS_ROOT', str(ROOT / 'storage' / 'originals')))


def storage_key(sha256):
    if not re.fullmatch(r'[0-9a-f]{64}', sha256):
        fail(422, 'Invalid SHA256')
    return sha256[:2] + '/' + sha256


def read_verified(sha256):
    path = originals_root() / storage_key(sha256)
    try:
        if path.is_symlink() or path.parent.is_symlink():
            fail(409, 'Original storage integrity failure')
        content = path.read_bytes()
    except OSError:
        fail(409, 'Original file is unavailable')
    if hashlib.sha256(content).hexdigest() != sha256:
        fail(409, 'Original storage integrity failure')
    return content


def store_original(content):
    sha = hashlib.sha256(content).hexdigest()
    target = originals_root() / storage_key(sha)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        fail(409, 'Original storage integrity failure')
    if target.exists():
        read_verified(sha)
        return sha, storage_key(sha)
    fd, temporary = tempfile.mkstemp(prefix='.incoming-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(Path(temporary).read_bytes()).hexdigest() != sha:
            fail(409, 'Original storage integrity failure')
        # Atomic create without replacing any existing immutable object.
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        read_verified(sha)
        if os.name != 'nt':
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return sha, storage_key(sha)
