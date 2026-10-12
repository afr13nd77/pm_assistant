"""Тесты для idea_pipeline.app.state (BL-178, T-01)."""
import json
from datetime import datetime, timedelta

import pytest

from idea_pipeline.state import (
    PipelineRun,
    PipelineStage,
    PipelineStore,
    _atomic_write,
)


@pytest.fixture
def store():
    return PipelineStore()


class TestPipelineStage:
    def test_all_values(self):
        assert {s.name: s.value for s in PipelineStage} == {
            "PENDING": "pending",
            "ANALYST_IN_PROGRESS": "analyst_in_progress",
            "ANALYST_DONE": "analyst_done",
            "PM_IN_PROGRESS": "pm_in_progress",
            "PM_DONE": "pm_done",
            "DECOMPOSER_IN_PROGRESS": "decomposer_in_progress",
            "COMPLETED": "completed",
            "FAILED": "failed",
        }

    def test_is_str_enum(self):
        assert PipelineStage.PENDING == "pending"
        assert PipelineStage("completed") is PipelineStage.COMPLETED

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            PipelineStage("unknown")


class TestPipelineRun:
    def test_defaults(self):
        run = PipelineRun(pipeline_id="p1", slug="s")
        assert run.stage == PipelineStage.PENDING
        assert run.vault_dir == ""
        assert run.domain == "general"
        assert run.error is None
        assert run.failed_stage is None
        assert run.artifacts == []
        assert run.input_type == "text"
        assert run.started_from == "analyst"
        assert isinstance(run.created_at, datetime)

    def test_artifacts_not_shared(self):
        a = PipelineRun(pipeline_id="a", slug="a")
        b = PipelineRun(pipeline_id="b", slug="b")
        a.artifacts.append("x")
        assert b.artifacts == []

    def test_to_dict(self):
        now = datetime(2026, 1, 2, 3, 4, 5)
        run = PipelineRun(
            pipeline_id="p1",
            slug="s",
            stage=PipelineStage.PM_DONE,
            created_at=now,
            updated_at=now,
            vault_dir="/v",
            domain="d",
            artifacts=["a.md"],
        )
        d = run.to_dict()
        assert d["stage"] == "pm_done"
        assert d["created_at"] == "2026-01-02T03:04:05"
        assert d["artifacts"] == ["a.md"]
        assert d["vault_dir"] == "/v"
        assert d["domain"] == "d"
        assert d["error"] is None
        # to_dict возвращает копию списка
        d["artifacts"].append("z")
        assert run.artifacts == ["a.md"]

    def test_round_trip(self):
        run = PipelineRun(
            pipeline_id="p1",
            slug="s",
            stage=PipelineStage.FAILED,
            error="boom",
            failed_stage="pm",
            artifacts=["a", "b"],
            input_type="url",
            started_from="pm",
            vault_dir="/v",
            domain="dom",
        )
        restored = PipelineRun.from_dict(run.to_dict())
        assert restored == run

    def test_from_dict_defaults(self):
        now = datetime.now().isoformat()
        run = PipelineRun.from_dict(
            {"pipeline_id": "p", "slug": "s", "stage": "pending",
             "created_at": now, "updated_at": now}
        )
        assert run.vault_dir == ""
        assert run.domain == "general"
        assert run.artifacts == []
        assert run.input_type == "text"
        assert run.started_from == "analyst"

    def test_from_dict_missing_required(self):
        with pytest.raises(KeyError):
            PipelineRun.from_dict({"slug": "s"})

    def test_update_fields(self):
        run = PipelineRun(pipeline_id="p", slug="s")
        run.stage = PipelineStage.COMPLETED
        run.error = "e"
        assert run.to_dict()["stage"] == "completed"
        assert run.to_dict()["error"] == "e"


class TestPipelineStore:
    def test_create(self, store):
        run = store.create("my-slug", input_type="url", started_from="pm",
                           vault_dir="/v", domain="dom")
        assert run.slug == "my-slug"
        assert run.stage == PipelineStage.PENDING
        assert run.input_type == "url"
        assert run.started_from == "pm"
        assert run.vault_dir == "/v"
        assert run.domain == "dom"
        assert run.pipeline_id
        assert store.get(run.pipeline_id) is run

    def test_create_unique_ids(self, store):
        assert store.create("a").pipeline_id != store.create("a").pipeline_id

    def test_get_existing_and_missing(self, store):
        run = store.create("a")
        assert store.get(run.pipeline_id) is run
        assert store.get("nope") is None

    def test_update_stage(self, store):
        run = store.create("a")
        before = run.updated_at
        updated = store.update_stage(run.pipeline_id, PipelineStage.ANALYST_DONE)
        assert updated is run
        assert run.stage == PipelineStage.ANALYST_DONE
        assert run.updated_at >= before

    def test_update_stage_missing(self, store):
        with pytest.raises(KeyError):
            store.update_stage("nope", PipelineStage.COMPLETED)

    def test_set_error(self, store):
        run = store.create("a")
        store.update_stage(run.pipeline_id, PipelineStage.PM_IN_PROGRESS)
        store.set_error(run.pipeline_id, "boom", "pm")
        assert run.stage == PipelineStage.FAILED
        assert run.error == "boom"
        assert run.failed_stage == "pm"

    def test_set_error_missing(self, store):
        with pytest.raises(KeyError):
            store.set_error("nope", "e", "s")

    def test_add_artifact(self, store):
        run = store.create("a")
        store.add_artifact(run.pipeline_id, "one.md")
        store.add_artifact(run.pipeline_id, "two.md")
        assert run.artifacts == ["one.md", "two.md"]

    def test_add_artifact_missing(self, store):
        with pytest.raises(KeyError):
            store.add_artifact("nope", "x")

    def test_list_runs_empty(self, store):
        assert store.list_runs() == []

    def test_list_runs_sorted_desc(self, store):
        r1 = store.create("1")
        r2 = store.create("2")
        r3 = store.create("3")
        r1.created_at = datetime(2026, 1, 1)
        r2.created_at = datetime(2026, 1, 2)
        r3.created_at = datetime(2026, 1, 3)
        assert [r.slug for r in store.list_runs()] == ["3", "2", "1"]

    def test_list_runs_limit(self, store):
        base = datetime(2026, 1, 1)
        for i in range(5):
            store.create(str(i)).created_at = base + timedelta(days=i)
        runs = store.list_runs(limit=2)
        assert [r.slug for r in runs] == ["4", "3"]

    def test_list_runs_status_filter(self, store):
        a = store.create("a")
        store.create("b")
        store.update_stage(a.pipeline_id, PipelineStage.COMPLETED)
        res = store.list_runs(status_filter="completed")
        assert [r.slug for r in res] == ["a"]
        assert store.list_runs(status_filter="failed") == []


class TestStateFile:
    def test_round_trip(self, store, tmp_path):
        run = store.create("a", vault_dir=str(tmp_path), domain="dom")
        store.add_artifact(run.pipeline_id, "x.md")
        store.update_stage(run.pipeline_id, PipelineStage.PM_DONE)
        store.save_state_file(run.pipeline_id, tmp_path)

        assert (tmp_path / "_state.json").exists()
        loaded = PipelineStore.load_state_file(tmp_path)
        assert loaded == run

    def test_save_creates_valid_json(self, store, tmp_path):
        run = store.create("тест")
        store.save_state_file(run.pipeline_id, tmp_path / "sub")
        data = json.loads((tmp_path / "sub" / "_state.json").read_text("utf-8"))
        assert data["slug"] == "тест"
        assert not (tmp_path / "sub" / "_state.tmp").exists()

    def test_save_missing_pipeline(self, store, tmp_path):
        with pytest.raises(KeyError):
            store.save_state_file("nope", tmp_path)

    def test_load_missing_file(self, tmp_path):
        assert PipelineStore.load_state_file(tmp_path) is None

    def test_load_corrupt_file(self, tmp_path):
        (tmp_path / "_state.json").write_text("{not json", encoding="utf-8")
        assert PipelineStore.load_state_file(tmp_path) is None

    def test_load_invalid_stage(self, tmp_path):
        now = datetime.now().isoformat()
        (tmp_path / "_state.json").write_text(
            json.dumps({"pipeline_id": "p", "slug": "s", "stage": "bad",
                        "created_at": now, "updated_at": now}),
            encoding="utf-8",
        )
        assert PipelineStore.load_state_file(tmp_path) is None


class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        target = tmp_path / "f.txt"
        _atomic_write(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"
        assert not target.with_suffix(".tmp").exists()

    def test_overwrites(self, tmp_path):
        target = tmp_path / "f.txt"
        _atomic_write(target, "one")
        _atomic_write(str(target), "two")
        assert target.read_text(encoding="utf-8") == "two"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "f.txt"
        _atomic_write(target, "x")
        assert target.read_text(encoding="utf-8") == "x"
