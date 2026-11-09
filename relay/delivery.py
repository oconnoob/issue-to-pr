"""One SQLite inbox and one worker. No agent runs in the relay process."""

import asyncio
import hashlib
import hmac
import json
import logging
from pathlib import Path
import sqlite3
import time
from uuid import UUID

import httpx

log = logging.getLogger("relay")


def signature(secret, body, timestamp):
    """DO custom: HMAC over the timestamp, a literal dot, then exact body bytes."""
    digest = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body,
                      hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


class Inbox:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
            source TEXT NOT NULL, delivery TEXT NOT NULL, candidate TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_at REAL NOT NULL DEFAULT 0, reason TEXT, execution_id TEXT,
            PRIMARY KEY (source, delivery))""")
        self.db.commit()

    def enqueue(self, source, delivery, candidate):
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO deliveries (source, delivery, candidate) VALUES (?, ?, ?)",
                (source, delivery, json.dumps(candidate)),
            )
        return bool(cursor.rowcount)

    def update(self, row, status, reason=None, execution_id=None, delay=0):
        with self.db:
            self.db.execute("""UPDATE deliveries SET status=?, reason=?, execution_id=?,
                next_at=? WHERE source=? AND delivery=?""",
                (status, reason, execution_id, time.time() + delay, row["source"], row["delivery"]))

    def recover(self):
        # A crash after POST may have created an execution. Never blindly send twice.
        interrupted = self.db.execute(
            "SELECT source, delivery FROM deliveries WHERE status='sending'").fetchall()
        with self.db:
            self.db.execute("""UPDATE deliveries SET status='uncertain', reason='restart_during_send'
                WHERE status='sending'""")
        for row in interrupted:
            log.warning("source=%s delivery=%s decision=uncertain reason=restart_during_send",
                        row["source"], row["delivery"])

    def next(self):
        return self.db.execute("""SELECT * FROM deliveries WHERE status='pending'
            AND next_at <= ? ORDER BY rowid LIMIT 1""", (time.time(),)).fetchone()


class Worker:
    def __init__(self, settings, inbox, sources, client):
        self.settings, self.inbox, self.sources, self.client = settings, inbox, sources, client

    def finish(self, row, status, reason, execution_id=None):
        self.inbox.update(row, status, reason, execution_id)
        log.info("source=%s delivery=%s decision=%s reason=%s execution=%s",
                 row["source"], row["delivery"], status, reason, execution_id or "-")

    async def process_one(self):
        row = self.inbox.next()
        if row is None:
            return False
        candidate = json.loads(row["candidate"])
        try:
            allowed = await self.sources[row["source"]].authorized(candidate)
        except httpx.HTTPError:
            # Authorization GET is safe to retry; errors never grant permission.
            attempts = row["attempts"] + 1
            with self.inbox.db:
                self.inbox.db.execute("UPDATE deliveries SET attempts=? WHERE source=? AND delivery=?",
                                      (attempts, row["source"], row["delivery"]))
            self.inbox.update(row, "pending" if attempts < 5 else "failed",
                              "authorization_unavailable", delay=min(60, 2 ** attempts))
            log.warning("source=%s delivery=%s decision=%s reason=authorization_unavailable",
                        row["source"], row["delivery"], "retry" if attempts < 5 else "failed")
            return True
        if not allowed:
            self.finish(row, "skipped", "untrusted_author_and_labeler")
            return True
        body = json.dumps(candidate["payload"], separators=(",", ":"), ensure_ascii=False).encode()
        self.inbox.update(row, "sending")
        try:
            response = await self.client.post(
                self.settings.trigger_url, content=body,
                headers={"Content-Type": "application/json",
                         "X-DigitalOcean-Signature": signature(
                             self.settings.trigger_secret, body, int(time.time()))},
            )
        except httpx.RequestError:
            self.finish(row, "uncertain", "trigger_transport_error")
            return True
        if response.status_code != 202:
            # A 5xx may occur after acceptance. Reconcile before replaying.
            self.finish(row, "uncertain" if response.status_code >= 500 else "failed",
                        f"trigger_http_{response.status_code}")
            return True
        try:
            execution = response.json().get("execution_id")
            execution = str(UUID(execution))
        except (ValueError, TypeError, AttributeError):
            # Paused triggers return 202 without an execution. Do not report success.
            self.finish(row, "uncertain", "no_execution_id_check_trigger_status")
            return True
        self.finish(row, "forwarded", "trigger_accepted", execution)
        return True

    async def run(self):
        try:
            while True:
                if not await self.process_one():
                    await asyncio.sleep(0.5)
        except Exception as error:
            # Avoid exception text that could contain a credential-bearing URL.
            log.error("decision=worker_stopped reason=%s", type(error).__name__)
            # Completing the task makes /healthz fail without an unsafe traceback.
            return
