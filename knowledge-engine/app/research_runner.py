from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from shared.file_writer import atomic_write
from shared.frontmatter_utils import read_frontmatter, update_frontmatter
from shared.llm_client import call_detailed
from shared.vault_paths import (
    raw_research_queue,
    raw_research_queue_failed,
    raw_research_queue_processed,
    wiki_reports,
)

from .notifier import send_telegram
from .quality_gate import QualityGate
from .signal_moderator import (
    ScoringResult,
    dispatch_signal,
    extract_signals,
)
from .signal_orchestrator import ModeratorConfig, load_config_from_settings

logger = logging.getLogger(__name__)


@dataclass
class ResearchTask:
    """Single research task parsed from a queue JSON file."""

    topic: str
    questions: list[str]
    scope: str
    signal_source: str = ""
    signal_date: str = ""
    competitor: str = ""
    source_path: Path = Path(".")

    @property
    def slug(self) -> str:
        s = re.sub(r"[^a-zA-Zа-яА-Яё0-9]", "-", self.topic)[:50]
        return re.sub(r"-+", "-", s).strip("-").lower()

    @property
    def report_filename(self) -> str:
        today = date.today().isoformat()
        return f"{today}-{self.slug}.md"


@dataclass
class ResearchResult:
    """Result of processing a single research task."""

    topic: str
    report_path: str | None
    completeness: int
    quality_warning: bool
    ideas_count: int
    tokens_in: int
    tokens_out: int
    method: str
    error: str | None
    outcome: str | None = None  # idea | insight | not_relevant | error | None (BL-198)
    outcome_details: str = ""  # no_ideas_reason or error message, truncated (BL-198)


class ResearchError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_all(
    vault_path: str,
    *,
    method_override: str | None = None,
    notify: bool = False,
    dry_run: bool = False,
    target_file: str | None = None,
) -> list[ResearchResult]:
    """Scan research queue and process all tasks."""
    logger.info(
        f"run_all: starting, vault_path={vault_path}, method_override={method_override}, "
        f"notify={notify}, dry_run={dry_run}, target_file={target_file}"
    )

    try:
        config = load_config_from_settings()
        logger.info("run_all: config loaded successfully")
    except Exception as exc:
        logger.error(f"run_all: failed to load config: {exc}")
        raise

    queue_files = _scan_queue(vault_path, target_file)
    logger.info(f"run_all: found {len(queue_files)} task(s) in queue")

    if not queue_files:
        logger.info("run_all: no tasks to process, returning empty list")
        return []

    method = _resolve_method(config, method_override)
    logger.info(f"run_all: resolved method={method}")

    results: list[ResearchResult] = []
    for task_path in queue_files:
        try:
            task = _parse_task(task_path)
            logger.info(f"run_all: processing task '{task.topic}' from {task_path.name}")
            result = process_task(
                task, vault_path, config,
                method=method, notify=notify, dry_run=dry_run,
            )
            results.append(result)
            logger.info(
                f"run_all: task '{task.topic}' completed, completeness={result.completeness}"
            )
        except Exception as exc:
            logger.error(f"run_all: failed to process {task_path.name}: {exc}")
            results.append(ResearchResult(
                topic=task_path.stem,
                report_path=None,
                completeness=0,
                quality_warning=False,
                ideas_count=0,
                tokens_in=0,
                tokens_out=0,
                method=method,
                error=str(exc),
            ))

    logger.info(
        f"run_all: finished, processed={len(results)}, "
        f"errors={sum(1 for r in results if r.error)}"
    )
    return results


def retry_failed_task(
    filename: str,
    vault_path: str,
) -> list[ResearchResult]:
    """Move a task from failed/ back to queue/ and re-process it."""
    logger.info(f"retry_failed_task: starting, filename={filename}")
    try:
        failed_dir = raw_research_queue_failed()
        queue_dir = raw_research_queue()
        source = failed_dir / filename

        if not source.exists():
            logger.error(f"retry_failed_task: file not found in failed/: {filename}")
            raise FileNotFoundError(f"File not found in failed/: {filename}")

        shutil.move(str(source), str(queue_dir / filename))
        logger.info(f"retry_failed_task: moved {filename} from failed/ to queue/")

        results = run_all(vault_path, target_file=filename)
        logger.info(
            f"retry_failed_task: completed, results={len(results)}, "
            f"errors={sum(1 for r in results if r.error)}"
        )
        return results
    except FileNotFoundError:
        raise
    except Exception as exc:
        logger.error(f"retry_failed_task: unexpected error: {exc}", exc_info=True)
        raise


def process_task(
    task: ResearchTask,
    vault_path: str,
    config: ModeratorConfig,
    *,
    method: str = "internal",
    notify: bool = False,
    dry_run: bool = False,
) -> ResearchResult:
    """Full pipeline for a single research task."""
    logger.info(
        f"process_task: starting, topic='{task.topic}', method={method}, "
        f"dry_run={dry_run}, notify={notify}"
    )

    # 1. Check existing
    existing = _check_existing_report(vault_path, task)
    if existing:
        logger.info(f"process_task: report already exists: {existing}")
        if not dry_run:
            _move_task_file(task.source_path, "processed", vault_path)

        # Read frontmatter to check if outcome was already computed (BL-200 / BUG-030)
        try:
            meta, _ = read_frontmatter(existing)
            logger.info(
                f"process_task: existing report frontmatter read, "
                f"outcome={meta.get('outcome')}, completeness={meta.get('completeness')}"
            )
        except Exception as exc:
            logger.error(f"process_task: failed to read frontmatter from {existing}: {exc}")
            meta = {}

        existing_outcome = meta.get("outcome")

        if existing_outcome is not None:
            # Outcome already computed — return early with real values
            logger.info(
                f"process_task: existing report has outcome={existing_outcome}, "
                f"returning cached result"
            )
            return ResearchResult(
                topic=task.topic,
                report_path=str(existing),
                completeness=meta.get("completeness", 0),
                quality_warning=False,
                ideas_count=meta.get("ideas_count", 0),
                tokens_in=0,
                tokens_out=0,
                method=method,
                error=None,
                outcome=existing_outcome,
                outcome_details=meta.get("outcome_details", ""),
            )

        # Outcome is None — previous run crashed before step 8a, recompute (BL-200)
        logger.warning(
            "process_task: existing report has outcome=None, "
            "running _extract_and_classify to recover"
        )
        outcome, outcome_details, ideas_count, ideas_refs = _extract_and_classify(
            report_path=existing,
            task=task,
            vault_path=vault_path,
            config=config,
        )
        logger.info(
            f"process_task: recovery classification done, outcome={outcome}, "
            f"ideas_count={ideas_count}"
        )
        return ResearchResult(
            topic=task.topic,
            report_path=str(existing),
            completeness=meta.get("completeness", 0),
            quality_warning=False,
            ideas_count=ideas_count,
            tokens_in=0,
            tokens_out=0,
            method=method,
            error=None,
            outcome=outcome,
            outcome_details=outcome_details,
        )

    # 2. Notify start
    if notify:
        logger.info(f"process_task: sending start notification for '{task.topic}'")
        send_telegram(
            f"Исследование запущено: {task.topic} (метод: {method})",
            parse_mode=None,
        )

    # 3. Collect context
    context = _collect_context(vault_path, task)
    logger.info(f"process_task: context collected, keys={list(context.keys())}")

    # 4. Generate report
    content, tokens_in, tokens_out = _generate_internal_report(task, context, config)
    logger.info(
        f"process_task: report generated, len={len(content)}, "
        f"tokens_in={tokens_in}, tokens_out={tokens_out}"
    )

    # 5. Completeness check
    score, quality_warning, unanswered = _run_completeness_check(
        content, task.questions, vault_path, config,
    )
    logger.info(
        f"process_task: completeness score={score}, "
        f"quality_warning={quality_warning}, unanswered={unanswered}"
    )

    # 6. Retry if completeness below threshold
    min_score = config.completeness_threshold  # default 6 from settings.yaml
    retry_score = min(4, min_score)  # retry trigger, at most 4

    if score < retry_score:
        if score < 2:
            # 6a. Catastrophic quality — full regeneration (discard garbage)
            logger.warning(
                f"process_task: catastrophic quality (score={score}), "
                f"full regeneration"
            )
            content, t_in_r, t_out_r = _generate_internal_report(
                task, context, config,
            )
            tokens_in += t_in_r
            tokens_out += t_out_r
            score, quality_warning, unanswered = _run_completeness_check(
                content, task.questions, vault_path, config,
            )
            logger.info(
                f"process_task: after regeneration score={score}, "
                f"quality_warning={quality_warning}"
            )
        elif unanswered:
            # 6b. Partial quality — append supplement for unanswered questions
            logger.info(
                f"process_task: completeness {score} < {retry_score}, "
                f"retrying with unanswered questions: {unanswered}"
            )
            retry_questions = [
                task.questions[i - 1]
                for i in unanswered
                if 0 < i <= len(task.questions)
            ]
            if retry_questions:
                retry_task = ResearchTask(
                    topic=task.topic,
                    questions=retry_questions,
                    scope=f"Дополнительное исследование: ответить на неотвеченные вопросы. {task.scope}",
                    signal_source=task.signal_source,
                    signal_date=task.signal_date,
                    competitor=task.competitor,
                    source_path=task.source_path,
                )
                logger.info(
                    f"process_task: retry with {len(retry_questions)} unanswered questions"
                )
                retry_content, t_in_r, t_out_r = _generate_internal_report(
                    retry_task, context, config,
                )
                tokens_in += t_in_r
                tokens_out += t_out_r
                content = content + "\n\n---\n\n## Дополнение\n\n" + retry_content
                score, quality_warning, _ = _run_completeness_check(
                    content, task.questions, vault_path, config,
                )
                logger.info(
                    f"process_task: after supplement score={score}, "
                    f"quality_warning={quality_warning}"
                )

    # 7. Reject gate: if score still below threshold after retry, move to failed
    if score < min_score and not dry_run:
        logger.warning(
            f"process_task: rejecting report, score={score} < {min_score}, "
            f"moving to failed"
        )
        _move_task_file(task.source_path, "failed", vault_path)
        if notify:
            msg = (
                f"Отчёт отклонён: {task.topic}. "
                f"Completeness: {score}/{min_score}. Задание в failed/."
            )
            send_telegram(msg, parse_mode=None)
        return ResearchResult(
            topic=task.topic,
            report_path=None,
            completeness=score,
            quality_warning=True,
            ideas_count=0,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            method=method,
            error=f"Rejected: completeness {score} < {min_score}",
        )

    # 8. Format + write (score >= min_score or dry_run)
    formatted = _format_report(content, task, score)
    report_path: str | None = None
    if not dry_run:
        path = _write_report(formatted, task, vault_path)
        report_path = str(path)
        logger.info(f"process_task: report written to {report_path}")
        _move_task_file(task.source_path, "processed", vault_path)
    else:
        logger.info("process_task: dry_run=True, skipping write and move")

    # 8a. Extract ideas and classify outcome (BL-198)
    outcome: str | None = None  # type: ignore[no-redef]
    outcome_details = ""
    ideas_refs = []
    extracted_ideas_count = 0

    if report_path and not dry_run:
        outcome, outcome_details, extracted_ideas_count, ideas_refs = _extract_and_classify(
            report_path=Path(report_path),
            task=task,
            vault_path=vault_path,
            config=config,
        )
        logger.info(
            f"process_task: outcome classification done, outcome={outcome}, "
            f"ideas_count={extracted_ideas_count}"
        )

    # 9. Notify completion
    if notify:
        msg = f"Отчёт готов: {task.topic}. Completeness: {score}/10."
        if quality_warning:
            msg += " Warning: Low quality"
        logger.info("process_task: sending completion notification")
        send_telegram(msg, parse_mode=None)

    logger.info(
        f"process_task: completed, topic='{task.topic}', "
        f"completeness={score}, tokens_in={tokens_in}, tokens_out={tokens_out}"
    )
    return ResearchResult(
        topic=task.topic,
        report_path=report_path,
        completeness=score,
        quality_warning=quality_warning,
        ideas_count=extracted_ideas_count,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        method=method,
        error=None,
        outcome=outcome,
        outcome_details=outcome_details,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_NOT_RELEVANT_MARKERS = [
    "не наш профиль",
    "нет пересечений",
    "не релевантно",
    "вне сферы",
    "не применимо",
    "не связано с нашим",
    "другая отрасль",
    "нет связи с продуктом",
]


def _classify_by_reason(reason: str) -> str:
    """Classify no_ideas_reason into 'insight' or 'not_relevant' via marker match (BL-198)."""
    if not reason:
        logger.info("_classify_by_reason: empty reason, defaulting to 'insight'")
        return "insight"

    reason_lower = reason.lower()
    for marker in _NOT_RELEVANT_MARKERS:
        if marker in reason_lower:
            logger.info(f"_classify_by_reason: matched marker '{marker}', outcome=not_relevant")
            return "not_relevant"

    logger.info("_classify_by_reason: no marker matched, outcome=insight")
    return "insight"


def _extract_and_classify(
    report_path: Path,
    task: ResearchTask,
    vault_path: str,
    config: ModeratorConfig,
) -> tuple[str, str, int, list[str]]:
    """Extract signals from a report and classify the research outcome (BL-203).

    Returns: (outcome, outcome_details, signals_count, signal_refs)
    """
    logger.info(f"_extract_and_classify: starting for {report_path.name}")

    try:
        # Load business context
        bc_path = Path(vault_path) / "wiki" / "concepts" / "business-context-brief.md"
        business_context = ""
        if bc_path.exists():
            try:
                business_context = bc_path.read_text(encoding="utf-8")
                logger.info(
                    f"_extract_and_classify: business context loaded, "
                    f"{len(business_context)} chars"
                )
            except Exception as exc:
                logger.error(f"_extract_and_classify: failed to read business context: {exc}")
        else:
            logger.info(f"_extract_and_classify: business context file not found: {bc_path}")

        signals = extract_signals(
            report_path, vault_path, business_context, config,
        )
        logger.info(
            f"_extract_and_classify: extract_signals done, signals={len(signals)}"
        )

        if signals:
            outcome = "signal"
            outcome_details = ""
        else:
            outcome = "insight"
            outcome_details = "No actionable signals extracted from report"

        # Dispatch each extracted signal into the vault (BL-203, AC-12)
        signal_refs: list[str] = []
        for signal in signals:
            signal_title = signal.title[:60]
            logger.info(f"_extract_and_classify: dispatching signal '{signal_title}'")
            ref = dispatch_signal(
                signal_data=signal,
                report_ref=report_path.name,
                item={
                    "title": task.topic,
                    "date": date.today().isoformat(),
                    "source": "research-report",
                    "source_url": "",
                },
                scoring=ScoringResult(relevance=0, reason="from research"),
                vault_path=vault_path,
                run_id=f"research-{date.today().isoformat()}",
            )
            if ref:
                signal_refs.append(ref)
            else:
                logger.warning(
                    f"_extract_and_classify: dispatch_signal returned None for '{signal_title}'"
                )

        # Persist outcome in report frontmatter
        update_frontmatter(report_path, {
            "outcome": outcome,
            "outcome_details": outcome_details,
            "signals_count": len(signals),
            "signal_refs": signal_refs,
        })
        logger.info(f"_extract_and_classify: frontmatter updated, outcome={outcome}")

        # Persist outcome in the moved processed/ JSON task file
        _update_processed_json(task.source_path, {
            "outcome": outcome,
            "outcome_details": outcome_details,
            "signals_count": len(signals),
            "signal_refs": signal_refs,
        })

        logger.info(
            f"_extract_and_classify: done, outcome={outcome}, signals_count={len(signals)}"
        )
        return outcome, outcome_details, len(signals), signal_refs

    except Exception as exc:
        logger.error(f"_extract_and_classify: failed: {exc}", exc_info=True)
        try:
            update_frontmatter(report_path, {
                "outcome": "error",
                "outcome_details": str(exc)[:200],
                "signals_count": 0,
                "signal_refs": [],
            })
            logger.info("_extract_and_classify: recorded outcome=error in frontmatter")
        except Exception as fm_exc:
            logger.error(
                f"_extract_and_classify: failed to record error in frontmatter: {fm_exc}"
            )
        return "error", str(exc)[:200], 0, []


def _update_processed_json(source_path: Path, outcome_data: dict) -> None:
    """Append outcome fields into the moved processed/ JSON task file (BL-198).

    By the time this runs, _move_task_file() has already relocated the task
    JSON from queue/ to processed/, so we look it up there by filename.
    """
    logger.info(f"_update_processed_json: updating {source_path.name}")
    proc_dir = raw_research_queue_processed()
    proc_path = proc_dir / source_path.name

    if not proc_path.exists():
        logger.warning(f"_update_processed_json: file not found: {proc_path}")
        return

    try:
        data = json.loads(proc_path.read_text(encoding="utf-8"))
        data.update(outcome_data)
        atomic_write(proc_path, json.dumps(data, ensure_ascii=False, indent=2))
        logger.info(f"_update_processed_json: success, path={proc_path}")
    except Exception as exc:
        logger.error(f"_update_processed_json: failed to update {proc_path}: {exc}")


def _scan_queue(vault_path: str, target_file: str | None = None) -> list[Path]:
    """Scan research queue directory for .json task files."""
    logger.info(f"_scan_queue: scanning research queue, target_file={target_file}")
    queue_dir = raw_research_queue()

    if not queue_dir.exists():
        logger.info(f"_scan_queue: queue directory does not exist: {queue_dir}")
        return []

    if target_file:
        target_path = Path(target_file)
        if not target_path.is_absolute():
            target_path = queue_dir / target_file
        if target_path.exists():
            logger.info(f"_scan_queue: returning single target file: {target_path}")
            return [target_path]
        logger.warning(f"_scan_queue: target file not found: {target_path}")
        return []

    json_files = sorted(queue_dir.glob("*.json"))
    logger.info(f"_scan_queue: found {len(json_files)} json file(s) in {queue_dir}")
    return json_files


def _parse_task(path: Path) -> ResearchTask:
    """Parse a JSON task file into a ResearchTask."""
    logger.info(f"_parse_task: parsing {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info(f"_parse_task: JSON loaded, keys={list(data.keys())}")
    except Exception as exc:
        logger.error(f"_parse_task: failed to read/parse {path}: {exc}")
        raise ValueError(f"Cannot parse task file {path}: {exc}") from exc

    topic = data.get("topic")
    questions = data.get("questions")
    scope = data.get("scope")

    if not topic:
        logger.error(f"_parse_task: missing required field 'topic' in {path.name}")
        raise ValueError(f"Missing required field 'topic' in {path.name}")
    if not questions or not isinstance(questions, list) or len(questions) == 0:
        logger.error(f"_parse_task: 'questions' must be a non-empty list in {path.name}")
        raise ValueError(f"'questions' must be a non-empty list in {path.name}")
    if not scope:
        logger.error(f"_parse_task: missing required field 'scope' in {path.name}")
        raise ValueError(f"Missing required field 'scope' in {path.name}")

    task = ResearchTask(
        topic=topic,
        questions=questions,
        scope=scope,
        signal_source=data.get("signal_source", ""),
        signal_date=data.get("signal_date", ""),
        competitor=data.get("competitor", ""),
        source_path=path,
    )
    logger.info(f"_parse_task: parsed successfully, topic='{task.topic}', questions={len(task.questions)}")
    return task


def _check_existing_report(vault_path: str, task: ResearchTask) -> Path | None:
    """Check if a report for this task already exists."""
    logger.info(f"_check_existing_report: checking for slug='{task.slug}'")
    reports_dir = wiki_reports()

    if not reports_dir.exists():
        logger.info("_check_existing_report: reports directory does not exist")
        return None

    pattern = f"*-{task.slug}*"
    matches = list(reports_dir.glob(pattern))
    logger.info(f"_check_existing_report: glob '{pattern}' found {len(matches)} match(es)")

    if matches:
        logger.info(f"_check_existing_report: existing report found: {matches[0]}")
        return matches[0]

    logger.info("_check_existing_report: no existing report found")
    return None


def _collect_context(vault_path: str, task: ResearchTask) -> dict[str, str]:
    """Collect business and competitor context from vault."""
    logger.info(f"_collect_context: collecting context for topic='{task.topic}'")
    context: dict[str, str] = {"business_context": "", "competitor_context": ""}

    # Business context
    bc_path = Path(vault_path) / "wiki" / "concepts" / "business-context-brief.md"
    if bc_path.exists():
        try:
            context["business_context"] = bc_path.read_text(encoding="utf-8")
            logger.info(f"_collect_context: business context loaded, {len(context['business_context'])} chars")
        except Exception as exc:
            logger.error(f"_collect_context: failed to read business context: {exc}")
    else:
        logger.info(f"_collect_context: business context file not found: {bc_path}")

    # Competitor context
    if task.competitor:
        reports_dir = Path(vault_path) / "wiki" / "reports"
        pattern = f"Competitor-Info-{task.competitor}*"
        matches = list(reports_dir.glob(pattern)) if reports_dir.exists() else []
        logger.info(f"_collect_context: competitor glob '{pattern}' found {len(matches)} match(es)")
        if matches:
            try:
                context["competitor_context"] = matches[0].read_text(encoding="utf-8")
                logger.info(
                    f"_collect_context: competitor context loaded from {matches[0].name}, "
                    f"{len(context['competitor_context'])} chars"
                )
            except Exception as exc:
                logger.error(f"_collect_context: failed to read competitor context: {exc}")
    else:
        logger.info("_collect_context: no competitor specified, skipping competitor context")

    logger.info(
        f"_collect_context: done, business_context={len(context['business_context'])} chars, "
        f"competitor_context={len(context['competitor_context'])} chars"
    )
    return context


def _generate_internal_report(
    task: ResearchTask, context: dict[str, str], config: ModeratorConfig,
) -> tuple[str, int, int]:
    """Generate a research report via LLM."""
    logger.info(f"_generate_internal_report: starting for topic='{task.topic}'")

    # Load prompt template
    prompts_dir = Path(__file__).parent / "prompts"
    prompt_path = prompts_dir / "research_report.txt"
    try:
        template = prompt_path.read_text(encoding="utf-8")
        logger.info(f"_generate_internal_report: prompt template loaded, {len(template)} chars")
    except Exception as exc:
        logger.error(f"_generate_internal_report: failed to load prompt template: {exc}")
        raise ResearchError(f"Cannot load prompt template: {exc}") from exc

    # Format questions as numbered list
    questions_text = "\n".join(
        f"{i + 1}. {q}" for i, q in enumerate(task.questions)
    )

    # Replace placeholders
    prompt = template.replace("{business_context}", context.get("business_context", ""))
    prompt = prompt.replace("{competitor_context}", context.get("competitor_context", ""))
    prompt = prompt.replace("{topic}", task.topic)
    prompt = prompt.replace("{signal_source}", task.signal_source)
    prompt = prompt.replace("{scope}", task.scope)
    prompt = prompt.replace("{questions}", questions_text)

    logger.info(f"_generate_internal_report: prompt assembled, {len(prompt)} chars")

    # Call LLM
    messages = [{"role": "user", "content": prompt}]
    max_retries = 2
    for attempt in range(max_retries):
        try:
            logger.info(
                f"_generate_internal_report: calling LLM, attempt={attempt + 1}/{max_retries}"
            )
            response_text, meta = call_detailed(
                operation="research_report",
                messages=messages,
                max_tokens=4000,
                timeout=120,
            )
            logger.info(
                f"_generate_internal_report: LLM response received, "
                f"len={len(response_text)}, provider={meta.get('used', 'unknown')}"
            )

            tokens_in = meta.get("input_tokens", 0) or 0
            tokens_out = meta.get("output_tokens", 0) or 0

            if len(response_text) < 200:
                logger.warning(
                    f"_generate_internal_report: response too short ({len(response_text)} chars), "
                    f"attempt={attempt + 1}"
                )
                if attempt < max_retries - 1:
                    continue
                raise ResearchError(
                    f"LLM response too short after {max_retries} attempts: "
                    f"{len(response_text)} chars"
                )

            logger.info(
                f"_generate_internal_report: success, tokens_in={tokens_in}, "
                f"tokens_out={tokens_out}"
            )
            return response_text, tokens_in, tokens_out

        except ResearchError:
            raise
        except Exception as exc:
            logger.error(
                f"_generate_internal_report: LLM call failed on attempt "
                f"{attempt + 1}: {exc}"
            )
            if attempt < max_retries - 1:
                continue
            raise ResearchError(f"LLM call failed after {max_retries} attempts: {exc}") from exc

    raise ResearchError("_generate_internal_report: exhausted all retries with no result")


def _run_completeness_check(
    report_content: str,
    questions: list[str],
    vault_path: str,
    config: ModeratorConfig,
) -> tuple[int, bool, list[int]]:
    """Run completeness check on generated report content."""
    logger.info(f"_run_completeness_check: starting, content_len={len(report_content)}, questions={len(questions)}")

    tmp_path: Path | None = None
    tmp_fd: int | None = None
    try:
        # Write to temp file for QualityGate
        tmp_fd, tmp_str = tempfile.mkstemp(suffix=".md", prefix="research-report-")
        tmp_path = Path(tmp_str)
        tmp_path.write_text(report_content, encoding="utf-8")
        logger.info(f"_run_completeness_check: temp file written: {tmp_path}")

        gate = QualityGate(vault_path, config)
        logger.info("_run_completeness_check: calling QualityGate.check_report_completeness")
        result = gate.check_report_completeness(tmp_path, questions)
        logger.info(
            f"_run_completeness_check: result score={result.score}, "
            f"passed={result.passed}, issues={result.issues}"
        )

        score = result.score
        quality_warning = result.improvements.get("_quality_warning", False)
        unanswered = result.improvements.get("unanswered_questions", [])

        logger.info(
            f"_run_completeness_check: done, score={score}, "
            f"quality_warning={quality_warning}, unanswered={unanswered}"
        )
        return score, quality_warning, unanswered

    except Exception as exc:
        logger.error(f"_run_completeness_check: failed: {exc}")
        return 5, False, []

    finally:
        if tmp_fd is not None:
            try:
                import os as _os
                _os.close(tmp_fd)
            except Exception:
                pass
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
                logger.info(f"_run_completeness_check: temp file removed: {tmp_path}")
            except Exception as exc:
                logger.warning(f"_run_completeness_check: failed to remove temp file: {exc}")


def _format_report(content: str, task: ResearchTask, completeness: int) -> str:
    """Format report with YAML frontmatter."""
    logger.info(f"_format_report: formatting report for topic='{task.topic}'")

    questions_yaml = "\n".join(f'  - "{q}"' for q in task.questions)
    today = date.today().isoformat()

    formatted = f"""---
type: research-report
topic: "{task.topic}"
date: "{today}"
signal_source: "{task.signal_source}"
questions:
{questions_yaml}
decay_rate: 0.03
relevance: 1.0
tier: active
last_accessed: "{today}"
access_count: 0
completeness: {completeness}
---

# Исследование: {task.topic}

{content}
"""

    logger.info(f"_format_report: done, total length={len(formatted)} chars")
    return formatted


def _write_report(formatted: str, task: ResearchTask, vault_path: str) -> Path:
    """Write formatted report to wiki/reports/."""
    report_path = wiki_reports() / task.report_filename
    logger.info(f"_write_report: writing to {report_path}")

    try:
        atomic_write(report_path, formatted)
        logger.info(f"_write_report: success, path={report_path}")
        return report_path
    except Exception as exc:
        logger.error(f"_write_report: failed to write {report_path}: {exc}")
        raise


def _move_task_file(source: Path, destination: str, vault_path: str) -> None:
    """Move task file to processed or failed subdirectory."""
    logger.info(f"_move_task_file: moving {source.name} to {destination}")

    if not source.exists():
        logger.warning(f"_move_task_file: source does not exist: {source}")
        return

    if destination == "processed":
        dest_dir = raw_research_queue_processed()
    elif destination == "failed":
        dest_dir = raw_research_queue_failed()
    else:
        logger.error(f"_move_task_file: unknown destination '{destination}'")
        return

    try:
        shutil.move(str(source), str(dest_dir / source.name))
        logger.info(f"_move_task_file: moved {source.name} to {dest_dir}")
    except Exception as exc:
        logger.error(f"_move_task_file: failed to move {source.name}: {exc}")


def _resolve_method(config: ModeratorConfig, override: str | None) -> str:
    """Resolve which generation method to use."""
    logger.info(f"_resolve_method: override={override}, config.report_method={config.report_method}")

    if override:
        logger.info(f"_resolve_method: using override method '{override}'")
        return override

    if config.report_method == "cowork":
        logger.warning(
            "_resolve_method: cowork not implemented, falling back to internal"
        )
        return "internal"

    logger.info(f"_resolve_method: using config method '{config.report_method}'")
    return config.report_method
