from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared import vault_paths
from shared.frontmatter_utils import read_frontmatter
from shared.llm_client import call_detailed

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    """Result of a quality check (analysis, idea, or report completeness)."""

    passed: bool
    score: int  # 1-10
    issues: list[str] = field(default_factory=list)
    improvements: dict = field(default_factory=dict)


@dataclass
class DedupResult:
    """Result of a deduplication check against existing ideas."""

    is_duplicate: bool
    similar_to: str | None = None  # IDEA-NNNN
    similarity: int = 0  # 0-10
    reason: str = ""


DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "static-metadata": [
        "справочник", "классификатор", "атрибут", "метаобъект",
        "reference-data", "catalog", "enum",
    ],
    "suggester": [
        "автокомплит", "подсказка", "typeahead", "suggester", "префикс",
    ],
    "search-engine": [
        "поиск", "релевантность", "индексация", "фильтрация",
        "ранжирование", "выдача",
    ],
    "partner-search-engine": [
        "партнёр", "поставщик", "b2b", "supplier", "подключение партнёра",
    ],
    "general": [],
}


class QualityGate:
    """Gate that validates analysis, ideas, reports and deduplication via LLM + rules."""

    def __init__(self, vault_path: str, config: Any) -> None:
        """Initialize QualityGate.

        Args:
            vault_path: root path to the Obsidian vault.
            config: ModeratorConfig (or any object with needed fields).
        """
        self.vault_path = vault_path
        self.config = config
        self._ideas_cache: list[dict] | None = None
        logger.info(f"QualityGate initialized, vault_path={vault_path}")

    # ------------------------------------------------------------------
    # Public checks
    # ------------------------------------------------------------------

    def check_analysis_quality(self, analysis: dict) -> QualityResult:
        """Check quality of an analysis result via LLM (AC-17).

        Supports two analysis shapes:
        - analysis with ``idea_draft`` key
        - analysis with ``report_brief`` key
        """
        logger.info(f"check_analysis_quality called, keys={list(analysis.keys())}")

        title, problem, solution, domain = self._extract_fields(analysis)
        logger.info(
            f"check_analysis_quality extracted fields: title={title!r}, "
            f"domain={domain!r}"
        )

        return self._run_quality_llm(title, problem, solution, domain)

    def check_idea_quality(self, idea: dict) -> QualityResult:
        """Check idea quality against 5 criteria via LLM (AC-21).

        Criteria (0-2 points each, max 10):
        1. Specificity  2. Product binding  3. Rationale
        4. Feasibility  5. Value
        """
        logger.info(f"check_idea_quality called, title={idea.get('title', '')!r}")

        title = idea.get("title", "")
        problem = idea.get("problem", "")
        solution = idea.get("solution", "")
        domain = idea.get("domain", "general")

        return self._run_quality_llm(title, problem, solution, domain)

    def check_dedup(self, idea: dict) -> DedupResult:
        """Dedup check: keyword overlap pre-filter + LLM confirmation (AC-20)."""
        logger.info(f"check_dedup called, title={idea.get('title', '')!r}")

        existing = self._load_existing_ideas()
        logger.info(f"check_dedup loaded {len(existing)} existing ideas")

        candidates = self._keyword_overlap(idea, existing, top_n=5)
        logger.info(f"check_dedup found {len(candidates)} keyword-overlap candidates")

        if not candidates:
            logger.info(f"check_dedup: no candidates, idea is unique")
            return DedupResult(is_duplicate=False)

        # Build prompt
        template = self._load_prompt("dedup_check")
        if not template:
            logger.error(f"check_dedup: dedup_check.txt prompt missing, assuming unique")
            return DedupResult(is_duplicate=False)

        candidates_list = "\n".join(
            f"- {c.get('id', 'unknown')}: {c.get('title', '')} ({c.get('domain', '')})"
            for c in candidates
        )
        prompt = template.replace("{candidates_list}", candidates_list)
        prompt = prompt.replace("{title}", idea.get("title", ""))
        prompt = prompt.replace("{problem}", idea.get("problem", ""))
        prompt = prompt.replace("{solution}", idea.get("solution", ""))

        messages = [{"role": "user", "content": prompt}]

        try:
            logger.info(f"check_dedup calling LLM, operation=dedup_check")
            response, meta = call_detailed(
                operation="dedup_check",
                messages=messages,
                max_tokens=500,
                timeout=30,
            )
            logger.info(
                f"check_dedup LLM response received, "
                f"provider={meta.get('used', 'unknown')}"
            )
        except Exception as e:
            logger.error(f"check_dedup LLM call failed: {e}")
            return DedupResult(is_duplicate=False, reason=f"LLM check failed: {e}")

        parsed = self._parse_json_response(response)
        if not parsed:
            logger.error(f"check_dedup failed to parse LLM response")
            return DedupResult(is_duplicate=False, reason="Failed to parse LLM response")

        similarity = int(parsed.get("similarity", 0))
        similar_to = parsed.get("similar_to")
        reason = parsed.get("reason", "")

        dedup_threshold = getattr(self.config, "dedup_similarity_threshold", 8)
        is_dup = similarity >= dedup_threshold

        logger.info(
            f"check_dedup result: similarity={similarity}, threshold={dedup_threshold}, "
            f"is_duplicate={is_dup}, similar_to={similar_to}"
        )

        return DedupResult(
            is_duplicate=is_dup,
            similar_to=similar_to,
            similarity=similarity,
            reason=reason,
        )

    def check_report_completeness(
        self, report_path: Path, original_questions: list[str]
    ) -> QualityResult:
        """Check report completeness via LLM (AC-22)."""
        logger.info(
            f"check_report_completeness called, report={report_path}, "
            f"questions_count={len(original_questions)}"
        )

        # Load and truncate report
        report_content = self._load_report_content(report_path)
        if not report_content:
            logger.warning(f"check_report_completeness: empty report at {report_path}")
            return QualityResult(
                passed=False,
                score=1,
                issues=["Report file is empty or unreadable"],
            )

        # Build prompt
        template = self._load_prompt("completeness_check")
        if not template:
            logger.error(
                f"check_report_completeness: completeness_check.txt prompt missing"
            )
            return QualityResult(
                passed=True, score=5, issues=["Completeness prompt missing"]
            )

        questions_text = "\n".join(
            f"{i + 1}. {q}" for i, q in enumerate(original_questions)
        )
        prompt = template.replace("{original_questions}", questions_text)
        prompt = prompt.replace("{report_content_first_3000_tokens}", report_content)

        messages = [{"role": "user", "content": prompt}]

        try:
            logger.info(
                f"check_report_completeness calling LLM, operation=completeness_check"
            )
            response, meta = call_detailed(
                operation="completeness_check",
                messages=messages,
                max_tokens=500,
                timeout=30,
            )
            logger.info(
                f"check_report_completeness LLM response received, "
                f"provider={meta.get('used', 'unknown')}"
            )
        except Exception as e:
            logger.error(f"check_report_completeness LLM call failed: {e}")
            return QualityResult(
                passed=True, score=5, issues=[f"LLM check failed: {e}"]
            )

        parsed = self._parse_json_response(response)
        if not parsed:
            logger.error(
                f"check_report_completeness failed to parse LLM response"
            )
            return QualityResult(
                passed=True, score=5, issues=["Failed to parse LLM response"]
            )

        completeness = int(parsed.get("completeness", 5))
        threshold = getattr(self.config, "completeness_threshold", 6)

        # Determine pass/fail based on thresholds
        if completeness >= threshold:
            passed = True
        elif completeness >= 4:
            passed = True  # pass with quality_warning
        else:
            passed = False  # AgentLoop will retry

        issues: list[str] = []
        unanswered = parsed.get("unanswered_questions", [])
        if unanswered:
            issues.append(f"Unanswered questions: {unanswered}")

        unsourced = parsed.get("unsourced_claims_count", 0)
        if unsourced:
            issues.append(f"Unsourced claims: {unsourced}")

        improvements: dict[str, Any] = {
            "unanswered_questions": unanswered,
            "has_enough_for_ideas": parsed.get("has_enough_for_ideas", False),
        }

        if completeness >= 4 and completeness < threshold:
            improvements["_quality_warning"] = True
            logger.info(
                f"check_report_completeness: marginal pass "
                f"(completeness={completeness}, threshold={threshold})"
            )

        logger.info(
            f"check_report_completeness result: completeness={completeness}, "
            f"threshold={threshold}, passed={passed}"
        )

        return QualityResult(
            passed=passed,
            score=completeness,
            issues=issues,
            improvements=improvements,
        )

    def check_domain(self, idea: dict) -> tuple[bool, str | None]:
        """Rule-based domain check via keyword matching (AC-23, AC-24). No LLM."""
        idea_domain = idea.get("domain", "general")
        logger.info(
            f"check_domain called, idea_domain={idea_domain!r}, "
            f"title={idea.get('title', '')!r}"
        )

        # Build text to search keywords in
        text = " ".join([
            idea.get("title", ""),
            idea.get("problem", ""),
            idea.get("solution", ""),
        ]).lower()

        # Score each domain by keyword hits
        scores: dict[str, int] = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if not keywords:
                continue
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > 0:
                scores[domain] = score

        logger.info(f"check_domain keyword scores: {scores}")

        # If no keywords matched any domain, trust the LLM assignment
        if not scores:
            logger.info(
                f"check_domain: no keyword matches, trusting LLM domain={idea_domain}"
            )
            return (True, None)

        best_domain = max(scores, key=scores.get)  # type: ignore[arg-type]

        # If the idea's domain matches the best keyword-scored domain, it's correct
        if idea_domain == best_domain:
            logger.info(
                f"check_domain: domain {idea_domain!r} matches best keyword domain"
            )
            return (True, None)

        # Domain mismatch detected
        auto_correct = getattr(self.config, "domain_auto_correct", False)
        if auto_correct:
            logger.info(
                f"check_domain: domain mismatch, auto_correct=True, "
                f"suggesting {best_domain!r} instead of {idea_domain!r}"
            )
            return (False, best_domain)

        # Auto-correct disabled -- trust the LLM
        logger.info(
            f"check_domain: domain mismatch detected "
            f"({idea_domain!r} vs {best_domain!r}), but auto_correct=False"
        )
        return (True, None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_fields(self, analysis: dict) -> tuple[str, str, str, str]:
        """Extract title/problem/solution/domain from analysis dict.

        Supports two shapes: idea_draft and report_brief.
        """
        if "idea_draft" in analysis:
            draft = analysis["idea_draft"]
            title = draft.get("title", "")
            problem = draft.get("problem", "")
            solution = draft.get("solution", "")
            domain = draft.get("domain", "general")
            logger.info(f"_extract_fields: using idea_draft shape")
        elif "report_brief" in analysis:
            brief = analysis["report_brief"]
            title = brief.get("topic", "")
            problem = "Нужен глубокий анализ"
            questions = brief.get("questions", [])
            solution = "; ".join(questions) if questions else ""
            domain = "general"
            logger.info(f"_extract_fields: using report_brief shape")
        else:
            title = analysis.get("title", "")
            problem = analysis.get("problem", "")
            solution = analysis.get("solution", "")
            domain = analysis.get("domain", "general")
            logger.info(f"_extract_fields: using flat dict shape (fallback)")

        return title, problem, solution, domain

    def _run_quality_llm(
        self, title: str, problem: str, solution: str, domain: str
    ) -> QualityResult:
        """Run the quality_check prompt through LLM and parse result."""
        template = self._load_prompt("quality_check")
        if not template:
            logger.error(f"_run_quality_llm: quality_check.txt prompt missing")
            return QualityResult(
                passed=True, score=5, issues=["Quality prompt missing"]
            )

        prompt = template.replace("{title}", title)
        prompt = prompt.replace("{problem}", problem)
        prompt = prompt.replace("{solution}", solution)
        prompt = prompt.replace("{domain}", domain)

        messages = [{"role": "user", "content": prompt}]

        try:
            logger.info(f"_run_quality_llm calling LLM, operation=quality_check")
            response, meta = call_detailed(
                operation="quality_check",
                messages=messages,
                max_tokens=500,
                timeout=30,
            )
            logger.info(
                f"_run_quality_llm LLM response received, "
                f"provider={meta.get('used', 'unknown')}"
            )
        except Exception as e:
            logger.error(f"_run_quality_llm LLM call failed: {e}")
            return QualityResult(
                passed=True, score=5, issues=[f"LLM check failed: {e}"]
            )

        parsed = self._parse_json_response(response)
        if not parsed:
            logger.error(f"_run_quality_llm failed to parse LLM response")
            return QualityResult(
                passed=True, score=5, issues=["Failed to parse LLM response"]
            )

        quality_score = int(parsed.get("quality_score", 5))
        llm_pass = parsed.get("pass", False)
        issues = parsed.get("issues", [])
        threshold = getattr(self.config, "quality_threshold", 6)

        passed = bool(llm_pass) and quality_score >= threshold

        improvements: dict[str, Any] = {}
        improved_title = parsed.get("improved_title")
        improved_solution = parsed.get("improved_solution")
        if improved_title:
            improvements["improved_title"] = improved_title
        if improved_solution:
            improvements["improved_solution"] = improved_solution

        logger.info(
            f"_run_quality_llm result: score={quality_score}, llm_pass={llm_pass}, "
            f"threshold={threshold}, passed={passed}, issues_count={len(issues)}"
        )

        return QualityResult(
            passed=passed,
            score=quality_score,
            issues=issues,
            improvements=improvements,
        )

    def _load_existing_ideas(self) -> list[dict]:
        """Load idea titles/descriptions from wiki/domains/*/ideas/*.md.

        Cached per run via self._ideas_cache.
        """
        if self._ideas_cache is not None:
            logger.info(
                f"_load_existing_ideas returning cached {len(self._ideas_cache)} ideas"
            )
            return self._ideas_cache

        logger.info(f"_load_existing_ideas loading from vault")
        ideas: list[dict] = []
        domains = vault_paths.all_domains()

        for domain in domains:
            ideas_dir = vault_paths.wiki_domain_dir(domain, "ideas")
            if not ideas_dir.exists():
                continue

            for md_file in sorted(ideas_dir.glob("*.md")):
                if md_file.name in ("index.md", "log.md"):
                    continue
                try:
                    meta, body = read_frontmatter(md_file)
                    idea_id = meta.get("id", md_file.stem)
                    title_line = ""
                    for line in body.split("\n"):
                        stripped = line.strip()
                        if stripped.startswith("# ") and not stripped.startswith("## "):
                            title_line = stripped[2:].strip()
                            break
                    title = title_line or meta.get("title", md_file.stem)

                    ideas.append({
                        "id": idea_id,
                        "title": title,
                        "status": meta.get("status", "inbox"),
                        "domain": domain,
                        "problem": meta.get("problem", ""),
                    })
                except Exception as e:
                    logger.warning(f"_load_existing_ideas failed to read {md_file}: {e}")

        self._ideas_cache = ideas
        logger.info(f"_load_existing_ideas loaded {len(ideas)} ideas from vault")
        return ideas

    def _keyword_overlap(
        self, idea: dict, existing: list[dict], top_n: int = 5
    ) -> list[dict]:
        """Filter top-N candidates by word overlap in title + problem."""
        logger.info(
            f"_keyword_overlap called, existing_count={len(existing)}, top_n={top_n}"
        )

        idea_words = self._extract_words(idea)
        if not idea_words:
            logger.info(f"_keyword_overlap: no words extracted from idea")
            return []

        scored: list[tuple[int, dict]] = []
        for ex in existing:
            ex_words = self._extract_words(ex)
            overlap = len(idea_words & ex_words)
            if overlap > 0:
                scored.append((overlap, ex))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [item for _, item in scored[:top_n]]

        logger.info(
            f"_keyword_overlap found {len(result)} candidates "
            f"(from {len(scored)} with any overlap)"
        )
        return result

    def _extract_words(self, item: dict) -> set[str]:
        """Extract meaningful words (length >= 3) from title + problem."""
        text = " ".join([
            item.get("title", ""),
            item.get("problem", ""),
        ]).lower()
        words = set(re.findall(r"[a-zA-Zа-яА-ЯёЁ]{3,}", text))
        return words

    def _load_report_content(self, report_path: Path) -> str:
        """Load report, strip frontmatter, truncate to ~3000 tokens (~12000 chars)."""
        logger.info(f"_load_report_content loading {report_path}")
        try:
            content = report_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"_load_report_content failed to read {report_path}: {e}")
            return ""

        # Strip frontmatter
        content = re.sub(
            r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL
        )

        # Truncate to ~3000 tokens (~12000 chars)
        max_chars = 12000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n[...report truncated...]"
            logger.info(f"_load_report_content truncated to {max_chars} chars")

        logger.info(f"_load_report_content loaded {len(content)} chars")
        return content.strip()

    def _load_prompt(self, name: str) -> str:
        """Load a prompt template from prompts/{name}.txt."""
        prompts_dir = Path(__file__).parent / "prompts"
        path = prompts_dir / f"{name}.txt"
        logger.info(f"_load_prompt loading {path}")
        try:
            content = path.read_text(encoding="utf-8")
            logger.info(f"_load_prompt loaded {name} ({len(content)} chars)")
            return content
        except FileNotFoundError:
            logger.error(f"_load_prompt: prompt file not found: {path}")
            return ""

    def _parse_json_response(self, text: str) -> dict | None:
        """Extract JSON from an LLM response.

        Supports: raw JSON, markdown code blocks, embedded JSON object.
        """
        logger.info(f"_parse_json_response parsing ({len(text)} chars)")

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

        # Try finding embedded JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
                logger.info(f"_parse_json_response: parsed from embedded object")
                return result
            except json.JSONDecodeError:
                pass

        logger.error(f"_parse_json_response: cannot parse JSON: {text[:200]}...")
        return None
