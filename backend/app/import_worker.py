"""Bounded spawn workers for upload parsing; originals are persisted by imports only."""
import asyncio
import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading

PARSE_TIMEOUT_SECONDS = 20
_PARSE_SLOTS = threading.BoundedSemaphore(2)


def _parse_worker(content, filename, result_path):
    """Module-level spawn target: no application/DB imports or inherited connections."""
    from .parsers import parse_file
    result = parse_file(content, filename)
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def _failure(content, filename, code, message):
    return {'type': 'unsupported', 'parser': 'original_only', 'version': 'worker-1',
            'status': 'original_only', 'blocks': [], 'warnings': [],
            'blocking_issues': [{'code': code, 'message': message, 'locator': None, 'field': None}],
            'filename_hints': {'source': 'filename_only', 'requires_confirmation': True, 'n': None, 'k': None},
            'source': {'filename': filename, 'sha256': hashlib.sha256(content).hexdigest(), 'size_bytes': len(content)}}


def _supervise(content, filename):
    # A file avoids pipe backpressure for large point previews. Nothing is read
    # until the child has exited, so a half-written result cannot block recv().
    with tempfile.TemporaryDirectory(prefix='ale-import-') as directory:
        result_path = str(Path(directory) / 'result.json')
        process = multiprocessing.get_context('spawn').Process(
            target=_parse_worker, args=(content, filename, result_path))
        try:
            process.start()
            process.join(PARSE_TIMEOUT_SECONDS)
            if process.is_alive():
                return _failure(content, filename, 'parser_timeout',
                                f'Preview parsing exceeded {PARSE_TIMEOUT_SECONDS:g} seconds; retain original or retry.')
            if process.exitcode != 0:
                return _failure(content, filename, 'parser_worker_failed',
                                'Preview parser process failed; retain original or retry.')
            result = json.loads(Path(result_path).read_text(encoding='utf-8'))
            if not isinstance(result, dict) or not {'status', 'blocks', 'blocking_issues', 'warnings'} <= result.keys():
                raise ValueError('Invalid parser result')
            # Provenance always describes the complete uploaded bytes, including
            # binary/unknown RGA and XPS originals. A worker cannot supply a
            # partial-content hash or turn an archive-only result into spectra.
            result['source'] = {'filename': filename,
                                'sha256': hashlib.sha256(content).hexdigest(),
                                'size_bytes': len(content)}
            if result['status'] == 'original_only':
                result['blocks'] = []
            return result
        except Exception:
            return _failure(content, filename, 'parser_worker_failed',
                            'Preview parser process could not complete; retain original or retry.')
        finally:
            # Also covers start/read errors. Reap before removing temporary files
            # or releasing the concurrency slot, including Windows file handles.
            if process.pid is not None:
                if process.is_alive():
                    process.kill()
                process.join()
                process.close()


async def parse_preview(content, filename):
    # threading semaphore is shared across TestClient/event loops as well as
    # requests; don't bind an asyncio semaphore to the first request's loop.
    while not _PARSE_SLOTS.acquire(blocking=False):
        await asyncio.sleep(.02)
    try:
        task = asyncio.create_task(asyncio.to_thread(_supervise, content, filename))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Keep the slot until the supervisor kills/reaps its child. Repeated
            # cancellation must not allow abandoned workers to exceed the cap.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            raise
    finally:
        _PARSE_SLOTS.release()
