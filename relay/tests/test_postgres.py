"""Real PostgreSQL: distinct receiver/worker sessions and rolling replacements."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import httpx
import psycopg
import pytest

from relay.config import Settings
from relay.delivery import Inbox, Worker

EXECUTION = str(uuid4())
CANDIDATE = {"payload": {"issue": {"number": 7}}}


@pytest.fixture
def inboxes(postgres_url):
    opened = []

    def open_inbox():
        inbox = Inbox(postgres_url)
        assert inbox.postgres
        opened.append(inbox)
        return inbox

    yield open_inbox
    for inbox in opened:
        inbox.close()


def worker(inbox, client, source=None):
    class Trusted:
        async def authorized(self, candidate):
            return True

    settings = Settings("demo/project", "github-secret", "lookup-token",
                        "https://example.com/trigger", "trigger-secret",
                        database=inbox.database)
    return Worker(settings, inbox, {"github": source or Trusted()}, client)


def state(inbox, delivery):
    return inbox.db.execute("SELECT * FROM deliveries WHERE delivery=%s", (delivery,)).fetchone()


def terminate(inbox, postgres_url):
    pid = inbox.leader_db.info.backend_pid
    with psycopg.connect(postgres_url, autocommit=True) as db:
        assert db.execute("SELECT pg_terminate_backend(%s, 1000)", (pid,)).fetchone()[0]


def test_concurrent_first_boot_and_independent_receivers(postgres_url):
    # Concurrent CREATE TABLE IF NOT EXISTS alone can race on PostgreSQL catalogs.
    with ThreadPoolExecutor(max_workers=4) as pool:
        inboxes = list(pool.map(lambda _: Inbox(postgres_url), range(4)))
    try:
        delivery = str(uuid4())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda box: box.enqueue("github", delivery, CANDIDATE), inboxes))
        assert results.count(True) == 1
        assert results.count(False) == 3
    finally:
        for inbox in inboxes:
            inbox.close()


def test_overlap_during_post_does_not_recover_active_send(inboxes):
    leader, standby = inboxes(), inboxes()
    delivery = str(uuid4())
    leader.enqueue("github", delivery, CANDIDATE)
    calls = []

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def remote(request):
            calls.append(request)
            entered.set()
            await release.wait()
            return httpx.Response(202, json={"execution_id": EXECUTION})

        async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
            first, second = worker(leader, client), worker(standby, client)
            sending = asyncio.create_task(first.process_one())
            await asyncio.wait_for(entered.wait(), 2)
            assert state(standby, delivery)["status"] == "sending"
            assert not await second.process_one()
            standby.health()  # Healthy during rollout even though it cannot lead.
            assert state(standby, delivery)["status"] == "sending"
            release.set()
            assert await sending
            leader.close()
            async with asyncio.timeout(2):
                while not standby.leading:
                    assert not await second.process_one()  # Nothing to replay.
                    await asyncio.sleep(0.01)
            assert standby.leading
            assert state(standby, delivery)["status"] == "forwarded"
            assert not standby.enqueue("github", delivery, CANDIDATE)

    asyncio.run(exercise())
    assert len(calls) == 1


def test_new_leader_recovers_only_interrupted_sends(inboxes, postgres_url):
    leader, standby = inboxes(), inboxes()
    interrupted, pending = str(uuid4()), str(uuid4())
    leader.enqueue("github", interrupted, CANDIDATE)
    assert leader.ensure_leader()
    leader.update(leader.next(), "sending")
    standby.enqueue("github", pending, CANDIDATE)
    assert not standby.ensure_leader()
    terminate(leader, postgres_url)  # A process/connection crash releases the lock.
    assert standby.ensure_leader()
    assert state(standby, interrupted)["status"] == "uncertain"
    assert state(standby, interrupted)["reason"] == "restart_during_send"
    assert standby.next()["delivery"] == pending
    assert not standby.enqueue("github", interrupted, CANDIDATE)


def test_lost_leadership_during_authorization_never_posts(inboxes, postgres_url, caplog):
    leader, standby = inboxes(), inboxes()
    delivery = str(uuid4())
    leader.enqueue("github", delivery, CANDIDATE)
    calls = []

    class SlowAuthorization:
        async def authorized(self, candidate):
            terminate(leader, postgres_url)
            assert standby.ensure_leader()
            return True

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(202)
        )) as client:
            task = asyncio.create_task(worker(leader, client, SlowAuthorization()).run())
            await asyncio.wait_for(task, 2)
            assert task.done()
            assert state(standby, delivery)["status"] == "pending"
            assert not calls

    asyncio.run(exercise())
    assert "worker_stopped" in caplog.text


def test_connection_loss_after_acceptance_never_automatically_replays(inboxes, postgres_url):
    leader, standby = inboxes(), inboxes()
    delivery = str(uuid4())
    leader.enqueue("github", delivery, CANDIDATE)
    calls = []

    async def remote(request):
        calls.append(request)  # Simulate acceptance followed by database loss.
        terminate(leader, postgres_url)
        assert standby.ensure_leader()
        return httpx.Response(202, json={"execution_id": EXECUTION})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
            await asyncio.wait_for(worker(leader, client).run(), 2)
            assert not await worker(standby, client).process_one()
            assert state(standby, delivery)["status"] == "uncertain"
            assert len(calls) == 1

    asyncio.run(exercise())


def test_retry_module_uses_postgres_and_requires_reconciliation(postgres_url, inboxes):
    inbox = inboxes()
    delivery = str(uuid4())
    inbox.enqueue("github", delivery, CANDIDATE)
    inbox.update(inbox.next(), "uncertain", "trigger_transport_error")
    env = os.environ | {"DATABASE_URL": postgres_url}
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "scripts.retry_delivery", delivery]
    missing = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    assert missing.returncode == 2
    assert state(inbox, delivery)["status"] == "uncertain"
    retry = subprocess.run(command + ["--confirmed-no-execution"], cwd=root, env=env,
                           capture_output=True, text=True)
    assert retry.returncode == 0
    assert retry.stdout.strip() == "Requeued 1 delivery"
    assert state(inbox, delivery)["status"] == "pending"
    inbox.update(inbox.next(), "forwarded", execution_id=EXECUTION)
    assert inbox.retry(delivery) == 0


def test_stopped_worker_releases_lock_before_app_shutdown(inboxes):
    leader, standby = inboxes(), inboxes()
    delivery = str(uuid4())
    leader.enqueue("github", delivery, CANDIDATE)

    async def remote(request):
        raise RuntimeError("PRIVATE-TRIGGER-URL")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
            await asyncio.wait_for(worker(leader, client).run(), 2)
            # The receiver remains open; only the dead worker's session closed.
            leader.health()
            assert standby.ensure_leader()
            assert state(standby, delivery)["status"] == "uncertain"
            with pytest.raises(psycopg.OperationalError):
                leader.ensure_leader()  # Former leaders never reconnect silently.

    asyncio.run(exercise())


def test_cancel_during_send_releases_leadership_without_replay(inboxes):
    leader, standby = inboxes(), inboxes()
    delivery = str(uuid4())
    leader.enqueue("github", delivery, CANDIDATE)
    calls = []

    async def exercise():
        entered = asyncio.Event()

        async def remote(request):
            calls.append(request)
            entered.set()
            await asyncio.Future()  # The app is terminated while waiting on POST.

        async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
            task = asyncio.create_task(worker(leader, client).run())
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not await worker(standby, client).process_one()
            assert state(standby, delivery)["status"] == "uncertain"
            assert len(calls) == 1

    asyncio.run(exercise())
