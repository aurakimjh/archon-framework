"""HandoffArtifact v1.0.0 → v1.1.0 마이그레이션.

변경 사항:
- quality_gates에 sop_compliance_score 필드 추가 (None = 미검사)
- envelope.schema_version 갱신
"""

from __future__ import annotations


def upgrade(data: dict) -> dict:
    """v1.0.0 → v1.1.0 업그레이드."""
    data = _deep_copy(data)
    data["envelope"]["schema_version"] = "1.1.0"

    qg = data.setdefault("quality_gates", {})
    qg.setdefault("sop_compliance_score", None)

    return data


def downgrade(data: dict) -> dict:
    """v1.1.0 → v1.0.0 롤백."""
    data = _deep_copy(data)
    data["envelope"]["schema_version"] = "1.0.0"

    qg = data.get("quality_gates", {})
    qg.pop("sop_compliance_score", None)

    return data


def _deep_copy(obj: dict) -> dict:
    import json
    return json.loads(json.dumps(obj))
