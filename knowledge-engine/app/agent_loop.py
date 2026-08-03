from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class LoopIteration:
    """Single iteration record within the AgentLoop retry cycle."""

    attempt: int
    result: dict
    quality: Any  # QualityResult at runtime
    context_additions: str = ""
    escalated: bool = False
    critique_text: str | None = None


class AgentLoop:
    """Retry-with-critique loop for iterative quality improvement.

    Runs step_fn up to max_iterations times, checking quality after each.
    On failure, injects critique into kwargs so the next call can improve.
    On the penultimate iteration, sets escalation_group for routing.
    """

    def __init__(self, max_iterations: int = 3):
        self.max_iterations = max_iterations
        self.history: list[LoopIteration] = []
        logger.info(f"AgentLoop initialized with max_iterations={max_iterations}")

    def run(
        self,
        step_fn: Callable[..., dict],
        quality_fn: Callable[[dict], Any],
        escalation_group: str = "signal_escalation",
        **kwargs: Any,
    ) -> tuple[dict, list[LoopIteration]]:
        """Retry-with-critique cycle.

        On each iteration:
        1. Call step_fn(**kwargs) -> result
        2. Call quality_fn(result) -> QualityResult
        3. If passed=True -> return (result, history)
        4. If passed=False and iteration < max_iterations:
           a. kwargs["critique"] = _build_critique(prev_iteration)
           b. If last iteration: kwargs["operation_group"] = escalation_group
        5. All attempts exhausted:
           - Return result with max quality.score
           - Set result["_quality_warning"] = True
           - Set result["_attempts"] = len(history)
        """
        self.history = []
        best_result: dict | None = None
        best_score = -1

        logger.info(f"AgentLoop.run() started, max_iterations={self.max_iterations}")

        for i in range(self.max_iterations):
            attempt = i + 1
            logger.info(f"AgentLoop iteration {attempt}/{self.max_iterations} starting")

            try:
                result = step_fn(**kwargs)
                logger.info(f"AgentLoop iteration {attempt} step_fn completed successfully")
            except Exception as e:
                logger.error(f"AgentLoop iteration {attempt} step_fn error: {e}")
                iteration = LoopIteration(
                    attempt=attempt,
                    result={},
                    quality=_make_failed_quality(str(e)),
                    escalated="operation_group" in kwargs
                        and kwargs["operation_group"] == escalation_group,
                    critique_text=kwargs.get("critique"),
                )
                self.history.append(iteration)
                kwargs["critique"] = self._build_critique(iteration)
                if attempt == self.max_iterations - 1:
                    kwargs["operation_group"] = escalation_group
                    logger.info(
                        f"AgentLoop escalating to {escalation_group} for final iteration"
                    )
                continue

            quality = quality_fn(result)
            iteration = LoopIteration(
                attempt=attempt,
                result=result,
                quality=quality,
                escalated="operation_group" in kwargs
                    and kwargs["operation_group"] == escalation_group,
                critique_text=kwargs.get("critique"),
            )
            self.history.append(iteration)

            score = quality.score if hasattr(quality, "score") else 0
            passed = quality.passed if hasattr(quality, "passed") else False
            logger.info(
                f"AgentLoop iteration {attempt}: score={score}, passed={passed}"
            )

            if score > best_score:
                best_score = score
                best_result = result

            if passed:
                logger.info(f"AgentLoop passed on iteration {attempt}")
                return result, self.history

            # Prepare next iteration with critique
            kwargs["critique"] = self._build_critique(iteration)
            logger.info(
                f"AgentLoop iteration {attempt} failed, critique injected for next attempt"
            )
            if attempt == self.max_iterations - 1:
                kwargs["operation_group"] = escalation_group
                logger.info(
                    f"AgentLoop escalating to {escalation_group} for final iteration"
                )

        # All attempts exhausted
        logger.warning(
            f"AgentLoop exhausted {self.max_iterations} iterations, best score={best_score}"
        )
        if best_result is not None:
            best_result["_quality_warning"] = True
            best_result["_attempts"] = len(self.history)
            logger.info(
                f"AgentLoop returning best result with _quality_warning=True, "
                f"_attempts={len(self.history)}"
            )
        else:
            logger.warning("AgentLoop has no successful result to return")

        return best_result or {}, self.history

    def _build_critique(self, prev: LoopIteration) -> str:
        """Build critique string from the previous failed iteration."""
        issues = (
            "; ".join(prev.quality.issues)
            if hasattr(prev.quality, "issues")
            else "unknown"
        )
        score = prev.quality.score if hasattr(prev.quality, "score") else 0
        critique = (
            f"Предыдущая попытка (score {score}/10) не прошла проверку качества. "
            f"Проблемы: {issues}. "
            "Исправь эти конкретные проблемы. Будь конкретнее. "
            "Назови конкретный компонент/модуль Суточно.ру, который затронут. "
            "В idea_draft.solution укажи действие, а не 'изучить' или 'рассмотреть'. "
            "В report_brief.questions формулируй вопросы, на которые можно ответить "
            "из открытых источников."
        )
        logger.info(f"AgentLoop built critique for attempt {prev.attempt}: score={score}")
        return critique

    def reset(self) -> None:
        """Clear iteration history."""
        self.history = []
        logger.info("AgentLoop history reset")


def _make_failed_quality(error_msg: str) -> Any:
    """Create a simple object mimicking QualityResult for failed iterations."""

    class _FailedQuality:
        passed = False
        score = 0
        issues = [error_msg]
        improvements: dict = {}

    logger.info(f"Created _FailedQuality for error: {error_msg}")
    return _FailedQuality()
