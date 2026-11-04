"""Global job limit, durable queue and deletion that stops work before removing its report."""
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import control, jsonfile, store
from app.paper import backtest, fetching, jobs, worker
from test_paper_backtest import cross_rule, save_cross_strategy


def wait_for(fn, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition not reached before timeout")


@pytest.fixture
def cache(tmp_path, synthetic_dir, monkeypatch):
    import shutil
    shutil.copytree(synthetic_dir / "bars", tmp_path / "bars")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def submit(name="Crosses", symbol="QQQ-DEMO", days=2, baseline_runs=0):
    have = store.list_days(symbol)
    return jobs.start(save_cross_strategy(), name, symbol, have[0], have[days - 1], "skip", 100_000,
                      {"commission": {"per_share": 0, "minimum": 0, "max_pct": 1}, "slippage": 0}, baseline_runs)


def api():
    from app.server import app
    return TestClient(app, client=("192.168.1.20", 50000))


def test_five_jobs_overlap_and_sixth_waits_and_deletion_frees_slot(cache, monkeypatch, paper_runner):
    gate = threading.Event()
    entered, exited = [], []
    guard = threading.Lock()

    def slow(*args, check, **kw):
        with guard:
            entered.append(threading.current_thread().name)
        try:
            while not gate.wait(0.01):
                check()
            return {"stats": {"trades": 0, "total": 0}}
        finally:
            exited.append(threading.current_thread().name)
    monkeypatch.setattr(backtest, "run", slow)
    runs = [submit(str(i)) for i in range(12)]
    paper_runner()
    wait_for(lambda: len(entered) == 5)
    assert sum(r["status"] == "queued" for r in jobs.listing()) == 7
    victim = next(r for r in jobs.listing() if r["status"] == "running")
    response = api().delete(f"/api/paper/backtests/{victim['id']}")
    assert response.status_code == 202 and response.json()["deleting"]
    wait_for(lambda: not jobs.path(victim["id"]).exists())
    assert len(exited) == 1
    wait_for(lambda: len(entered) == 6)
    assert len(entered) - len(exited) == 5
    gate.set()
    wait_for(lambda: all(r["status"] == "done" for r in jobs.listing()))
    assert len(jobs.listing()) == len(runs) - 1
    assert not jobs.path(victim["id"]).exists()


def test_delete_queued_never_executes_and_queue_capacity_is_atomic(cache, monkeypatch, paper_runner):
    monkeypatch.setattr(jobs, "MAX_QUEUED", 2)
    first, second = submit(), submit()
    with pytest.raises(jobs.QueueFull):
        submit()
    assert api().delete(f"/api/paper/backtests/{first['id']}").status_code == 200
    calls = []
    monkeypatch.setattr(backtest, "run", lambda *a, **k: calls.append(1) or {"stats": {"trades": 0, "total": 0}})
    paper_runner()
    wait_for(lambda: jobs.read(second["id"])["status"] == "done")
    assert calls == [1]
    with pytest.raises(jobs.Cancelled):
        jobs._write(first["id"], status="done")
    assert not jobs.path(first["id"]).exists()


def test_delete_wins_over_inflight_progress_and_completion(cache, monkeypatch, paper_runner):
    entered, release = threading.Event(), threading.Event()

    def finishes(*args, progress, **kw):
        entered.set()
        assert release.wait(5)
        progress(1, 1)   # delete must win even if this write occurs before the throttled cancellation check
        return {"stats": {"trades": 0, "total": 0}}
    monkeypatch.setattr(backtest, "run", finishes)
    run = submit()
    paper_runner()
    assert entered.wait(5)
    assert not jobs.delete(run["id"])
    assert jobs.read(run["id"])["status"] == "deleting"
    release.set()
    wait_for(lambda: not jobs.path(run["id"]).exists())
    assert api().get(f"/api/paper/backtests/{run['id']}").status_code == 404


def test_delete_wins_over_worker_exception(cache, monkeypatch, paper_runner):
    entered, release = threading.Event(), threading.Event()

    def fails(*args, **kw):
        entered.set()
        assert release.wait(5)
        raise RuntimeError("failure racing with deletion")
    monkeypatch.setattr(backtest, "run", fails)
    run = submit()
    paper_runner()
    assert entered.wait(5)
    assert not jobs.delete(run["id"])
    release.set()
    wait_for(lambda: not jobs.path(run["id"]).exists())


def test_delete_fetching_stops_before_backtest(cache, monkeypatch, paper_runner):
    control.write_status({"connected": True})
    monkeypatch.setattr(fetching, "POLL_SECONDS", 0.01)
    called = []
    monkeypatch.setattr(backtest, "run", lambda *a, **k: called.append(1))
    rule = save_cross_strategy()
    run = jobs.start(rule, "Fetch", "UNCACHED", "2026-10-19", "2026-10-23", "fetch", 100_000, {}, 0)
    paper_runner()
    wait_for(lambda: control.pending_requests())
    assert not jobs.delete(run["id"])
    wait_for(lambda: not jobs.path(run["id"]).exists())
    assert not called


def test_real_results_are_identical_across_five_threads(cache):
    have = store.list_days("QQQ-DEMO")[:3]
    rule = cross_rule()
    settings = {"commission": {"per_share": 0, "minimum": 0, "max_pct": 1}, "slippage": 0}
    expected = backtest.run(rule, "QQQ-DEMO", have, 100_000, settings, baseline_runs=2)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(backtest.run, rule, "QQQ-DEMO", have, 100_000, settings, baseline_runs=2) for _ in range(5)]
        assert all(f.result() == expected for f in futures)


def test_cancellation_inside_day_and_baseline(cache, monkeypatch):
    have = store.list_days("QQQ-DEMO")[:1]
    steps = []
    original = backtest.engine.step

    def step(*a, **kw):
        steps.append(1)
        return original(*a, **kw)

    def check():
        if len(steps) >= 3:
            raise jobs.Cancelled()
    monkeypatch.setattr(backtest.engine, "step", step)
    with pytest.raises(jobs.Cancelled):
        backtest.run(cross_rule(), "QQQ-DEMO", have, 100_000, {}, check=check)
    assert len(steps) == 3
    # A cancellation requested as the random entries start stops them inside the day: no later run, no progress.
    count, baselines = [], []
    cancelled = threading.Event()
    picks = backtest._random_entries

    def random_entries(*a):
        baselines.append(1)
        cancelled.set()
        return picks(*a)

    def baseline_check():
        if cancelled.is_set():
            raise jobs.Cancelled()
    monkeypatch.setattr(backtest, "_random_entries", random_entries)
    with pytest.raises(jobs.Cancelled):
        backtest.run(cross_rule(), "QQQ-DEMO", have, 100_000, {}, baseline_runs=5,
                     progress=lambda done, total: count.append(done), check=baseline_check)
    assert baselines == [1] and count == []


def test_restart_preserves_queue_interrupts_old_runs_and_finishes_deletions(cache, monkeypatch, paper_runner):
    queued, old, deleting = submit(), submit(), submit()
    jobs._write(old["id"], status="running")
    with jsonfile.editing(jobs.path(deleting["id"])) as d:
        d.update(status="deleting", delete_requested=True)
    monkeypatch.setattr(backtest, "run", lambda *a, **k: {"stats": {"trades": 0, "total": 0}})
    paper_runner()
    wait_for(lambda: jobs.read(queued["id"])["status"] == "done")
    assert jobs.read(old["id"])["status"] == "interrupted"
    assert not jobs.path(deleting["id"]).exists()


def test_shutdown_interrupts_active_and_preserves_waiting(cache, monkeypatch, paper_runner):
    def slow(*a, check, **kw):
        while True:
            check()
            time.sleep(0.01)
    monkeypatch.setattr(backtest, "run", slow)
    first, second = submit(), submit()
    stop = paper_runner(workers=1)
    wait_for(lambda: jobs.read(first["id"])["status"] == "running")
    stop.set()
    wait_for(lambda: jobs.read(first["id"])["status"] == "interrupted")
    assert jobs.read(second["id"])["status"] == "queued"


def _second_runner(data, result):
    store.DATA_DIR = data
    try:
        worker.run(threading.Event(), poll_seconds=0.01)
    except BlockingIOError:
        result.put("locked")


def _delete_from_other_process(data, run_id, result):
    store.DATA_DIR = data
    result.put(jobs.delete(run_id))


def test_singleton_and_delete_work_across_processes(cache, monkeypatch, paper_runner):
    def slow(*a, check, **kw):
        while True:
            check()
            time.sleep(0.01)
    monkeypatch.setattr(backtest, "run", slow)
    run = submit()
    paper_runner()
    wait_for(lambda: jobs.read(run["id"])["status"] == "running")
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Queue()
    for target, args, expected in ((_second_runner, (cache, result), "locked"),
                                   (_delete_from_other_process, (cache, run["id"], result), False)):
        p = ctx.Process(target=target, args=args)
        p.start()
        try:
            assert result.get(timeout=10) == expected
            p.join(5)
            assert p.exitcode == 0
        finally:
            if p.is_alive():
                p.kill()
                p.join()
    wait_for(lambda: not jobs.path(run["id"]).exists())


def test_invalid_worker_count():
    for n in (0, 6):
        with pytest.raises(ValueError, match="between 1 and 5"):
            worker.run(threading.Event(), workers=n)


def _submit_from_web_process(data, result):
    store.DATA_DIR = data
    jobs.MAX_QUEUED = 4
    accepted = 0
    for _ in range(6):
        try:
            submit()
            accepted += 1
        except jobs.QueueFull:
            pass
    result.put(accepted)


def test_two_web_processes_share_one_bounded_queue(cache):
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Queue()
    processes = [ctx.Process(target=_submit_from_web_process, args=(cache, result)) for _ in range(2)]
    for p in processes:
        p.start()
    try:
        assert sum(result.get(timeout=20) for _ in processes) == 4
        for p in processes:
            p.join(5)
            assert p.exitcode == 0
        assert len(jobs.queued()) == 4
    finally:
        for p in processes:
            if p.is_alive():
                p.kill()
                p.join()


def test_delete_after_final_write_before_execution_lock_release(cache):
    run = submit()
    with jsonfile.locked(jobs.execution_path(run["id"])):
        jobs._write(run["id"], status="done", report={})
        assert jobs.delete(run["id"])
    assert not jobs.path(run["id"]).exists()


def test_api_queue_full_is_retryable(cache, monkeypatch):
    monkeypatch.setattr(jobs, "MAX_QUEUED", 1)
    first = submit()
    r = api().post("/api/paper/backtests", json={"strategy": save_cross_strategy(), "symbol": "QQQ-DEMO",
                   "start": first["start"], "end": first["end"], "missing": "skip"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "5"
    assert len(jobs.queued()) == 1
