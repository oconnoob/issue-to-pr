"""Requeue one failed/uncertain delivery AFTER reconciling DO executions.

Run from the project root: python -m scripts.retry_delivery ...
"""

import argparse
from uuid import UUID

from relay.config import Settings
from relay.delivery import Inbox


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delivery", type=UUID)
    parser.add_argument("--confirmed-no-execution", action="store_true", required=True,
                        help="Confirm you checked trigger executions and no run was accepted")
    args = parser.parse_args()
    inbox = None
    try:
        inbox = Inbox(Settings.database_from_env())
        print(f"Requeued {inbox.retry(str(args.delivery))} delivery")
    except Exception:
        parser.exit(1, "Retry failed; check database configuration/connectivity privately.\n")
    finally:
        if inbox is not None:
            inbox.close()


if __name__ == "__main__":
    main()
