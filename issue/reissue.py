from __future__ import annotations

from issue.registry import IssueRegistry
from source.day import require_name


def reissue(registry: IssueRegistry, artifact_id: str) -> bytes | None:
    require_name(artifact_id, 'artifact id')
    return registry.load_frozen(artifact_id)
