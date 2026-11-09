"""Requeue one failed/uncertain delivery AFTER reconciling DO executions."""

import argparse
import os
import sqlite3
from uuid import UUID

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("delivery", type=UUID)
parser.add_argument("--confirmed-no-execution", action="store_true", required=True,
                    help="Confirm you checked the trigger executions and no run was accepted")
args = parser.parse_args()
with sqlite3.connect(os.environ.get("DATABASE_PATH", "./data/relay.sqlite3")) as db:
    cursor = db.execute("""UPDATE deliveries SET status='pending', attempts=0, next_at=0,
        reason=NULL WHERE source='github' AND delivery=? AND status IN ('failed', 'uncertain')""",
        (str(args.delivery),))
    print(f"Requeued {cursor.rowcount} delivery")
