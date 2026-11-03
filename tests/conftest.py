import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

from app import engine, store  # noqa: E402


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory):
    """The synthetic QQQ-DEMO / SPY-DEMO data set, generated once per test run."""
    import synthetic
    d = tmp_path_factory.mktemp("synthetic")
    old = store.DATA_DIR
    synthetic.generate(d)
    store.DATA_DIR = old
    return d


@pytest.fixture
def demo(synthetic_dir, monkeypatch):
    """Point the cache at the synthetic data set for one test."""
    monkeypatch.setattr(store, "DATA_DIR", synthetic_dir)
    engine._summary_cache.clear()
    engine._tf_cache.clear()
    return synthetic_dir


@pytest.fixture
def paper_runner():
    """Start the separate runner explicitly after a test selects its DATA_DIR; join before fixture teardown."""
    import threading
    from app.paper import worker
    running = []

    def start(workers=5):
        stop, ready = threading.Event(), threading.Event()
        errors = []

        def target():
            try:
                worker.run(stop, workers=workers, poll_seconds=0.01, ready=ready)
            except Exception as e:
                errors.append(e)
        thread = threading.Thread(target=target)
        thread.start()
        running.append((stop, thread, errors))
        assert ready.wait(5), errors
        return stop
    yield start
    for stop, thread, errors in running:
        stop.set()
        thread.join(10)
        assert not thread.is_alive(), "paper runner did not stop"
        assert not errors, errors
