from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent_loop import AgentLoop
from .idea_extractor import extract_ideas
from .quality_gate import QualityGate
from .signal_memory import SignalMemory, SignalRecord
from .signal_moderator import (
    AnalysisResult,
    ScoringResult,
    _write_processed_md,
    _write_skipped_md,
    analyze_signal,
    dispatch_idea,
    dispatch_report,
    score_signal,
)
from shared import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Langfuse helpers (BL-190)
# ---------------------------------------------------------------------------


def _safe_span(trace, name: str, **kwargs):
    """Create Langfuse span, return None if unavailable."""
    if trace is None:
        return None
    try:
        return trace.span(name=name, **kwargs)
    except Exception as e:
        logger.warning(f"Langfuse span creation failed: {e}")
        return None


def _safe_end_span(span, **kwargs):
    """End Langfuse span, silently ignore errors."""
    if span is None:
        return
    try:
        span.end(**kwargs)
    except Exception as e:
        logger.warning(f"Langfuse span end failed: {e}")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ModeratorConfig:
    """Конфигурация из settings.yaml секции 'moderator'. 20 полей."""

    relevance_threshold: int = 7
    max_items_per_run: int = 20
    report_auto_launch: bool = True
    report_method: str = "cowork"
    idea_auto_create: bool = True
    cooldown_hours: int = 24
    max_retries: int = 3
    escalation_group: str = "signal_escalation"
    quality_threshold: int = 6
    memory_db_path: str = "/data/signal_memory.db"
    memory_cleanup_days: int = 180
    trend_detection_lookback_weeks: int = 4
    trend_spike_threshold: int = 3
    dedup_similarity_threshold: int = 8
    dedup_related_threshold: int = 6
    completeness_threshold: int = 6
    domain_auto_correct: bool = True
    report_wait_timeout_minutes: int = 30
    pending_report_poll_interval: int = 5
    persist_run_state: bool = True


def load_config_from_settings() -> ModeratorConfig:
    """Загрузить ModeratorConfig из shared.settings."""
    config = ModeratorConfig()
    mod_settings = settings.get("moderator", {})
    if isinstance(mod_settings, dict):
        for key, value in mod_settings.items():
            if hasattr(config, key):
                setattr(config, key, value)
    logger.info(
        f"ModeratorConfig loaded: threshold={config.relevance_threshold}, "
        f"max_items={config.max_items_per_run}"
    )
    return config


# ---------------------------------------------------------------------------
# Run State (AC-34, AC-35, AC-47)
# ---------------------------------------------------------------------------


@dataclass
class ItemState:
    """Состояние обработки одного item (AC-47).

    Допустимые статусы:
    pending | scoring | analyzing | dispatching | waiting_report |
    extracting | completed | failed | skipped
    """

    title: str
    status: str = "pending"
    current_step: str = ""
    result_ref: str | None = None
    iterations: int = 0
    errors: list[str] = field(default_factory=list)
    quality_warnings: list[str] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    iterations_history: list[dict] = field(default_factory=list)
    gate_results: list[dict] = field(default_factory=list)
    reaction: str | None = None


@dataclass
class RunSummary:
    """Агрегированные метрики прогона."""

    total: int = 0
    relevant: int = 0
    ideas: int = 0
    reports: int = 0
    retries: int = 0
    errors: int = 0
    quality_warnings: int = 0


@dataclass
class RunState:
    """Состояние прогона (AC-34, AC-35)."""

    run_id: str  # 'YYYY-MM-DD-HHMM'
    digest_path: str
    started_at: str
    status: str = "running"  # 'running' | 'completed' | 'failed'
    completed_at: str | None = None
    items: dict[str, ItemState] = field(default_factory=dict)
    summary: RunSummary | None = None

    def persist(self, vault_path: str) -> None:
        """Сохранить в wiki/signals/runs/{run_id}.json."""
        runs_dir = Path(vault_path) / "wiki" / "signals" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{self.run_id}.json"
        data = asdict(self)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"RunState persisted: {path}")

    @classmethod
    def load(cls, run_file: Path) -> RunState:
        """Загрузить из файла."""
        data = json.loads(run_file.read_text(encoding="utf-8"))
        items: dict[str, ItemState] = {}
        for key, item_data in data.get("items", {}).items():
            known_fields = {
                k: v for k, v in item_data.items()
                if k in ItemState.__dataclass_fields__
            }
            items[key] = ItemState(**known_fields)
        summary = None
        if data.get("summary"):
            summary = RunSummary(**data["summary"])
        return cls(
            run_id=data["run_id"],
            digest_path=data["digest_path"],
            started_at=data["started_at"],
            status=data.get("status", "running"),
            completed_at=data.get("completed_at"),
            items=items,
            summary=summary,
        )

    @classmethod
    def new(cls, digest_path: str) -> RunState:
        """Создать новый RunState."""
        now = datetime.now()
        return cls(
            run_id=now.strftime("%Y-%m-%d-%H%M"),
            digest_path=digest_path,
            started_at=now.isoformat(),
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class SignalOrchestrator:
    """Координатор полного pipeline обработки новостного дайджеста.

    Связывает модули score -> analyze -> quality gate -> dispatch
    через AgentLoop с retry-with-critique.
    """

    def __init__(self, vault_path: str, config: ModeratorConfig):
        self.vault_path = vault_path
        self.config = config
        self.memory = SignalMemory(config.memory_db_path)
        self.gate = QualityGate(vault_path, config)
        self.run_state: RunState | None = None
        self._business_context: str | None = None
        self._trace = None  # Langfuse trace (BL-190)
        logger.info(f"SignalOrchestrator initialized, vault={vault_path}")

    # ------------------------------------------------------------------
    # Public entry point (FLOW-01)
    # ------------------------------------------------------------------

    def process_digest(
        self,
        digest_path: str | None = None,
        notify: bool = False,
        dry_run: bool = False,
    ) -> RunState:
        """Основная точка входа (FLOW-01).

        1. Если digest_path is None: auto-detect latest из raw/inbound/news/
        2. Загрузить JSON, валидировать контракт (AC-43)
        3. Проверить resume: resume_if_needed()
        4. Создать RunState.new(), зарегистрировать items
        5. Для каждого item (до config.max_items_per_run): _process_item()
        6. _finalize(notify, dry_run)
        7. Persist RunState
        """
        logger.info(
            f"process_digest: starting, path={digest_path}, "
            f"notify={notify}, dry_run={dry_run}"
        )

        # 1. Auto-detect or use provided path
        if digest_path is None:
            digest_path = self._auto_detect_digest()
        if digest_path is None:
            logger.info("process_digest: no digest available, nothing to process")
            self.run_state = RunState.new("none")
            self.run_state.status = "completed"
            self.run_state.completed_at = datetime.now().isoformat()
            self.run_state.summary = RunSummary(
                total=0, relevant=0, ideas=0,
                reports=0, retries=0, errors=0, quality_warnings=0,
            )
            return self.run_state

        # 2. Load and validate (AC-43)
        path = Path(digest_path)
        if not path.exists():
            path = Path(self.vault_path) / digest_path
        if not path.exists():
            raise FileNotFoundError(f"Digest file not found: {digest_path}")

        digest = json.loads(path.read_text(encoding="utf-8"))
        items = digest.get("items", [])
        digest_date = digest.get("date", datetime.now().strftime("%Y-%m-%d"))
        digest_source = digest.get("source", "unknown")

        # Validate required fields per AC-43
        if not items:
            logger.warning("process_digest: empty items in digest")

        for idx, item in enumerate(items):
            if "title" not in item or "summary" not in item:
                logger.warning(
                    f"process_digest: item[{idx}] missing title or summary: "
                    f"{json.dumps(item, ensure_ascii=False)[:120]}"
                )

        # 3. Check resume (AC-35)
        resumed = self.resume_if_needed()
        if resumed:
            self.run_state = resumed
            logger.info(f"process_digest: resumed run {resumed.run_id}")
        else:
            # 4. Create new RunState
            self.run_state = RunState.new(str(path))
            logger.info(f"process_digest: created new run {self.run_state.run_id}")

        # BL-190: Langfuse trace
        from shared.langfuse_client import get_langfuse

        lf = get_langfuse()
        trace = None
        if lf:
            try:
                trace = lf.trace(
                    name=f"signal-moderator/{self.run_state.run_id}",
                    session_id=self.run_state.run_id,
                    metadata={
                        "run_id": self.run_state.run_id,
                        "digest_path": str(path),
                        "total_items": len(items),
                    },
                    tags=["signal-moderator"],
                )
                logger.info(
                    f"Langfuse trace created: "
                    f"signal-moderator/{self.run_state.run_id}"
                )
            except Exception:
                logger.warning(
                    "Langfuse trace creation failed, "
                    "continuing without tracing"
                )
        else:
            logger.info("Langfuse unavailable, tracing disabled")
        self._trace = trace

        # Register items (limited by max_items_per_run)
        capped_items = items[: self.config.max_items_per_run]
        for item in capped_items:
            item_key = hashlib.md5(
                item.get("title", "").encode()
            ).hexdigest()[:8]
            if item_key not in self.run_state.items:
                self.run_state.items[item_key] = ItemState(
                    title=item.get("title", "")
                )
            # Enrich item with digest-level metadata
            item.setdefault("date", digest_date)
            item.setdefault("source", digest_source)

        # 5. Process each item
        processed_items: list[dict] = []
        skipped_items: list[dict] = []

        for item in capped_items:
            item_key = hashlib.md5(
                item.get("title", "").encode()
            ).hexdigest()[:8]
            item_state = self.run_state.items.get(item_key)

            # Skip already completed items (resume scenario)
            if item_state and item_state.status in ("completed", "skipped"):
                logger.info(
                    f"Skipping already processed item: "
                    f"{item.get('title', '')[:50]}"
                )
                continue

            try:
                self._process_item(
                    item, item_key, notify, dry_run,
                    processed_items, skipped_items,
                    trace=trace,
                )
            except Exception as e:
                logger.error(
                    f"Error processing item "
                    f"'{item.get('title', '')[:50]}': {e}"
                )
                if item_state:
                    item_state.status = "failed"
                    item_state.errors.append(str(e))

            # Persist after each item (AC-34)
            if self.config.persist_run_state:
                self.run_state.persist(self.vault_path)

        # Write batch files (AC-04, AC-45)
        if skipped_items:
            _write_skipped_md(self.vault_path, digest_date, skipped_items)
        if processed_items:
            _write_processed_md(self.vault_path, digest_date, processed_items)

        # 6. Finalize (AC-33)
        self._finalize(notify, dry_run)

        # 7. Final persist
        self.run_state.persist(self.vault_path)

        logger.info(
            f"process_digest: completed, run_id={self.run_state.run_id}"
        )
        return self.run_state

    # ------------------------------------------------------------------
    # Item processing (FLOW-01, steps 3a-3f)
    # ------------------------------------------------------------------

    def _process_item(
        self,
        item: dict,
        item_key: str,
        notify: bool,
        dry_run: bool,
        processed_items: list[dict],
        skipped_items: list[dict],
        trace=None,
    ) -> None:
        """Обработка одного item через полный pipeline."""
        item_state = self.run_state.items[item_key]
        item_state.started_at = datetime.now().isoformat()
        title = item.get("title", "")[:50]
        logger.info(f"Processing item: {title}")

        # BL-190: Item-level span
        item_span = _safe_span(
            trace, f"item:{item_key}", metadata={"title": title}
        )

        # --- Step 1: Scoring (AC-01..AC-03) ---
        item_state.status = "scoring"
        item_state.current_step = "score_signal"

        business_context = self._load_business_context()
        memory_context = ""

        score_span = _safe_span(item_span, f"score:{item_key}")
        scoring = score_signal(
            item, business_context, memory_context, self.config
        )
        _safe_end_span(score_span, metadata={
            "relevance": scoring.relevance,
            "decision": (
                "continue"
                if scoring.relevance >= self.config.relevance_threshold
                else "skip"
            ),
        })
        logger.info(f"Item '{title}': relevance={scoring.relevance}")

        # --- Step 2: Threshold check ---
        if scoring.relevance < self.config.relevance_threshold:
            item_state.status = "skipped"
            item_state.reaction = "skip"  # BL-190
            item_state.completed_at = datetime.now().isoformat()
            skipped_items.append({
                "title": item.get("title", ""),
                "relevance": scoring.relevance,
                "reason": scoring.reason,
            })
            self.memory.record_signal(SignalRecord(
                date=item.get("date", datetime.now().strftime("%Y-%m-%d")),
                title=item.get("title", ""),
                summary=item.get("summary"),
                source=item.get("source"),
                source_url=item.get("source_url"),
                relevance=scoring.relevance,
                reaction="skip",
                entities=scoring.matched_entities,
            ))
            logger.info(
                f"Item '{title}': skipped (relevance "
                f"{scoring.relevance} < {self.config.relevance_threshold})"
            )
            _safe_end_span(item_span, metadata={
                "status": item_state.status,
                "reaction": item_state.reaction,
            })
            return

        # --- Step 3: Analysis with AgentLoop (AC-17..AC-19) ---
        item_state.status = "analyzing"
        item_state.current_step = "analyze_signal"

        competitor_profile = None
        competitor_name = ""
        for entity in scoring.matched_entities:
            profile = self._load_competitor_profile(entity)
            if profile:
                competitor_profile = profile
                competitor_name = entity
                break

        memory_history = ""
        for entity in scoring.matched_entities:
            hist = self.memory.get_entity_history(
                entity, weeks=self.config.trend_detection_lookback_weeks
            )
            if hist:
                memory_history += hist + "\n"

        loop = AgentLoop(max_iterations=self.config.max_retries)

        def step_fn(**kwargs: Any) -> dict:
            result = analyze_signal(
                item=item,
                scoring=scoring,
                business_context=business_context,
                competitor_profile=competitor_profile,
                memory_history=memory_history,
                config=self.config,
                critique=kwargs.get("critique"),
                operation_group=kwargs.get("operation_group"),
            )
            return result.__dict__

        analyze_span = _safe_span(item_span, f"analyze:{item_key}")
        analysis_dict, loop_history = loop.run(
            step_fn=step_fn,
            quality_fn=self.gate.check_analysis_quality,
            escalation_group=self.config.escalation_group,
        )
        _safe_end_span(analyze_span, metadata={
            "iterations": len(loop_history),
            "quality_score": (
                loop_history[-1].quality.score
                if loop_history
                and hasattr(loop_history[-1].quality, "score")
                else 0
            ),
            "escalated": any(it.escalated for it in loop_history),
        })

        # BL-190: Record iterations_history
        for iteration in loop_history:
            item_state.iterations_history.append({
                "attempt": iteration.attempt,
                "quality_score": (
                    iteration.quality.score
                    if hasattr(iteration.quality, "score")
                    else 0
                ),
                "critique": iteration.critique_text,
                "escalated": iteration.escalated,
                "operation": (
                    "signal_analyze_escalation"
                    if iteration.escalated
                    else "signal_analyze"
                ),
            })

        # BL-190: Record quality gate result from last iteration
        if loop_history:
            last_q = loop_history[-1].quality
            item_state.gate_results.append({
                "gate": "quality",
                "passed": (
                    last_q.passed if hasattr(last_q, "passed") else False
                ),
                "score": (
                    last_q.score if hasattr(last_q, "score") else 0
                ),
                "failed_criteria": (
                    last_q.issues if hasattr(last_q, "issues") else []
                ),
            })

        # Reconstruct AnalysisResult from dict (filter private keys for ctor)
        ctor_keys = {
            "reaction", "analysis", "threat_level",
            "idea_draft", "report_brief",
        }
        analysis = AnalysisResult(
            **{k: v for k, v in analysis_dict.items() if k in ctor_keys}
        )
        if analysis_dict.get("_quality_warning"):
            analysis._quality_warning = True
            item_state.quality_warnings.append(
                "analysis quality below threshold"
            )
        analysis._attempts = len(loop_history)
        item_state.iterations = len(loop_history)

        # BL-190: Record reaction
        item_state.reaction = analysis.reaction

        # --- Step 4: Domain auto-correction (AC-23) ---
        if analysis.idea_draft:
            is_correct, suggested = self.gate.check_domain(analysis.idea_draft)
            if not is_correct and suggested:
                logger.info(
                    f"Domain auto-corrected: "
                    f"{analysis.idea_draft.get('domain')} -> {suggested}"
                )
                analysis.idea_draft["domain"] = suggested

        # --- Step 5: Dispatch ---
        item_state.status = "dispatching"
        item_state.current_step = f"dispatch_{analysis.reaction}"

        # BL-190: Gate span wraps dispatch decisions
        gate_span = _safe_span(item_span, f"gate:{item_key}")

        if analysis.reaction == "idea":
            self._handle_idea(item, analysis, item_state, notify, dry_run)
        elif analysis.reaction == "report":
            self._handle_report(
                item, analysis, item_state, notify, dry_run,
                competitor=competitor_name,
            )

        _safe_end_span(gate_span, metadata={
            "gates": [g["gate"] for g in item_state.gate_results],
            "all_passed": all(
                g["passed"] for g in item_state.gate_results
            ),
        })

        # BL-190: Dispatch span
        dispatch_span = _safe_span(item_span, f"dispatch:{item_key}", metadata={
            "reaction": item_state.reaction,
            "result_ref": item_state.result_ref,
        })
        _safe_end_span(dispatch_span)

        # --- Step 6: Record in memory ---
        quality_scores = [
            h.quality.score
            for h in loop_history
            if hasattr(h.quality, "score")
        ]
        best_quality = max(quality_scores) if quality_scores else 0

        self.memory.record_signal(SignalRecord(
            date=item.get("date", datetime.now().strftime("%Y-%m-%d")),
            title=item.get("title", ""),
            summary=item.get("summary"),
            source=item.get("source"),
            source_url=item.get("source_url"),
            relevance=scoring.relevance,
            reaction=analysis.reaction,
            result_ref=item_state.result_ref,
            entities=scoring.matched_entities,
            quality_score=best_quality,
            attempts=len(loop_history),
        ))

        # --- Step 7: Complete ---
        if item_state.status != "waiting_report":
            item_state.status = "completed"
        item_state.completed_at = datetime.now().isoformat()

        processed_items.append({
            "title": item.get("title", ""),
            "reaction": analysis.reaction,
            "result_ref": item_state.result_ref or "",
            "quality_score": best_quality,
        })

        # BL-190: End item span
        _safe_end_span(item_span, metadata={
            "status": item_state.status,
            "reaction": item_state.reaction,
        })

        logger.info(
            f"Item '{title}': {analysis.reaction}, "
            f"ref={item_state.result_ref}"
        )

    # ------------------------------------------------------------------
    # Idea dispatch (FLOW-03)
    # ------------------------------------------------------------------

    def _handle_idea(
        self,
        item: dict,
        analysis: AnalysisResult,
        item_state: ItemState,
        notify: bool,
        dry_run: bool,
    ) -> None:
        """FLOW-03: dedup -> quality check -> domain check -> write."""
        if not analysis.idea_draft:
            logger.warning("_handle_idea: no idea_draft in analysis")
            return

        # 1. Dedup check (AC-20)
        dedup_result = self.gate.check_dedup(analysis.idea_draft)

        # BL-190: Record dedup gate result
        item_state.gate_results.append({
            "gate": "dedup",
            "passed": not dedup_result.is_duplicate,
            "similarity": dedup_result.similarity,
            "compared_with": dedup_result.similar_to,
        })

        if dedup_result.is_duplicate:
            logger.info(
                f"Idea duplicate detected: similar_to={dedup_result.similar_to}, "
                f"similarity={dedup_result.similarity}"
            )
            item_state.quality_warnings.append(
                f"duplicate of {dedup_result.similar_to}"
            )
            if dedup_result.similarity >= self.config.dedup_similarity_threshold:
                item_state.status = "skipped"
                return

        # 2. Idea quality check (AC-21)
        quality = self.gate.check_idea_quality(analysis.idea_draft)
        if not quality.passed and quality.improvements:
            if quality.improvements.get("improved_title"):
                analysis.idea_draft["title"] = quality.improvements[
                    "improved_title"
                ]
            if quality.improvements.get("improved_solution"):
                analysis.idea_draft["solution"] = quality.improvements[
                    "improved_solution"
                ]

        # 3. Dispatch (AC-08, AC-10, AC-30)
        if self.config.idea_auto_create:
            dedup_for_dispatch = None
            if dedup_result.similarity >= self.config.dedup_related_threshold:
                dedup_for_dispatch = dedup_result
            ref = dispatch_idea(
                item=item,
                analysis=analysis,
                vault_path=self.vault_path,
                notify=notify,
                dry_run=dry_run,
                dedup_result=dedup_for_dispatch,
            )
            item_state.result_ref = ref
            logger.info(f"_handle_idea: dispatched, ref={ref}")

    # ------------------------------------------------------------------
    # Report dispatch (FLOW-04)
    # ------------------------------------------------------------------

    def _handle_report(
        self,
        item: dict,
        analysis: AnalysisResult,
        item_state: ItemState,
        notify: bool,
        dry_run: bool,
        competitor: str = "",
    ) -> None:
        """FLOW-04: create research queue JSON (AC-07, AC-31)."""
        if self.config.report_auto_launch:
            ref = dispatch_report(
                item=item,
                analysis=analysis,
                vault_path=self.vault_path,
                notify=notify,
                dry_run=dry_run,
                competitor=competitor,
            )
            item_state.result_ref = ref
            logger.info(f"_handle_report: dispatched, ref={ref}")
        item_state.status = "waiting_report"

    # ------------------------------------------------------------------
    # Resume (AC-35)
    # ------------------------------------------------------------------

    def resume_if_needed(self) -> RunState | None:
        """Проверить wiki/signals/runs/ на незавершённые прогоны."""
        logger.info("resume_if_needed: checking for incomplete runs")
        runs_dir = Path(self.vault_path) / "wiki" / "signals" / "runs"
        if not runs_dir.exists():
            logger.info("resume_if_needed: runs directory does not exist")
            return None

        run_files = sorted(runs_dir.glob("*.json"), reverse=True)
        for run_file in run_files:
            try:
                state = RunState.load(run_file)
                if state.status == "completed":
                    continue
                # Check if not too old (< 24 hours)
                started = datetime.fromisoformat(state.started_at)
                age_hours = (datetime.now() - started).total_seconds() / 3600
                if age_hours < 24:
                    logger.info(
                        f"Found incomplete run: {state.run_id}, "
                        f"status={state.status}, age={age_hours:.1f}h"
                    )
                    return state
                logger.info(
                    f"Skipping stale run: {state.run_id}, age={age_hours:.1f}h"
                )
            except Exception as e:
                logger.warning(
                    f"Error loading run state {run_file}: {e}"
                )

        logger.info("resume_if_needed: no incomplete runs found")
        return None

    # ------------------------------------------------------------------
    # Pending reports (FLOW-04, steps 5-9)
    # ------------------------------------------------------------------

    def check_pending_reports(self) -> None:
        """Проверить готовность отчётов и извлечь идеи."""
        logger.info("check_pending_reports: starting")
        if not self.run_state:
            logger.info("check_pending_reports: no active run_state")
            return

        business_context = self._load_business_context()

        for item_key, item_state in self.run_state.items.items():
            if item_state.status != "waiting_report":
                continue

            reports_dir = Path(self.vault_path) / "wiki" / "reports"
            if not reports_dir.exists():
                logger.info(
                    f"check_pending_reports: reports dir does not exist"
                )
                continue

            # Match report by title slug
            title_slug = re.sub(
                r"[^a-zA-Za-zA-Z0-9]", "-", item_state.title
            )[:30].lower()
            matching = list(reports_dir.glob(f"*{title_slug}*"))

            if not matching:
                logger.info(
                    f"check_pending_reports: no report found for "
                    f"'{item_state.title[:40]}'"
                )
                continue

            report_path = matching[0]
            item_state.status = "extracting"
            item_state.current_step = "extract_ideas"
            logger.info(
                f"check_pending_reports: processing report {report_path.name}"
            )

            # Extract ideas (AC-38)
            ideas = extract_ideas(
                report_path=report_path,
                vault_path=self.vault_path,
                business_context=business_context,
                config=self.config,
            )

            # Dispatch each extracted idea
            for idea in ideas:
                dedup = self.gate.check_dedup(idea)
                if not dedup.is_duplicate:
                    analysis = AnalysisResult(
                        reaction="idea",
                        analysis=idea.get("rationale", ""),
                        idea_draft=idea,
                    )
                    dedup_for_dispatch = None
                    if dedup.similarity >= self.config.dedup_related_threshold:
                        dedup_for_dispatch = dedup
                    dispatch_idea(
                        item={
                            "title": item_state.title,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                        },
                        analysis=analysis,
                        vault_path=self.vault_path,
                        notify=True,
                        dry_run=False,
                        dedup_result=dedup_for_dispatch,
                    )

            item_state.status = "completed"
            item_state.completed_at = datetime.now().isoformat()
            logger.info(
                f"Pending report processed: {item_state.title[:40]}, "
                f"{len(ideas)} ideas extracted"
            )

    # ------------------------------------------------------------------
    # Finalize (AC-33)
    # ------------------------------------------------------------------

    def _finalize(self, notify: bool, dry_run: bool) -> None:
        """Финализация прогона: вычислить summary, отправить Telegram."""
        if not self.run_state:
            logger.warning("_finalize: no run_state")
            return

        # Compute summary
        all_items = list(self.run_state.items.values())
        summary = RunSummary(
            total=len(all_items),
            relevant=sum(
                1 for i in all_items if i.status not in ("skipped",)
            ),
            ideas=sum(
                1 for i in all_items
                if i.result_ref and "ideas" in str(i.result_ref)
            ),
            reports=sum(
                1 for i in all_items if i.status == "waiting_report"
            ),
            retries=sum(max(0, i.iterations - 1) for i in all_items),
            errors=sum(1 for i in all_items if i.status == "failed"),
            quality_warnings=sum(
                1 for i in all_items if i.quality_warnings
            ),
        )
        self.run_state.summary = summary
        self.run_state.status = "completed"
        self.run_state.completed_at = datetime.now().isoformat()  # BL-190

        # BL-190: Finalize Langfuse trace
        if hasattr(self, "_trace") and self._trace:
            try:
                summary_data = (
                    asdict(self.run_state.summary)
                    if self.run_state.summary
                    else {}
                )
                self._trace.update(
                    output={
                        "status": self.run_state.status,
                        **summary_data,
                    },
                )
            except Exception:
                logger.warning("Langfuse trace finalize failed")

        logger.info(
            f"Run {self.run_state.run_id} finalized: "
            f"total={summary.total}, relevant={summary.relevant}, "
            f"ideas={summary.ideas}, reports={summary.reports}, "
            f"retries={summary.retries}, errors={summary.errors}"
        )

        # Telegram summary notification (AC-33)
        if notify and not dry_run:
            try:
                from app.notifier import send_telegram

                msg = (
                    f"Moderator run completed\n"
                    f"Total: {summary.total}\n"
                    f"Relevant: {summary.relevant}\n"
                    f"Ideas: {summary.ideas}\n"
                    f"Reports: {summary.reports}\n"
                    f"Retries: {summary.retries}\n"
                    f"Errors: {summary.errors}"
                )
                send_telegram(msg, parse_mode=None)
                logger.info("_finalize: Telegram summary sent")
            except Exception as e:
                logger.warning(
                    f"_finalize: Telegram summary notification failed: {e}"
                )

    # ------------------------------------------------------------------
    # Context loaders
    # ------------------------------------------------------------------

    def _load_business_context(self) -> str:
        """Прочитать wiki/concepts/business-context-brief.md (кэш per run)."""
        if self._business_context is not None:
            return self._business_context

        path = (
            Path(self.vault_path)
            / "wiki"
            / "concepts"
            / "business-context-brief.md"
        )
        if not path.exists():
            logger.warning(f"Business context not found: {path}")
            self._business_context = ""
            return ""

        content = path.read_text(encoding="utf-8")
        # Strip frontmatter
        content = re.sub(
            r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL
        )
        self._business_context = content.strip()
        logger.info(
            f"Business context loaded: {len(self._business_context)} chars"
        )
        return self._business_context

    def _load_competitor_profile(self, entity: str) -> str | None:
        """Прочитать wiki/reports/Competitor-Info-{entity}.md."""
        path = (
            Path(self.vault_path)
            / "wiki"
            / "reports"
            / f"Competitor-Info-{entity}.md"
        )
        if not path.exists():
            logger.info(f"No competitor profile for entity: {entity}")
            return None
        try:
            content = path.read_text(encoding="utf-8")
            content = re.sub(
                r"^---\s*\n.*?\n---\s*\n",
                "",
                content,
                count=1,
                flags=re.DOTALL,
            )
            logger.info(f"Competitor profile loaded: {entity}")
            return content.strip()
        except Exception as e:
            logger.warning(
                f"Failed to load competitor profile for {entity}: {e}"
            )
            return None

    def _auto_detect_digest(self) -> str:
        """Найти последний файл в raw/inbound/news/*.json."""
        logger.info("_auto_detect_digest: scanning raw/inbound/news/")
        news_dir = Path(self.vault_path) / "raw" / "inbound" / "news"
        if not news_dir.exists():
            logger.info(f"_auto_detect_digest: news directory not found: {news_dir}")
            return None

        json_files = sorted(news_dir.glob("*.json"), reverse=True)
        if not json_files:
            logger.info(f"_auto_detect_digest: no digest files in {news_dir}")
            return None

        logger.info(f"Auto-detected digest: {json_files[0]}")
        return str(json_files[0])
