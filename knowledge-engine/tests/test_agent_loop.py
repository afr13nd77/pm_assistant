"""Tests for agent_loop module: AgentLoop retry-with-critique cycle."""
from __future__ import annotations

import pytest

from app.agent_loop import AgentLoop, LoopIteration, _make_failed_quality


class _FakeQuality:
    """Fake QualityResult for testing."""

    def __init__(self, passed: bool, score: int, issues: list[str] | None = None):
        self.passed = passed
        self.score = score
        self.issues = issues or []
        self.improvements = {}


class TestAgentLoopPassesOnFirstAttempt:
    def test_returns_result_and_single_iteration(self):
        """AC-17: AgentLoop.run() returns (result, history) when step passes."""
        loop = AgentLoop(max_iterations=3)
        step_fn = lambda **kw: {"answer": 42}
        quality_fn = lambda r: _FakeQuality(passed=True, score=9)

        result, history = loop.run(step_fn, quality_fn)

        assert result == {"answer": 42}
        assert len(history) == 1
        assert history[0].attempt == 1
        assert history[0].quality.passed is True

    def test_no_quality_warning_on_pass(self):
        """AC-17: Passed result should not have _quality_warning."""
        loop = AgentLoop(max_iterations=3)
        step_fn = lambda **kw: {"data": "ok"}
        quality_fn = lambda r: _FakeQuality(passed=True, score=10)

        result, _ = loop.run(step_fn, quality_fn)

        assert "_quality_warning" not in result


class TestAgentLoopRetryAndPass:
    def test_passes_on_second_attempt_with_critique(self):
        """AC-17: Loop retries and passes on second attempt."""
        call_count = 0

        def step_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"quality": "low"}
            return {"quality": "high", "critique_received": kwargs.get("critique", "")}

        qualities = [
            _FakeQuality(passed=False, score=3, issues=["too vague"]),
            _FakeQuality(passed=True, score=8),
        ]
        quality_iter = iter(qualities)
        quality_fn = lambda r: next(quality_iter)

        loop = AgentLoop(max_iterations=3)
        result, history = loop.run(step_fn, quality_fn)

        assert result["quality"] == "high"
        assert "critique_received" in result
        assert len(history) == 2
        assert history[0].quality.passed is False
        assert history[1].quality.passed is True


class TestAgentLoopExhaustion:
    def test_returns_best_result_with_warning(self):
        """AC-19: When all attempts exhausted, returns best result with _quality_warning=True."""
        scores = [2, 7, 5]
        score_iter = iter(scores)

        def step_fn(**kwargs):
            return {"attempt_data": True}

        def quality_fn(r):
            s = next(score_iter)
            return _FakeQuality(passed=False, score=s, issues=["needs work"])

        loop = AgentLoop(max_iterations=3)
        result, history = loop.run(step_fn, quality_fn)

        assert result["_quality_warning"] is True
        assert result["_attempts"] == 3
        assert len(history) == 3

    def test_returns_empty_dict_when_all_fail_with_exceptions(self):
        """AC-19: When all step_fn calls raise exceptions, returns empty dict."""

        def step_fn(**kwargs):
            raise RuntimeError("boom")

        loop = AgentLoop(max_iterations=2)
        result, history = loop.run(step_fn, lambda r: None)

        assert result == {}
        assert len(history) == 2


class TestEscalation:
    def test_escalation_group_set_on_penultimate_iteration(self):
        """AC-18: On penultimate iteration, kwargs['operation_group'] = escalation_group."""
        received_kwargs = []

        def step_fn(**kwargs):
            received_kwargs.append(dict(kwargs))
            return {"data": True}

        qualities = [
            _FakeQuality(passed=False, score=3, issues=["issue1"]),
            _FakeQuality(passed=False, score=4, issues=["issue2"]),
            _FakeQuality(passed=True, score=9),
        ]
        quality_iter = iter(qualities)

        loop = AgentLoop(max_iterations=3)
        loop.run(step_fn, lambda r: next(quality_iter))

        # After iteration 2 (penultimate, max-1=2), operation_group should be set
        # So iteration 3's kwargs should contain it
        assert received_kwargs[2].get("operation_group") == "signal_escalation"

    def test_custom_escalation_group(self):
        """AC-18: Custom escalation group is passed correctly."""
        received_kwargs = []

        def step_fn(**kwargs):
            received_kwargs.append(dict(kwargs))
            return {"data": True}

        qualities = [
            _FakeQuality(passed=False, score=2, issues=["bad"]),
            _FakeQuality(passed=False, score=3, issues=["still bad"]),
            _FakeQuality(passed=False, score=4, issues=["better but no"]),
        ]
        quality_iter = iter(qualities)

        loop = AgentLoop(max_iterations=3)
        loop.run(
            step_fn,
            lambda r: next(quality_iter),
            escalation_group="custom_escalation",
        )

        assert received_kwargs[2].get("operation_group") == "custom_escalation"


class TestBuildCritique:
    def test_critique_contains_issues_and_score(self):
        """AC-49: _build_critique contains specific fix instructions."""
        loop = AgentLoop()
        iteration = LoopIteration(
            attempt=1,
            result={},
            quality=_FakeQuality(
                passed=False,
                score=4,
                issues=["too vague", "no component named"],
            ),
        )

        critique = loop._build_critique(iteration)

        assert "score 4/10" in critique
        assert "too vague; no component named" in critique
        assert "Исправь" in critique
        assert "компонент/модуль Суточно.ру" in critique
        assert "idea_draft.solution" in critique
        assert "report_brief.questions" in critique

    def test_critique_handles_missing_issues(self):
        """AC-49: Critique works even when quality has no issues attr."""

        class _MinimalQuality:
            passed = False
            score = 1

        loop = AgentLoop()
        iteration = LoopIteration(
            attempt=1,
            result={},
            quality=_MinimalQuality(),
        )

        critique = loop._build_critique(iteration)

        assert "score 1/10" in critique
        # Issues should fall back to "unknown"
        assert "unknown" in critique


class TestMakeFailedQuality:
    def test_creates_failed_quality_object(self):
        fq = _make_failed_quality("connection timeout")

        assert fq.passed is False
        assert fq.score == 0
        assert "connection timeout" in fq.issues
        assert fq.improvements == {}


class TestStepFnException:
    def test_exception_in_step_fn_creates_failed_iteration(self):
        """Exception in step_fn should not crash the loop."""
        call_count = 0

        def step_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("API unavailable")
            return {"recovered": True}

        qualities = [_FakeQuality(passed=True, score=8)]
        quality_iter = iter(qualities)

        loop = AgentLoop(max_iterations=3)
        result, history = loop.run(step_fn, lambda r: next(quality_iter))

        assert result["recovered"] is True
        assert len(history) == 2
        # First iteration: exception -> FailedQuality
        assert history[0].quality.passed is False
        assert history[0].quality.score == 0
        # Second iteration: success
        assert history[1].quality.passed is True


class TestReset:
    def test_reset_clears_history(self):
        loop = AgentLoop()
        loop.run(
            lambda **kw: {"x": 1},
            lambda r: _FakeQuality(passed=True, score=10),
        )
        assert len(loop.history) == 1

        loop.reset()
        assert len(loop.history) == 0


class TestLoopIteration:
    def test_dataclass_fields(self):
        iteration = LoopIteration(
            attempt=2,
            result={"key": "value"},
            quality=_FakeQuality(passed=True, score=9),
            context_additions="extra context",
        )

        assert iteration.attempt == 2
        assert iteration.result == {"key": "value"}
        assert iteration.quality.passed is True
        assert iteration.context_additions == "extra context"

    def test_default_context_additions(self):
        iteration = LoopIteration(
            attempt=1,
            result={},
            quality=None,
        )
        assert iteration.context_additions == ""
