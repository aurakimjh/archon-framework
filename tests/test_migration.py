"""SchemaMigrator 테스트."""

from __future__ import annotations

import pytest

from src.migration.schema_migrator import (
    CURRENT_VERSION,
    MigrationError,
    MigrationStep,
    SchemaMigrator,
    get_migrator,
)


def _make_v100_data(handoff_id: str = "hf-001") -> dict:
    return {
        "envelope": {
            "handoff_id": handoff_id,
            "schema_version": "1.0.0",
            "from_agent": "backend",
            "to_agent": "reviewer",
        },
        "quality_gates": {
            "test_results": {"passed": 10, "failed": 0},
        },
    }


def _make_v110_data(handoff_id: str = "hf-001") -> dict:
    data = _make_v100_data(handoff_id)
    data["envelope"]["schema_version"] = "1.1.0"
    data["quality_gates"]["sop_compliance_score"] = None
    return data


class TestSchemaMigrator:
    def test_upgrade_v100_to_v110(self):
        m = SchemaMigrator()
        result = m.migrate(_make_v100_data(), "1.1.0")
        assert result["envelope"]["schema_version"] == "1.1.0"
        assert "sop_compliance_score" in result["quality_gates"]

    def test_same_version_returns_as_is(self):
        m = SchemaMigrator()
        data = _make_v100_data()
        result = m.migrate(data, "1.0.0")
        assert result is data  # 동일 객체

    def test_migrate_to_latest(self):
        m = SchemaMigrator()
        result = m.migrate_to_latest(_make_v100_data())
        assert result["envelope"]["schema_version"] == CURRENT_VERSION

    def test_downgrade_v110_to_v100(self):
        m = SchemaMigrator()
        result = m.rollback(_make_v110_data(), "1.0.0")
        assert result["envelope"]["schema_version"] == "1.0.0"
        assert "sop_compliance_score" not in result["quality_gates"]

    def test_no_path_raises(self):
        m = SchemaMigrator()
        data = _make_v100_data()
        with pytest.raises(MigrationError, match="No migration path"):
            m.migrate(data, "9.9.9")

    def test_missing_schema_version_raises(self):
        m = SchemaMigrator()
        with pytest.raises(MigrationError, match="schema_version"):
            m.migrate({"envelope": {}}, "1.1.0")

    def test_original_data_not_mutated(self):
        m = SchemaMigrator()
        original = _make_v100_data()
        original_copy = {
            "envelope": dict(original["envelope"]),
            "quality_gates": dict(original["quality_gates"]),
        }
        m.migrate(original, "1.1.0")
        assert original["envelope"]["schema_version"] == original_copy["envelope"]["schema_version"]

    def test_custom_migration_step(self):
        m = SchemaMigrator()

        def up(data: dict) -> dict:
            import json
            d = json.loads(json.dumps(data))
            d["envelope"]["schema_version"] = "1.2.0"
            d["new_field"] = "added"
            return d

        def down(data: dict) -> dict:
            import json
            d = json.loads(json.dumps(data))
            d["envelope"]["schema_version"] = "1.1.0"
            d.pop("new_field", None)
            return d

        m.register(MigrationStep("1.1.0", "1.2.0", upgrade=up, downgrade=down))
        result = m.migrate(_make_v100_data(), "1.2.0")
        assert result["envelope"]["schema_version"] == "1.2.0"
        assert result["new_field"] == "added"

    def test_get_migrator_singleton(self):
        m1 = get_migrator()
        m2 = get_migrator()
        assert m1 is m2
