"""Durable inbox with one forwarding leader. No agent runs in this process."""

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
import psycopg
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict

log = logging.getLogger("relay")


def signature(secret, body, timestamp):
    """DO custom: HMAC over the timestamp, a literal dot, then exact body bytes."""
    digest = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body,
                      hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


# Stable, database-scoped keys; every replica of this relay uses the same lock.
WORKER_LOCK = 716239801
SCHEMA_LOCK = 716239802


class Inbox:
    def __init__(self, database):
        self.database = database
        self.postgres = database.startswith(("postgresql://", "postgres://"))
        self.leader_db = None
        self.leading = False
        if self.postgres:
            self.db = self.connect()
        else:
            Path(database).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(database, timeout=5, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
        try:
            # Serialize first-boot DDL across rolling/parallel app starts.
            with self.db.transaction() if self.postgres else self.db:
                if self.postgres:
                    self.db.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
                self.db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
                    source TEXT NOT NULL, delivery TEXT NOT NULL, candidate TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    next_at DOUBLE PRECISION NOT NULL DEFAULT 0, reason TEXT, execution_id TEXT,
                    PRIMARY KEY (source, delivery))""")
        except BaseException:
            self.db.close()
            raise

    def connect(self):
        # A direct session is required: transaction-pooling proxies cannot hold
        # session advisory locks. Never reconnect a former leader silently.
        options = conninfo_to_dict(self.database).get("options", "")
        return psycopg.connect(self.database, autocommit=True, row_factory=dict_row,
                               connect_timeout=5,
                               options=options + " -c statement_timeout=5000")

    def execute(self, sql, parameters=(), *, worker=False):
        db = self.leader_db if worker and self.postgres else self.db
        if self.postgres:
            return db.execute(sql.replace("?", "%s"), parameters)
        cursor = db.execute(sql, parameters)
        db.commit()
        return cursor

    def ensure_leader(self):
        if self.leading:
            return True
        if self.postgres:
            if self.leader_db is None:
                self.leader_db = self.connect()
            locked = self.leader_db.execute(
                "SELECT pg_try_advisory_lock(%s) AS locked", (WORKER_LOCK,)
            ).fetchone()["locked"]
            if not locked:
                return False
        self.leading = True
        # Only a new leader may classify an interrupted send. A standby starting
        # must not touch a delivery still being sent by the current leader.
        self.recover()
        log.info("decision=worker_leader")
        return True

    def enqueue(self, source, delivery, candidate):
        cursor = self.execute(
            """INSERT INTO deliveries (source, delivery, candidate) VALUES (?, ?, ?)
               ON CONFLICT (source, delivery) DO NOTHING""",
            (source, delivery, json.dumps(candidate)),
        )
        return bool(cursor.rowcount)

    def update(self, row, status, reason=None, execution_id=None, delay=0):
        # The sending marker commits on the session holding the lock. If that
        # session is lost during authorization, this fails before any POST.
        self.execute("""UPDATE deliveries SET status=?, reason=?, execution_id=?,
            next_at=? WHERE source=? AND delivery=?""",
            (status, reason, execution_id, time.time() + delay, row["source"], row["delivery"]),
            worker=self.leading)

    def authorization_failed(self, row):
        attempts = row["attempts"] + 1
        self.execute("UPDATE deliveries SET attempts=? WHERE source=? AND delivery=?",
                     (attempts, row["source"], row["delivery"]), worker=True)
        self.update(row, "pending" if attempts < 5 else "failed",
                    "authorization_unavailable", delay=min(60, 2 ** attempts))
        return attempts

    def recover(self):
        if self.postgres and not self.leading:
            raise RuntimeError("Recovery requires worker leadership")
        interrupted = self.execute(
            "SELECT source, delivery FROM deliveries WHERE status='sending'",
            worker=self.leading).fetchall()
        self.execute("""UPDATE deliveries SET status='uncertain', reason='restart_during_send'
            WHERE status='sending'""", worker=self.leading)
        for row in interrupted:
            log.warning("source=%s delivery=%s decision=uncertain reason=restart_during_send",
                        row["source"], row["delivery"])

    def next(self):
        return self.execute("""SELECT * FROM deliveries WHERE status='pending'
            AND next_at <= ? ORDER BY next_at, source, delivery LIMIT 1""",
            (time.time(),), worker=self.leading).fetchone()

    def retry(self, delivery):
        return self.execute("""UPDATE deliveries SET status='pending', attempts=0, next_at=0,
            reason=NULL, execution_id=NULL WHERE source='github' AND delivery=?
            AND status IN ('failed', 'uncertain')""", (delivery,)).rowcount

    def health(self):
        self.db.execute("SELECT 1")
        if self.leading and self.postgres:
            self.leader_db.execute("SELECT 1")

    def release_leadership(self):
        # Keep the closed connection reference: a former leader cannot reconnect
        # and resume a delivery after another instance has taken over.
        self.leading = False
        if self.leader_db is not None:
            self.leader_db.close()

    def close(self):
        self.release_leadership()
        self.db.close()


class Worker:
    def __init__(self, settings, inbox, sources, client):
        self.settings, self.inbox, self.sources, self.client = settings, inbox, sources, client

    def finish(self, row, status, reason, execution_id=None):
        self.inbox.update(row, status, reason, execution_id)
        log.info("source=%s delivery=%s decision=%s reason=%s execution=%s",
                 row["source"], row["delivery"], status, reason, execution_id or "-")

    async def process_one(self):
        if not self.inbox.ensure_leader():
            return False
        row = self.inbox.next()
        if row is None:
            return False
        candidate = json.loads(row["candidate"])
        try:
            allowed = await self.sources[row["source"]].authorized(candidate)
        except httpx.HTTPError:
            # Authorization GET is safe to retry; errors never grant permission.
            attempts = self.inbox.authorization_failed(row)
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
        finally:
            self.inbox.release_leadership()
