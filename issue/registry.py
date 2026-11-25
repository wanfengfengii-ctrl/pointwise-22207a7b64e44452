from __future__ import annotations

import sqlite3
from os import PathLike

from source.store import write_transaction

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS issued_artifacts (
    artifact_id TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    payload BLOB NOT NULL
)
'''


class IssueRegistry:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def close(self) -> None:
        self._db.close()

    def lookup_request(self, artifact_id: str, request: str | None = None) -> bytes | None:
        saved = self._db.execute(
            'SELECT request, payload FROM issued_artifacts WHERE artifact_id = ?', (artifact_id,)
        ).fetchone()
        if saved is None:
            return None
        original_request, payload = saved
        if request is not None and request != original_request:
            raise ValueError('issue request identity conflict')
        return payload

    def register_issue(self, artifact_id: str, request: str, payload: bytes) -> bytes:
        with write_transaction(self._db):
            saved = self.lookup_request(artifact_id, request)
            if saved is not None:
                return saved
            self._db.execute(
                'INSERT INTO issued_artifacts (artifact_id, request, payload) VALUES (?, ?, ?)',
                (artifact_id, request, payload),
            )
        return payload

    def load_frozen(self, artifact_id: str) -> bytes | None:
        return self.lookup_request(artifact_id)


def open_issue_registry(path: str | PathLike[str]) -> IssueRegistry:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute(_SCHEMA)
    except BaseException:
        db.close()
        raise
    return IssueRegistry(db)
