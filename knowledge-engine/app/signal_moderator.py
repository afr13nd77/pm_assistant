from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from shared.llm_client import call_detailed

if TYPE_CHECKING:
    from app.quality_gate import DedupResult

logger = logging.getLogger(__name__)

# Module-level prompt cache to avoid re-reading files on every call
_prompt_cache: dict[str, str] = {}


@dataclass
class ScoringResult:
    """Result of signal relevance scoring (AC-01, AC-02, AC-03)."""

    relevance: int = 0  # 0-10
    reason: str = ""
    matched_entities: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Result of signal content analysis (AC-05, AC-06, AC-07)."""

    reaction: str = ""  # 'idea' | 'report'
    analysis: str = ""  # 3-5 sentences
    threat_level: str = "low"  # 'low' | 'medium' | 'high'
    idea_draft: dict | None = None  # {title, problem, solution, domain}
    report_brief: dict | None = None  # {topic, questions, scope}
    _quality_warning: bool = False
    _attempts: int = 1


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _load_prompt(name: str) -> str:
    """Load prompt template from knowledge-engine/app/prompts/{name}.txt.

    Uses a module-level dict cache to avoid repeated filesystem reads.
    """
    if name in _prompt_cache:
        logger.info(f"_load_prompt: returning cached prompt '{name}'")
        return _prompt_cache[name]

    prompts_dir = Path(__file__).parent / "prompts"
    path = prompts_dir / f"{name}.txt"
    logger.info(f"_load_prompt: loading prompt from {path}")
    try:
        content = path.read_text(encoding="utf-8")
        _prompt_cache[name] = content
        logger.info(f"_load_prompt: loaded '{name}' ({len(content)} chars)")
        return content
    except FileNotFoundError:
        logger.error(f"_load_prompt: prompt file not found: {path}")
        return ""
    except Exception as e:
        logger.error(f"_load_prompt: failed to read {path}: {e}")
        return ""


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict | None:
    """Extract JSON from LLM response.

    Supports: direct JSON, markdown code blocks, and embedded JSON objects.
    """
    logger.info(f"_parse_json_response: parsing ({len(text)} chars)")

    # Try direct parse
    try:
        result = json.loads(text)
        logger.info(f"_parse_json_response: parsed directly")
        return result
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            logger.info(f"_parse_json_response: parsed from markdown code block")
            return result
        except json.JSONDecodeError:
            pass

    # Try finding JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            logger.info(f"_parse_json_response: parsed from embedded object")
            return result
        except json.JSONDecodeError:
            pass

    logger.error(f"_parse_json_response: cannot parse JSON from response: {text[:200]}...")
    return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_scoring_prompt(
    item: dict, business_context: str, memory_context: str
) -> str:
    """Build scoring prompt from signal_score.txt template."""
    logger.info(f"_build_scoring_prompt: building for item '{item.get('title', '')[:50]}'")

    template = _load_prompt("signal_score")
    if not template:
        logger.error(f"_build_scoring_prompt: template signal_score.txt is empty or missing")
        return ""

    news_item = (
        f"Заголовок: {item['title']}\n"
        f"Суть: {item.get('summary', '')}\n"
        f"Источник: {item.get('source', 'unknown')}"
    )

    prompt = template.replace("{business_context}", business_context)
    prompt = prompt.replace("{memory_context}", memory_context)
    prompt = prompt.replace("{news_item}", news_item)

    logger.info(f"_build_scoring_prompt: built prompt ({len(prompt)} chars)")
    return prompt


def _build_analysis_prompt(
    item: dict,
    scoring: ScoringResult,
    business_context: str,
    competitor_profile: str | None,
    memory_history: str,
    critique: str | None = None,
) -> str:
    """Build analysis prompt from signal_analyze.txt template.

    On retry iterations, appends critique block to prompt end.
    """
    logger.info(f"_build_analysis_prompt: building for item '{item.get('title', '')[:50]}'")

    template = _load_prompt("signal_analyze")
    if not template:
        logger.error(f"_build_analysis_prompt: template signal_analyze.txt is empty or missing")
        return ""

    news_item = (
        f"Заголовок: {item['title']}\n"
        f"Суть: {item.get('summary', '')}\n"
        f"Источник: {item.get('source', 'unknown')}"
    )

    prompt = template.replace("{business_context}", business_context)
    prompt = prompt.replace(
        "{competitor_profile}", competitor_profile or "Нет данных"
    )
    prompt = prompt.replace("{memory_history}", memory_history or "")
    prompt = prompt.replace("{news_item}", news_item)

    if critique is not None:
        prompt += f"\n\nПредыдущая попытка не прошла проверку:\n{critique}"
        logger.info(f"_build_analysis_prompt: critique block appended ({len(critique)} chars)")

    logger.info(f"_build_analysis_prompt: built prompt ({len(prompt)} chars)")
    return prompt


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def score_signal(
    item: dict,
    business_context: str,
    memory_context: str,
    config: Any,
) -> ScoringResult:
    """Score signal relevance on 0-10 scale (AC-01, AC-02, AC-03).

    1. Load and fill prompt template
    2. Call LLM via call_detailed(operation='signal_score')
    3. Parse JSON response; validate fields
    4. On JSONDecodeError: 1 retry with re-prompt
    5. On repeated failure: return ScoringResult(relevance=0, reason="JSON parse error")
    """
    title = item.get("title", "unknown")
    logger.info(f"score_signal: starting for '{title[:60]}'")

    prompt = _build_scoring_prompt(item, business_context, memory_context)
    if not prompt:
        logger.error(f"score_signal: empty prompt, returning default ScoringResult")
        return ScoringResult(relevance=0, reason="Empty prompt template")

    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, 3):  # max 2 attempts (1 original + 1 retry)
        logger.info(f"score_signal: LLM call attempt {attempt}/2")
        try:
            response, meta = call_detailed(
                operation="signal_score",
                messages=messages,
                max_tokens=300,
                timeout=30,
            )
            logger.info(
                f"score_signal: LLM call succeeded, provider={meta.get('used', 'unknown')}"
            )
        except Exception as e:
            logger.error(f"score_signal: LLM call failed (attempt {attempt}): {e}")
            if attempt == 1:
                continue
            return ScoringResult(
                relevance=0, reason=f"LLM call error: {e}"
            )

        parsed = _parse_json_response(response)
        if parsed is not None:
            relevance = parsed.get("relevance", 0)
            if isinstance(relevance, (int, float)):
                relevance = max(0, min(10, int(relevance)))
            else:
                relevance = 0

            reason = str(parsed.get("reason", ""))
            matched_entities = parsed.get("matched_entities", [])
            if not isinstance(matched_entities, list):
                matched_entities = []

            result = ScoringResult(
                relevance=relevance,
                reason=reason,
                matched_entities=matched_entities,
            )
            logger.info(
                f"score_signal: completed, relevance={result.relevance}, "
                f"reason='{result.reason[:80]}', entities={result.matched_entities}"
            )
            return result

        # JSON parse failed
        logger.warning(f"score_signal: JSON parse failed (attempt {attempt})")
        if attempt == 1:
            # Re-prompt with explicit instruction
            messages = [
                {
                    "role": "user",
                    "content": prompt
                    + "\n\nВНИМАНИЕ: предыдущий ответ не был валидным JSON. "
                    "Верни ТОЛЬКО JSON объект, без текста вокруг.",
                }
            ]

    logger.error(f"score_signal: all attempts exhausted, returning default")
    return ScoringResult(relevance=0, reason="JSON parse error")


def analyze_signal(
    item: dict,
    scoring: ScoringResult,
    business_context: str,
    competitor_profile: str | None,
    memory_history: str,
    config: Any,
    critique: str | None = None,
    operation_group: str | None = None,
) -> AnalysisResult:
    """Conduct content analysis of a signal (AC-05, AC-06, AC-07).

    1. Load and fill prompt template
    2. If critique is set, append critique block
    3. Determine operation based on operation_group
    4. Call LLM via call_detailed
    5. Parse and validate JSON response
    """
    title = item.get("title", "unknown")
    logger.info(f"analyze_signal: starting for '{title[:60]}'")

    prompt = _build_analysis_prompt(
        item, scoring, business_context, competitor_profile, memory_history, critique
    )
    if not prompt:
        logger.error(f"analyze_signal: empty prompt, returning default AnalysisResult")
        return AnalysisResult(
            reaction="idea",
            analysis="Empty prompt template",
            threat_level="low",
        )

    # Determine operation name based on escalation
    if operation_group == "signal_escalation":
        operation = "signal_analyze_escalation"
        logger.info(f"analyze_signal: using escalation operation")
    else:
        operation = "signal_analyze"

    messages = [{"role": "user", "content": prompt}]

    try:
        logger.info(f"analyze_signal: calling LLM, operation={operation}")
        response, meta = call_detailed(
            operation=operation,
            messages=messages,
            max_tokens=1500,
            timeout=60,
        )
        logger.info(
            f"analyze_signal: LLM call succeeded, provider={meta.get('used', 'unknown')}"
        )
    except Exception as e:
        logger.error(f"analyze_signal: LLM call failed: {e}")
        return AnalysisResult(
            reaction="idea",
            analysis=f"LLM call error: {e}",
            threat_level="low",
        )

    parsed = _parse_json_response(response)
    if parsed is None:
        logger.error(f"analyze_signal: JSON parse failed")
        return AnalysisResult(
            reaction="idea",
            analysis="JSON parse error",
            threat_level="low",
        )

    # Validate and extract fields
    reaction = parsed.get("reaction", "idea")
    if reaction not in ("idea", "report"):
        logger.warning(f"analyze_signal: unexpected reaction='{reaction}', defaulting to 'idea'")
        reaction = "idea"

    threat_level = parsed.get("threat_level", "low")
    if threat_level not in ("low", "medium", "high"):
        threat_level = "low"

    idea_draft = parsed.get("idea_draft")
    report_brief = parsed.get("report_brief")

    result = AnalysisResult(
        reaction=reaction,
        analysis=str(parsed.get("analysis", "")),
        threat_level=threat_level,
        idea_draft=idea_draft if reaction == "idea" else None,
        report_brief=report_brief if reaction == "report" else None,
    )

    logger.info(
        f"analyze_signal: completed, reaction={result.reaction}, "
        f"threat_level={result.threat_level}, "
        f"has_idea_draft={result.idea_draft is not None}, "
        f"has_report_brief={result.report_brief is not None}"
    )
    return result


# ---------------------------------------------------------------------------
# Dispatch functions
# ---------------------------------------------------------------------------


def dispatch_idea(
    item: dict,
    analysis: AnalysisResult,
    vault_path: str,
    notify: bool,
    dry_run: bool,
    dedup_result: DedupResult | None = None,
) -> str | None:
    """Create idea in vault from analysis result (AC-08, AC-10, AC-30).

    Writes idea as .md file with frontmatter directly to vault
    (ke-cron has no access to pm-bot HTTP API).
    """
    title = (analysis.idea_draft or {}).get("title", "Без названия")
    logger.info(f"dispatch_idea: starting for '{title[:60]}'")

    if not analysis.idea_draft:
        logger.error(f"dispatch_idea: no idea_draft in analysis, returning None")
        return None

    # Build idea_data from analysis.idea_draft
    idea_data = {
        "title": analysis.idea_draft.get("title", "Без названия"),
        "problem": analysis.idea_draft.get("problem", ""),
        "solution": analysis.idea_draft.get("solution", ""),
        "domain": analysis.idea_draft.get("domain", "general"),
        "source": "signal",
        "signal_date": item.get("date", datetime.now().strftime("%Y-%m-%d")),
        "signal_source": item.get("source_url", item.get("source", "")),
    }

    # Mark related idea if dedup detected similarity (AC-10)
    if dedup_result is not None and hasattr(dedup_result, "similarity"):
        if dedup_result.similarity >= 6:
            idea_data["related"] = dedup_result.similar_to
            logger.info(
                f"dispatch_idea: marked related to {dedup_result.similar_to} "
                f"(similarity={dedup_result.similarity})"
            )

    if dry_run:
        logger.info(f"dispatch_idea: dry_run=True, skipping vault write for '{title[:60]}'")
        return None

    # Write idea as .md file with frontmatter
    today = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-zA-Zа-яА-Яё0-9]", "-", title)[:50]
    slug = re.sub(r"-+", "-", slug).strip("-")
    filename = f"{today}-signal-{slug}.md"
    idea_id = filename

    ideas_dir = Path(vault_path) / "raw" / "inbound" / "ideas"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    idea_path = ideas_dir / filename

    # Build frontmatter
    related_line = ""
    if "related" in idea_data:
        related_line = f'related: "{idea_data["related"]}"\n'

    frontmatter = (
        f"---\n"
        f'title: "{idea_data["title"]}"\n'
        f"type: idea\n"
        f"domain: {idea_data['domain']}\n"
        f'status: "Новая"\n'
        f"source: signal\n"
        f'signal_date: "{idea_data["signal_date"]}"\n'
        f'signal_source: "{idea_data["signal_source"]}"\n'
        f"{related_line}"
        f'created: "{today}"\n'
        f"---\n"
    )

    content = (
        f"{frontmatter}\n"
        f"# {idea_data['title']}\n\n"
        f"## Проблема\n\n{idea_data['problem']}\n\n"
        f"## Решение\n\n{idea_data['solution']}\n\n"
        f"## Анализ\n\n{analysis.analysis}\n"
    )

    try:
        idea_path.write_text(content, encoding="utf-8")
        logger.info(f"dispatch_idea: wrote idea to {idea_path}")
    except Exception as e:
        logger.error(f"dispatch_idea: failed to write idea file: {e}")
        return None

    # Send Telegram notification (AC-30)
    if notify:
        try:
            from app.notifier import send_telegram

            msg = (
                f"Новая идея из новостей:\n"
                f"{idea_data['title']}\n"
                f"Домен: {idea_data['domain']}\n"
                f"Источник: {item.get('title', '')}\n"
                f"{analysis.analysis[:200]}"
            )
            send_telegram(msg, parse_mode=None)
            logger.info(f"dispatch_idea: Telegram notification sent")
        except Exception as e:
            logger.warning(f"dispatch_idea: Telegram notification failed: {e}")

    # Write to processed.md
    _write_processed_md(
        vault_path,
        today,
        [
            {
                "title": item.get("title", ""),
                "reaction": "idea",
                "result_ref": filename,
                "quality_score": "",
            }
        ],
    )

    logger.info(f"dispatch_idea: completed, idea_id={idea_id}")
    return idea_id


def dispatch_report(
    item: dict,
    analysis: AnalysisResult,
    vault_path: str,
    notify: bool,
    dry_run: bool,
    competitor: str = "",
) -> str | None:
    """Create research queue JSON for deep research (AC-07, AC-31).

    Writes a JSON task file to raw/inbound/research-queue/.
    """
    if not analysis.report_brief:
        logger.error(f"dispatch_report: no report_brief in analysis, returning None")
        return None

    topic = analysis.report_brief.get("topic", "unknown")
    logger.info(f"dispatch_report: starting for topic '{topic[:60]}'")

    # Build slug from topic
    slug = re.sub(r"[^a-zA-Zа-яА-Яё0-9]", "-", topic)[:50]
    slug = re.sub(r"-+", "-", slug).strip("-")
    today = datetime.now().strftime("%Y-%m-%d")

    report_data = {
        "topic": topic,
        "questions": analysis.report_brief.get("questions", []),
        "scope": analysis.report_brief.get("scope", ""),
        "signal_source": item.get("source_url", item.get("source", "")),
        "signal_date": item.get("date", today),
        "competitor": analysis.report_brief.get("competitor") or competitor,
    }
    logger.info(
        f"dispatch_report: competitor='{report_data['competitor']}' for topic '{topic[:60]}'"
    )

    if dry_run:
        logger.info(f"dispatch_report: dry_run=True, skipping vault write for '{topic[:60]}'")
        return None

    # Write research queue JSON
    queue_dir = Path(vault_path) / "raw" / "inbound" / "research-queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{today}-{slug}.json"
    report_path = queue_dir / filename

    try:
        report_path.write_text(
            json.dumps(report_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"dispatch_report: wrote research queue to {report_path}")
    except Exception as e:
        logger.error(f"dispatch_report: failed to write research queue file: {e}")
        return None

    # Send Telegram notification (AC-31)
    if notify:
        try:
            from app.notifier import send_telegram

            msg = f"Запущен анализ: {topic}..."
            send_telegram(msg, parse_mode=None)
            logger.info(f"dispatch_report: Telegram notification sent")
        except Exception as e:
            logger.warning(f"dispatch_report: Telegram notification failed: {e}")

    logger.info(f"dispatch_report: completed, path={report_path}")
    return str(report_path)


# ---------------------------------------------------------------------------
# Vault log helpers
# ---------------------------------------------------------------------------


def _write_skipped_md(
    vault_path: str, date: str, items: list[dict]
) -> None:
    """Write/append to wiki/signals/YYYY-MM-DD-skipped.md (AC-04).

    Format: Markdown table with title, relevance, reason.
    """
    logger.info(f"_write_skipped_md: writing {len(items)} skipped items for {date}")

    signals_dir = Path(vault_path) / "wiki" / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)
    filepath = signals_dir / f"{date}-skipped.md"

    try:
        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
        else:
            existing = (
                f"# Skipped Signals {date}\n\n"
                "| Title | Relevance | Reason |\n"
                "|-------|-----------|--------|\n"
            )

        lines = []
        for item in items:
            title = item.get("title", "").replace("|", "\\|")
            relevance = item.get("relevance", 0)
            reason = item.get("reason", "").replace("|", "\\|")
            lines.append(f"| {title} | {relevance} | {reason} |")

        content = existing + "\n".join(lines) + "\n"
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"_write_skipped_md: wrote to {filepath}")
    except Exception as e:
        logger.error(f"_write_skipped_md: failed to write {filepath}: {e}")


def _write_processed_md(
    vault_path: str, date: str, processed_items: list[dict]
) -> None:
    """Write/append to wiki/signals/YYYY-MM-DD-processed.md (AC-45).

    Format: Markdown table with title, reaction, result_ref, quality_score.
    """
    logger.info(
        f"_write_processed_md: writing {len(processed_items)} processed items for {date}"
    )

    signals_dir = Path(vault_path) / "wiki" / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)
    filepath = signals_dir / f"{date}-processed.md"

    try:
        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
        else:
            existing = (
                f"# Processed Signals {date}\n\n"
                "| Title | Reaction | Result Ref | Quality Score |\n"
                "|-------|----------|------------|---------------|\n"
            )

        lines = []
        for item in processed_items:
            title = item.get("title", "").replace("|", "\\|")
            reaction = item.get("reaction", "")
            result_ref = item.get("result_ref", "")
            quality_score = item.get("quality_score", "")
            lines.append(f"| {title} | {reaction} | {result_ref} | {quality_score} |")

        content = existing + "\n".join(lines) + "\n"
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"_write_processed_md: wrote to {filepath}")
    except Exception as e:
        logger.error(f"_write_processed_md: failed to write {filepath}: {e}")
