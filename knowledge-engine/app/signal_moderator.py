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


@dataclass
class ReportResult:
    """Result of analytical report generation (BL-203)."""

    content: str = ""
    threat_level: str = "medium"
    _quality_warning: bool = False
    _attempts: int = 1


@dataclass
class SignalData:
    """Single extracted signal from analytical report (BL-203, AC-02)."""

    title: str = ""
    analysis: str = ""
    threat_level: str = "low"
    recommended_action: str = ""
    draft_idea: dict | None = None
    domain: str = "general"
    priority_hint: str = "medium"
    rationale: str = ""


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
        logger.info("_parse_json_response: parsed directly")
        return result
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            logger.info("_parse_json_response: parsed from markdown code block")
            return result
        except json.JSONDecodeError:
            pass

    # Try finding JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            logger.info("_parse_json_response: parsed from embedded object")
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
        logger.error("_build_scoring_prompt: template signal_score.txt is empty or missing")
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
        logger.error("_build_analysis_prompt: template signal_analyze.txt is empty or missing")
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
        logger.error("score_signal: empty prompt, returning default ScoringResult")
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

    logger.error("score_signal: all attempts exhausted, returning default")
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
        logger.error("analyze_signal: empty prompt, returning default AnalysisResult")
        return AnalysisResult(
            reaction="idea",
            analysis="Empty prompt template",
            threat_level="low",
        )

    # Determine operation name based on escalation
    if operation_group == "signal_escalation":
        operation = "signal_analyze_escalation"
        logger.info("analyze_signal: using escalation operation")
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
        logger.error("analyze_signal: JSON parse failed")
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
# Report generation (BL-203)
# ---------------------------------------------------------------------------


def _build_report_prompt(
    item: dict,
    scoring: ScoringResult,
    business_context: str,
    competitor_profile: str | None,
    memory_history: str,
    critique: str | None = None,
) -> str:
    """Build report generation prompt from signal_report_generate.txt template."""
    logger.info(f"_build_report_prompt: building for item '{item.get('title', '')[:50]}'")

    template = _load_prompt("signal_report_generate")
    if not template:
        logger.error("_build_report_prompt: template signal_report_generate.txt is empty or missing")
        return ""

    news_item = (
        f"Заголовок: {item['title']}\n"
        f"Суть: {item.get('summary', '')}\n"
        f"Источник: {item.get('source', 'unknown')}\n"
        f"URL: {item.get('source_url', '')}"
    )

    prompt = template.replace("{business_context}", business_context)
    prompt = prompt.replace("{competitor_profile}", competitor_profile or "Нет данных")
    prompt = prompt.replace("{memory_history}", memory_history or "")
    prompt = prompt.replace("{news_item}", news_item)

    if critique is not None:
        prompt += f"\n\nПредыдущая попытка не прошла проверку:\n{critique}"
        logger.info(f"_build_report_prompt: critique block appended ({len(critique)} chars)")

    logger.info(f"_build_report_prompt: built prompt ({len(prompt)} chars)")
    return prompt


def generate_analysis_report(
    item: dict,
    scoring: ScoringResult,
    business_context: str,
    competitor_profile: str | None,
    memory_history: str,
    config: Any,
    critique: str | None = None,
    operation_group: str | None = None,
) -> ReportResult:
    """Generate full analytical report for a news item (BL-203).

    1. Build prompt from signal_report_generate.txt
    2. Call LLM via call_detailed(operation="signal_report_generate")
    3. Parse response: markdown before <report_meta> → content, JSON in tag → threat_level
    4. Return ReportResult
    """
    title = item.get("title", "unknown")
    logger.info(f"generate_analysis_report: starting for '{title[:60]}'")

    prompt = _build_report_prompt(
        item, scoring, business_context, competitor_profile, memory_history, critique
    )
    if not prompt:
        logger.error("generate_analysis_report: empty prompt, returning default ReportResult")
        return ReportResult(content="Empty prompt template", threat_level="medium")

    if operation_group == "signal_escalation":
        operation = "signal_analyze_escalation"
        logger.info("generate_analysis_report: using escalation operation")
    else:
        operation = "signal_report_generate"

    messages = [{"role": "user", "content": prompt}]

    try:
        logger.info(f"generate_analysis_report: calling LLM, operation={operation}")
        response, meta = call_detailed(
            operation=operation,
            messages=messages,
            max_tokens=4000,
            timeout=90,
        )
        logger.info(
            f"generate_analysis_report: LLM call succeeded, "
            f"provider={meta.get('used', 'unknown')}, response_len={len(response)}"
        )
    except Exception as e:
        logger.error(f"generate_analysis_report: LLM call failed: {e}")
        return ReportResult(content=f"LLM call error: {e}", threat_level="medium")

    # Parse report_meta tag
    threat_level = "medium"
    content = response

    meta_match = re.search(r"<report_meta>\s*(\{.*?\})\s*</report_meta>", response, re.DOTALL)
    if meta_match:
        content = response[:meta_match.start()].rstrip()
        try:
            meta_json = json.loads(meta_match.group(1))
            tl = meta_json.get("threat_level", "medium")
            if tl in ("low", "medium", "high"):
                threat_level = tl
            logger.info(f"generate_analysis_report: parsed threat_level={threat_level}")
        except json.JSONDecodeError as e:
            logger.warning(f"generate_analysis_report: failed to parse report_meta JSON: {e}")
    else:
        logger.warning("generate_analysis_report: <report_meta> tag not found, using default threat_level='medium'")

    result = ReportResult(content=content, threat_level=threat_level)
    logger.info(
        f"generate_analysis_report: completed, content_len={len(result.content)}, "
        f"threat_level={result.threat_level}"
    )
    return result


# ---------------------------------------------------------------------------
# Wiki signal idea helpers (BL-202)
# ---------------------------------------------------------------------------

_IDEA_NUM_PATTERN = re.compile(r"IDEA-(\d{4})-")


def _max_idea_number(vault_path: str) -> int:
    """Scan raw/inbound/ideas/ and wiki/domains/*/ideas/ for max IDEA-NNNN number.

    Returns the highest numeric part found, or 0 if none exist.
    Used to generate sequential IDEA IDs for wiki signal ideas.
    """
    logger.info(f"_max_idea_number: scanning vault_path={vault_path}")
    max_num = 0

    # 1. Scan raw/inbound/ideas/
    raw_dir = Path(vault_path) / "raw" / "inbound" / "ideas"
    if raw_dir.exists():
        for f in raw_dir.glob("IDEA-*.md"):
            m = _IDEA_NUM_PATTERN.match(f.name)
            if m:
                max_num = max(max_num, int(m.group(1)))
        logger.info(f"_max_idea_number: scanned raw_dir, max_num={max_num}")
    else:
        logger.info(f"_max_idea_number: raw_dir does not exist: {raw_dir}")

    # 2. Scan wiki/domains/*/ideas/
    domains_dir = Path(vault_path) / "wiki" / "domains"
    if domains_dir.exists():
        for domain_entry in domains_dir.iterdir():
            if not domain_entry.is_dir():
                continue
            ideas_dir = domain_entry / "ideas"
            if ideas_dir.exists():
                for f in ideas_dir.glob("IDEA-*.md"):
                    m = _IDEA_NUM_PATTERN.match(f.name)
                    if m:
                        max_num = max(max_num, int(m.group(1)))
        logger.info(f"_max_idea_number: scanned wiki domains, max_num={max_num}")
    else:
        logger.info(f"_max_idea_number: domains_dir does not exist: {domains_dir}")

    logger.info(f"_max_idea_number: result={max_num}")
    return max_num


def _load_idea_template(vault_path: str) -> str | None:
    """Load idea template from vault/templates/idea.md.

    Returns template content as string, or None if the file does not exist
    or cannot be read.
    """
    template_path = Path(vault_path) / "templates" / "idea.md"
    logger.info(f"_load_idea_template: attempting to load from {template_path}")
    try:
        content = template_path.read_text(encoding="utf-8")
        logger.info(f"_load_idea_template: loaded template ({len(content)} chars)")
        return content
    except FileNotFoundError:
        logger.warning(f"_load_idea_template: template not found at {template_path}")
        return None
    except Exception as e:
        logger.error(f"_load_idea_template: failed to read {template_path}: {e}")
        return None


def _build_signal_idea_content(
    idea_id: str,
    idea_data: dict,
    today: str,
    readiness_pct: int,
    raw_filename: str,
    analysis_text: str,
    related: str | None,
) -> str:
    """Build wiki idea content as fallback when no template is available.

    Generates full markdown with YAML frontmatter (status="Сигнал") and
    body sections: Проблема, Решение, Анализ.
    """
    domain = idea_data.get("domain", "general")
    title = idea_data.get("title", "Без названия")
    logger.info(f"_build_signal_idea_content: building for {idea_id}, domain={domain}")

    related_line = f'related: "{related}"\n' if related else ""

    frontmatter = (
        f"---\n"
        f'id: "{idea_id}"\n'
        f"type: idea\n"
        f"domain: {domain}\n"
        f'status: "Сигнал"\n'
        f"source: signal\n"
        f'signal_ref: "{raw_filename}"\n'
        f'signal_date: "{idea_data.get("signal_date", today)}"\n'
        f'signal_source: "{idea_data.get("signal_source", "")}"\n'
        f"{related_line}"
        f"readiness: {readiness_pct}%\n"
        f'created: "{today}"\n'
        f'updated: "{today}"\n'
        f"relevance: 1.0\n"
        f"tier: active\n"
        f'last_accessed: "{today}"\n'
        f"access_count: 0\n"
        f"tags:\n"
        f"  - idea\n"
        f"  - signal\n"
        f"---\n"
    )

    body = (
        f"\n# {title}\n\n"
        f"## Проблема\n\n{idea_data.get('problem', '')}\n\n"
        f"## Решение\n\n{idea_data.get('solution', '')}\n\n"
        f"## Анализ\n\n{analysis_text}\n"
    )

    content = frontmatter + body
    logger.info(f"_build_signal_idea_content: built content ({len(content)} chars)")
    return content


def _fill_template_for_signal(
    template: str,
    idea_id: str,
    idea_data: dict,
    today: str,
    readiness_pct: int,
    raw_filename: str,
    analysis_text: str,
    related: str | None,
) -> str:
    """Fill idea.md template for a signal idea via regex replacements.

    Replaces frontmatter fields and fills body sections (Проблема, Решение, Анализ).
    If frontmatter block is not found in template, falls back to _build_signal_idea_content().
    """
    domain = idea_data.get("domain", "general")
    title = idea_data.get("title", "Без названия")
    logger.info(f"_fill_template_for_signal: filling template for {idea_id}")

    # Match frontmatter block
    fm_match = re.match(r"(---\s*\n)(.*?)(\n---)", template, re.DOTALL)
    if not fm_match:
        logger.warning("_fill_template_for_signal: no frontmatter block found, using fallback")
        return _build_signal_idea_content(
            idea_id, idea_data, today, readiness_pct,
            raw_filename, analysis_text, related,
        )

    prefix = fm_match.group(1)
    fm_body = fm_match.group(2)
    suffix = fm_match.group(3)
    rest = template[fm_match.end():]

    # Replace frontmatter fields
    replacements = [
        (r"^id:.*$", f'id: "{idea_id}"'),
        (r"^domain:.*$", f"domain: {domain}"),
        (r"^status:.*$", 'status: "Сигнал"'),
        (r"^source:.*$", "source: signal"),
        (r"^readiness:.*$", f"readiness: {readiness_pct}%"),
        (r"^created:.*$", f'created: "{today}"'),
        (r"^updated:.*$", f'updated: "{today}"'),
    ]
    for pattern, replacement in replacements:
        fm_body = re.sub(pattern, replacement, fm_body, count=1, flags=re.MULTILINE)

    logger.info("_fill_template_for_signal: replaced frontmatter fields")

    # Add signal-specific fields
    signal_fields = (
        f'signal_ref: "{raw_filename}"\n'
        f'signal_date: "{idea_data.get("signal_date", today)}"\n'
        f'signal_source: "{idea_data.get("signal_source", "")}"\n'
    )
    if related:
        signal_fields += f'related: "{related}"\n'

    # Insert before tags:
    if re.search(r"^tags:", fm_body, re.MULTILINE):
        fm_body = re.sub(
            r"^(tags:)", signal_fields + r"\1",
            fm_body, count=1, flags=re.MULTILINE,
        )
    else:
        fm_body = fm_body.rstrip() + "\n" + signal_fields

    # Decay fields
    decay_block = (
        f"relevance: 1.0\ntier: active\n"
        f'last_accessed: "{today}"\naccess_count: 0'
    )
    if "relevance:" not in fm_body:
        if re.search(r"^tags:", fm_body, re.MULTILINE):
            fm_body = re.sub(
                r"^(tags:)", decay_block + "\n" + r"\1",
                fm_body, count=1, flags=re.MULTILINE,
            )
        else:
            fm_body = fm_body.rstrip() + "\n" + decay_block

    # Tags
    tags_yaml = "tags:\n  - idea\n  - signal"
    fm_body = re.sub(
        r"^tags:.*?(?=\n[a-z]|\n---|\Z)",
        tags_yaml,
        fm_body,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )

    content = prefix + fm_body + suffix + rest

    # Fill title (H1)
    h1_match = re.search(r"^# .+$", content, re.MULTILINE)
    if h1_match:
        content = content[:h1_match.start()] + f"# {title}" + content[h1_match.end():]

    # Fill source/raw_ref placeholders
    content = content.replace("{{source}}", "signal")
    content = content.replace("{{raw_ref}}", f"raw/inbound/ideas/{raw_filename}")

    # Fill sections Проблема/Решение
    for field_name, heading in [("problem", "## Проблема"), ("solution", "## Решение")]:
        value = idea_data.get(field_name, "").strip()
        if value:
            section_pattern = rf"({heading}\s*\n)(<!-- .*?-->\s*\n)?"
            match = re.search(section_pattern, content, re.DOTALL)
            if match:
                insert_pos = match.end()
                content = content[:insert_pos] + f"{value}\n" + content[insert_pos:]

    # Fill section Анализ
    if analysis_text:
        analysis_pattern = r"(## Анализ\s*\n)(<!-- .*?-->\s*\n)?"
        match = re.search(analysis_pattern, content, re.DOTALL)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + f"{analysis_text}\n" + content[insert_pos:]

    logger.info(f"_fill_template_for_signal: completed ({len(content)} chars)")
    return content


def _create_wiki_signal_idea(
    vault_path: str,
    idea_data: dict,
    analysis_text: str,
    raw_filename: str,
    today: str,
    related: str | None = None,
) -> str:
    """Create wiki copy of a signal idea with status 'Сигнал'.

    Generates sequential IDEA-NNNN ID, loads template (or uses fallback),
    writes wiki file to wiki/domains/{domain}/ideas/, updates wiki index.

    Returns wiki_filename (IDEA-NNNN-date_slug.md).
    Raises Exception on failure.
    """
    domain = idea_data.get("domain", "general")
    title = idea_data.get("title", "Без названия")
    logger.info(f"_create_wiki_signal_idea: starting for domain={domain}, title='{title[:60]}'")

    # 1. Generate IDEA-NNNN
    next_num = _max_idea_number(vault_path) + 1
    idea_id = f"IDEA-{next_num:04d}"
    logger.info(f"_create_wiki_signal_idea: generated {idea_id}")

    # 2. Try to load template
    template = _load_idea_template(vault_path)

    # 3. Calculate readiness (problem + solution = 2 out of 9 fields)
    filled_count = sum(
        1 for k in ("problem", "solution")
        if idea_data.get(k, "").strip()
    )
    readiness_pct = int((filled_count / 9) * 100)
    logger.info(f"_create_wiki_signal_idea: readiness={readiness_pct}%")

    # 4. Build content
    if template:
        logger.info("_create_wiki_signal_idea: using template")
        content = _fill_template_for_signal(
            template, idea_id, idea_data, today, readiness_pct,
            raw_filename, analysis_text, related,
        )
    else:
        logger.info("_create_wiki_signal_idea: using fallback (no template)")
        content = _build_signal_idea_content(
            idea_id, idea_data, today, readiness_pct,
            raw_filename, analysis_text, related,
        )

    # 5. Generate wiki filename
    slug = re.sub(r"[^a-zA-Zа-яА-Яё0-9]", "-", title)[:50]
    slug = re.sub(r"-+", "-", slug).strip("-")
    wiki_filename = f"IDEA-{next_num:04d}-{today}_{slug}.md"
    logger.info(f"_create_wiki_signal_idea: wiki_filename={wiki_filename}")

    # 6. Write to wiki/domains/{domain}/ideas/
    wiki_dir = Path(vault_path) / "wiki" / "domains" / domain / "ideas"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    wiki_path = wiki_dir / wiki_filename

    try:
        wiki_path.write_text(content, encoding="utf-8")
        logger.info(f"_create_wiki_signal_idea: wrote wiki idea to {wiki_path}")
    except Exception as e:
        logger.error(f"_create_wiki_signal_idea: failed to write {wiki_path}: {e}")
        raise

    # 7. Update wiki index (non-critical)
    try:
        _update_wiki_index(vault_path, domain)
        logger.info(f"_create_wiki_signal_idea: wiki index updated for domain={domain}")
    except Exception as e:
        logger.warning(f"_create_wiki_signal_idea: wiki index update failed (non-critical): {e}")

    logger.info(f"_create_wiki_signal_idea: completed, returning {wiki_filename}")
    return wiki_filename


def _update_wiki_index(vault_path: str, domain: str) -> None:
    """Append a SIGNAL_CREATE entry to wiki/domains/{domain}/ideas/log.md.

    Creates the log file with header if it does not exist.
    Non-critical operation: errors are logged but not raised.
    """
    ideas_dir = Path(vault_path) / "wiki" / "domains" / domain / "ideas"
    if not ideas_dir.exists():
        logger.info(f"_update_wiki_index: ideas_dir does not exist: {ideas_dir}")
        return

    log_path = ideas_dir / "log.md"
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    entry = f"[{timestamp}] SIGNAL_CREATE -> ok\n"

    try:
        if log_path.exists():
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
            logger.info(f"_update_wiki_index: appended entry to {log_path}")
        else:
            header = (
                "---\ntype: log\n"
                f"domain: {domain}\n"
                "artifact_type: ideas\n"
                "---\n\n"
                "# Change Log\n\n"
            )
            log_path.write_text(header + entry, encoding="utf-8")
            logger.info(f"_update_wiki_index: created log file at {log_path}")
    except Exception as e:
        logger.warning(f"_update_wiki_index: log update failed: {e}")


# ---------------------------------------------------------------------------
# Signal extraction (BL-203)
# ---------------------------------------------------------------------------


def extract_signals(
    report_path: Path,
    vault_path: str,
    business_context: str,
    config: Any,
) -> list[SignalData]:
    """Extract 1-N signals from analytical report via LLM (BL-203).

    1. Read report markdown from report_path
    2. Load signal_extract.txt prompt
    3. Call LLM via call_detailed(operation="signal_extract")
    4. Parse JSON response into list[SignalData]
    5. Validate required fields, filter invalid entries
    """
    logger.info(f"extract_signals: starting for report_path={report_path}")

    # 1. Read report content
    try:
        report_content = report_path.read_text(encoding="utf-8")
        logger.info(f"extract_signals: loaded report ({len(report_content)} chars)")
    except Exception as e:
        logger.error(f"extract_signals: failed to read report: {e}")
        return []

    # 2. Build prompt
    template = _load_prompt("signal_extract")
    if not template:
        logger.error("extract_signals: template signal_extract.txt is empty or missing")
        return []

    prompt = template.replace("{business_context}", business_context)
    prompt = prompt.replace("{report_content}", report_content)
    logger.info(f"extract_signals: built prompt ({len(prompt)} chars)")

    # 3. LLM call
    messages = [{"role": "user", "content": prompt}]

    try:
        logger.info("extract_signals: calling LLM, operation=signal_extract")
        response, meta = call_detailed(
            operation="signal_extract",
            messages=messages,
            max_tokens=4000,
            timeout=90,
        )
        logger.info(
            f"extract_signals: LLM call succeeded, "
            f"provider={meta.get('used', 'unknown')}, response_len={len(response)}"
        )
    except Exception as e:
        logger.error(f"extract_signals: LLM call failed: {e}")
        return []

    # 4. Parse JSON response
    parsed = _parse_json_response(response)
    if parsed is None:
        logger.error("extract_signals: JSON parse failed")
        return []

    raw_signals = parsed.get("signals", [])
    if not raw_signals:
        no_reason = parsed.get("no_signals_reason", "unknown")
        logger.info(f"extract_signals: no signals extracted, reason: {no_reason}")
        return []

    # 5. Validate and convert to SignalData
    signals: list[SignalData] = []
    for i, raw in enumerate(raw_signals):
        if not isinstance(raw, dict):
            logger.warning(f"extract_signals: signal[{i}] is not a dict, skipping")
            continue

        title = raw.get("title", "")
        analysis = raw.get("analysis", "")
        threat_level = raw.get("threat_level", "low")
        recommended_action = raw.get("recommended_action", "")

        if not title or not analysis:
            logger.warning(f"extract_signals: signal[{i}] missing title or analysis, skipping")
            continue

        if threat_level not in ("low", "medium", "high"):
            threat_level = "low"

        draft_idea = raw.get("draft_idea")
        if draft_idea is not None and not isinstance(draft_idea, dict):
            draft_idea = None

        domain = raw.get("domain", "general")
        priority_hint = raw.get("priority_hint", "medium")
        if priority_hint not in ("low", "medium", "high"):
            priority_hint = "medium"

        rationale = raw.get("rationale", "")

        signal = SignalData(
            title=title,
            analysis=analysis,
            threat_level=threat_level,
            recommended_action=recommended_action,
            draft_idea=draft_idea,
            domain=domain,
            priority_hint=priority_hint,
            rationale=rationale,
        )
        signals.append(signal)
        logger.info(f"extract_signals: signal[{i}] '{title[:40]}' validated")

    logger.info(f"extract_signals: extracted {len(signals)} valid signals from {len(raw_signals)} raw")
    return signals


# ---------------------------------------------------------------------------
# Signal dispatch
# ---------------------------------------------------------------------------


def dispatch_signal(
    signal_data: SignalData,
    report_ref: str,
    item: dict,
    scoring: ScoringResult,
    vault_path: str,
    run_id: str,
    dry_run: bool = False,
) -> str | None:
    """Create Signal artifact: raw JSON + wiki Markdown (BL-203, AC-01, AC-02, AC-15, AC-16).

    Returns signal_id (filename without extension) or None on error.
    """
    title = signal_data.title or "untitled"
    logger.info(f"dispatch_signal: starting for '{title[:50]}', dry_run={dry_run}")

    # 1. Generate slug and signal_id
    slug = re.sub(r"[^a-zA-Zа-яА-Яё0-9]", "-", title)[:50]
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    if not slug:
        slug = "signal"

    today = datetime.now().strftime("%Y-%m-%d")
    signal_id = f"{today}-{slug}"
    logger.info(f"dispatch_signal: signal_id={signal_id}")

    if dry_run:
        logger.info(f"dispatch_signal: dry_run mode, skipping file writes for {signal_id}")
        return signal_id

    # 2. Import vault_paths for directory resolution
    from shared import vault_paths

    # 3. Create raw JSON
    raw_dir = vault_paths.raw_signals()
    raw_path = raw_dir / f"{signal_id}.json"

    raw_data = {
        "title": signal_data.title,
        "source_url": item.get("source_url", ""),
        "source": item.get("source", ""),
        "relevance_score": scoring.relevance,
        "analysis": signal_data.analysis,
        "threat_level": signal_data.threat_level,
        "recommended_action": signal_data.recommended_action,
        "draft_idea": signal_data.draft_idea,
        "signal_date": today,
        "run_id": run_id,
        "status": "pending",
        "report_ref": report_ref,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        raw_path.write_text(
            json.dumps(raw_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"dispatch_signal: wrote raw JSON to {raw_path}")
    except Exception as e:
        logger.error(f"dispatch_signal: failed to write raw JSON {raw_path}: {e}")
        return None

    # 4. Create wiki Markdown
    wiki_dir = vault_paths.wiki_signals()
    wiki_path = wiki_dir / f"{signal_id}.md"

    # Build draft idea section
    draft_idea_section = ""
    if signal_data.draft_idea:
        di = signal_data.draft_idea
        draft_idea_section = (
            f"\n## Черновик идеи\n\n"
            f"**Название:** {di.get('title', '')}\n"
            f"**Проблема:** {di.get('problem', '')}\n"
            f"**Решение:** {di.get('solution', '')}\n"
            f"**Домен:** {di.get('domain', 'general')}\n"
        )

    wiki_content = (
        f"---\n"
        f"type: signal\n"
        f'title: "{signal_data.title}"\n'
        f"status: pending\n"
        f'source_url: "{item.get("source_url", "")}"\n'
        f'source: "{item.get("source", "")}"\n'
        f"relevance_score: {scoring.relevance}\n"
        f"threat_level: {signal_data.threat_level}\n"
        f'signal_date: "{today}"\n'
        f'run_id: "{run_id}"\n'
        f'report_ref: "{report_ref}"\n'
        f'created: "{today}"\n'
        f'result_ref: ""\n'
        f"---\n\n"
        f"# {signal_data.title}\n\n"
        f"## Анализ\n\n{signal_data.analysis}\n\n"
        f"## Рекомендация\n\n{signal_data.recommended_action}\n"
        f"{draft_idea_section}"
    )

    try:
        wiki_path.write_text(wiki_content, encoding="utf-8")
        logger.info(f"dispatch_signal: wrote wiki MD to {wiki_path}")
    except Exception as e:
        logger.error(f"dispatch_signal: failed to write wiki MD {wiki_path}: {e}")
        return None

    logger.info(
        f"dispatch_signal: completed, signal_id={signal_id}, "
        f"raw={raw_path}, wiki={wiki_path}"
    )
    return signal_id


# ---------------------------------------------------------------------------
# Idea dispatch
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
        logger.error("dispatch_idea: no idea_draft in analysis, returning None")
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
    raw_filename = f"{today}-signal-{slug}.md"

    ideas_dir = Path(vault_path) / "raw" / "inbound" / "ideas"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    raw_path = ideas_dir / raw_filename

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
        raw_path.write_text(content, encoding="utf-8")
        logger.info(f"dispatch_idea: wrote raw idea to {raw_path}")
    except Exception as e:
        logger.error(f"dispatch_idea: failed to write raw idea file: {e}")
        return None

    # === BL-202: создание wiki-копии со статусом "Сигнал" ===
    wiki_ref = None
    try:
        wiki_ref = _create_wiki_signal_idea(
            vault_path=vault_path,
            idea_data=idea_data,
            analysis_text=analysis.analysis,
            raw_filename=raw_filename,
            today=today,
            related=idea_data.get("related"),
        )
        logger.info(f"dispatch_idea: wiki copy created: {wiki_ref}")
    except Exception as e:
        logger.error(f"dispatch_idea: wiki copy failed (non-fatal): {e}")

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
            logger.info("dispatch_idea: Telegram notification sent")
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
                "result_ref": raw_filename,
                "wiki_ref": wiki_ref or "",
                "quality_score": "",
            }
        ],
    )

    logger.info(f"dispatch_idea: completed, raw={raw_filename}, wiki={wiki_ref}")
    return raw_filename


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
        logger.error("dispatch_report: no report_brief in analysis, returning None")
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
            logger.info("dispatch_report: Telegram notification sent")
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
