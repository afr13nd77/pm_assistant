import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


def _atomic_write(filepath: str | Path, content: str) -> None:
    filepath = Path(filepath)
    tmp_path = filepath.with_suffix(".tmp")
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(str(tmp_path), str(filepath))


class PipelineStage(str, Enum):
    PENDING = "pending"
    ANALYST_IN_PROGRESS = "analyst_in_progress"
    ANALYST_DONE = "analyst_done"
    PM_IN_PROGRESS = "pm_in_progress"
    PM_DONE = "pm_done"
    DECOMPOSER_IN_PROGRESS = "decomposer_in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PipelineRun:
    pipeline_id: str
    slug: str
    stage: PipelineStage = PipelineStage.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    vault_dir: str = ""
    domain: str = "general"
    error: str | None = None
    failed_stage: str | None = None
    artifacts: list[str] = field(default_factory=list)
    input_type: str = "text"
    started_from: str = "analyst"

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "slug": self.slug,
            "stage": self.stage.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "vault_dir": self.vault_dir,
            "domain": self.domain,
            "error": self.error,
            "failed_stage": self.failed_stage,
            "artifacts": list(self.artifacts),
            "input_type": self.input_type,
            "started_from": self.started_from,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineRun":
        return cls(
            pipeline_id=data["pipeline_id"],
            slug=data["slug"],
            stage=PipelineStage(data["stage"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            vault_dir=data.get("vault_dir", ""),
            domain=data.get("domain", "general"),
            error=data.get("error"),
            failed_stage=data.get("failed_stage"),
            artifacts=data.get("artifacts", []),
            input_type=data.get("input_type", "text"),
            started_from=data.get("started_from", "analyst"),
        )


class PipelineStore:
    def __init__(self) -> None:
        self._runs: dict[str, PipelineRun] = {}

    def create(
        self,
        slug: str,
        input_type: str = "text",
        started_from: str = "analyst",
        vault_dir: str = "",
        domain: str = "general",
    ) -> PipelineRun:
        pipeline_id = str(uuid.uuid4())
        now = datetime.now()
        run = PipelineRun(
            pipeline_id=pipeline_id,
            slug=slug,
            stage=PipelineStage.PENDING,
            created_at=now,
            updated_at=now,
            vault_dir=vault_dir,
            domain=domain,
            input_type=input_type,
            started_from=started_from,
        )
        self._runs[pipeline_id] = run
        logger.info(
            "Pipeline %s created: slug=%s, domain=%s, input_type=%s, started_from=%s",
            pipeline_id,
            slug,
            domain,
            input_type,
            started_from,
        )
        return run

    def get(self, pipeline_id: str) -> PipelineRun | None:
        return self._runs.get(pipeline_id)

    def update_stage(self, pipeline_id: str, stage: PipelineStage) -> PipelineRun:
        run = self._runs[pipeline_id]
        old_stage = run.stage
        run.stage = stage
        run.updated_at = datetime.now()
        logger.info(
            "Pipeline %s: stage %s -> %s",
            pipeline_id,
            old_stage.value,
            stage.value,
        )
        return run

    def set_error(
        self, pipeline_id: str, error: str, failed_stage: str
    ) -> PipelineRun:
        run = self._runs[pipeline_id]
        old_stage = run.stage
        run.stage = PipelineStage.FAILED
        run.error = error
        run.failed_stage = failed_stage
        run.updated_at = datetime.now()
        logger.error(
            "Pipeline %s: stage %s -> failed (failed_stage=%s, error=%s)",
            pipeline_id,
            old_stage.value,
            failed_stage,
            error,
        )
        return run

    def add_artifact(self, pipeline_id: str, artifact_name: str) -> PipelineRun:
        run = self._runs[pipeline_id]
        run.artifacts.append(artifact_name)
        run.updated_at = datetime.now()
        logger.info(
            "Pipeline %s: artifact added '%s' (total=%d)",
            pipeline_id,
            artifact_name,
            len(run.artifacts),
        )
        return run

    def list_runs(
        self, limit: int = 20, status_filter: str | None = None
    ) -> list[PipelineRun]:
        runs = list(self._runs.values())
        if status_filter is not None:
            runs = [r for r in runs if r.stage.value == status_filter]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def save_state_file(self, pipeline_id: str, vault_dir: Path) -> None:
        run = self._runs[pipeline_id]
        state_path = vault_dir / "_state.json"
        _atomic_write(
            state_path,
            json.dumps(run.to_dict(), ensure_ascii=False, indent=2),
        )
        logger.info(
            "Pipeline %s: state saved to %s",
            pipeline_id,
            state_path,
        )

    @staticmethod
    def load_state_file(vault_dir: Path) -> "PipelineRun | None":
        state_path = vault_dir / "_state.json"
        if not state_path.exists():
            logger.warning("State file not found at %s", state_path)
            return None
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            run = PipelineRun.from_dict(data)
            logger.info(
                "Pipeline %s: state loaded from %s (stage=%s)",
                run.pipeline_id,
                state_path,
                run.stage.value,
            )
            return run
        except Exception as exc:
            logger.error(
                "Failed to load state file %s: %s", state_path, exc, exc_info=True
            )
            return None
