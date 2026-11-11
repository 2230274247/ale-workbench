"""Real spawn workers: deadline, reaping, event-loop responsiveness and cap."""
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import time

import pytest
from app import import_worker as worker


def slow_worker(content, filename, result_path):
    Path(filename).write_text(str(os.getpid()))
    time.sleep(30)


def crashed_worker(content, filename, result_path):
    os._exit(7)


def timed_worker(content, filename, result_path):
    started = time.monotonic()
    time.sleep(.2)
    ended = time.monotonic()
    Path(result_path).write_text(json.dumps({'status': 'original_only', 'blocks': [],
        'warnings': [], 'blocking_issues': [], 'interval': [started, ended]}))


def test_spawn_timeout_reaps_child_and_keeps_loop_responsive(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, '_parse_worker', slow_worker)
    monkeypatch.setattr(worker, 'PARSE_TIMEOUT_SECONDS', 1.5)
    before = {p.pid for p in multiprocessing.active_children()}
    async def run():
        task = asyncio.create_task(worker.parse_preview(b'raw', str(tmp_path / 'pid')))
        ticks = 0
        while not task.done():
            ticks += 1
            await asyncio.sleep(.02)
        assert ticks >= 10
        return await task
    result = asyncio.run(run())
    assert result['status'] == 'original_only' and result['blocks'] == []
    assert result['blocking_issues'][0]['code'] == 'parser_timeout'
    assert 'seconds' in result['blocking_issues'][0]['message']
    assert (tmp_path / 'pid').exists(), 'Spawn child never started'
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_spawn_crash_returns_explicit_failure(monkeypatch):
    monkeypatch.setattr(worker, '_parse_worker', crashed_worker)
    result = asyncio.run(worker.parse_preview(b'raw', 'raw.dat'))
    assert result['blocking_issues'][0]['code'] == 'parser_worker_failed'
    assert result['blocks'] == []


def test_real_spawn_concurrency_cap(monkeypatch):
    monkeypatch.setattr(worker, '_parse_worker', timed_worker)
    async def run():
        return await asyncio.gather(*(worker.parse_preview(b'x', f'{i}.dat') for i in range(5)))
    results = asyncio.run(run())
    events = sorted((moment, delta) for r in results
                    for moment, delta in [(r['interval'][0], 1), (r['interval'][1], -1)])
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    assert peak == 2 and active == 0


def test_cancelled_request_waits_for_child_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, '_parse_worker', slow_worker)
    monkeypatch.setattr(worker, 'PARSE_TIMEOUT_SECONDS', 1.5)
    before = {p.pid for p in multiprocessing.active_children()}
    async def run():
        task = asyncio.create_task(worker.parse_preview(b'raw', str(tmp_path / 'pid')))
        await asyncio.sleep(.2)
        task.cancel()
        await asyncio.sleep(.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert {p.pid for p in multiprocessing.active_children()} == before
    assert worker._PARSE_SLOTS.acquire(blocking=False)
    assert worker._PARSE_SLOTS.acquire(blocking=False)
    assert not worker._PARSE_SLOTS.acquire(blocking=False)
    worker._PARSE_SLOTS.release()
    worker._PARSE_SLOTS.release()
