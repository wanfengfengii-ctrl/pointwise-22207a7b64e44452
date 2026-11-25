from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from balance.posting import post_artifact
from balance.store import open_report_database
from intake.envelope import decode_envelope
from intake.receipts import Receipt, insert_receipt, lookup_receipt, same_artifact
from intake.validate import validate_artifact
from source.store import write_transaction


def accept(db: sqlite3.Connection, payload: bytes) -> Receipt:
    """Commit one delivery and its visible effect, or return its existing receipt."""
    artifact = decode_envelope(payload)
    validate_artifact(artifact)
    with write_transaction(db):
        previous = lookup_receipt(db, artifact.artifact_id)
        if previous is not None:
            if not same_artifact(previous, artifact):
                raise ValueError('receipt artifact identity conflict')
            return previous
        receipt = insert_receipt(db, artifact)
        post_artifact(db, artifact)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Receive a frozen packet in the reporting warehouse')
    parser.add_argument('database')
    parser.add_argument('packet', type=Path)
    args = parser.parse_args(argv)
    try:
        payload = args.packet.read_bytes()
        with closing(open_report_database(args.database)) as db:
            receipt = accept(db, payload)
        print(json.dumps({'number': receipt.number, 'artifact_id': receipt.artifact_id}))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
