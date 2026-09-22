from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.signal_memory import SignalMemory, SignalRecord, TrendAlert


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_signal.db")


@pytest.fixture
def memory(db_path: str) -> SignalMemory:
    mem = SignalMemory(db_path)
    yield mem
    mem.close()


def _make_record(
    date: str | None = None,
    title: str = "Test signal",
    summary: str = "Summary",
    source: str = "test",
    source_url: str = "http://test.com",
    relevance: int = 7,
    reaction: str = "idea",
    result_ref: str | None = "IDEA-0001",
    entities: list[str] | None = None,
    quality_score: int = 7,
    attempts: int = 1,
) -> SignalRecord:
    # По умолчанию используем сегодняшнюю дату, чтобы тесты не протухали
    # из-за фильтрации по TTL/окну дней в signal_memory.
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return SignalRecord(
        date=date,
        title=title,
        summary=summary,
        source=source,
        source_url=source_url,
        relevance=relevance,
        reaction=reaction,
        result_ref=result_ref,
        entities=entities or ["Booking"],
        quality_score=quality_score,
        attempts=attempts,
    )


# ---------------------------------------------------------------------------
# AC-11: record_signal inserts into signals table
# ---------------------------------------------------------------------------

class TestRecordSignal:

    def test_insert_returns_positive_id(self, memory: SignalMemory):
        rec = _make_record()
        rid = memory.record_signal(rec)
        assert rid > 0

    def test_insert_stores_all_fields(self, memory: SignalMemory, db_path: str):
        rec = _make_record(
            date="2026-08-02",
            title="Booking launches AI",
            summary="Details here",
            source="techcrunch",
            source_url="https://tc.com/1",
            relevance=9,
            reaction="report",
            result_ref="report-2026-08-02",
            entities=["Booking", "AI"],
            quality_score=8,
            attempts=2,
        )
        rid = memory.record_signal(rec)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (rid,)).fetchone()
        conn.close()

        assert row["date"] == "2026-08-02"
        assert row["title"] == "Booking launches AI"
        assert row["summary"] == "Details here"
        assert row["source"] == "techcrunch"
        assert row["source_url"] == "https://tc.com/1"
        assert row["relevance"] == 9
        assert row["reaction"] == "report"
        assert row["result_ref"] == "report-2026-08-02"
        assert json.loads(row["entities"]) == ["Booking", "AI"]
        assert row["quality_score"] == 8
        assert row["attempts"] == 2

    def test_multiple_inserts_unique_ids(self, memory: SignalMemory):
        ids = [memory.record_signal(_make_record(title=f"Signal {i}")) for i in range(5)]
        assert len(set(ids)) == 5

    def test_entities_stored_as_json(self, memory: SignalMemory, db_path: str):
        rec = _make_record(entities=["Booking", "Airbnb"])
        rid = memory.record_signal(rec)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT entities FROM signals WHERE id = ?", (rid,)).fetchone()
        conn.close()
        parsed = json.loads(row[0])
        assert parsed == ["Booking", "Airbnb"]

    def test_cyrillic_entities_preserved(self, memory: SignalMemory, db_path: str):
        rec = _make_record(entities=["Яндекс", "Островок"])
        rid = memory.record_signal(rec)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT entities FROM signals WHERE id = ?", (rid,)).fetchone()
        conn.close()
        parsed = json.loads(row[0])
        assert parsed == ["Яндекс", "Островок"]


# ---------------------------------------------------------------------------
# AC-41: get_recent_signals returns recent history
# ---------------------------------------------------------------------------

class TestGetRecentSignals:

    def test_returns_matching_entity(self, memory: SignalMemory):
        today = datetime.now().strftime("%Y-%m-%d")
        memory.record_signal(_make_record(entities=["Booking"], date=today))
        memory.record_signal(_make_record(entities=["Airbnb"], date=today))

        result = memory.get_recent_signals("Booking", days=7)
        assert len(result) == 1
        assert result[0].entities == ["Booking"]

    def test_excludes_old_signals(self, memory: SignalMemory):
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent_date = datetime.now().strftime("%Y-%m-%d")

        memory.record_signal(_make_record(entities=["Booking"], date=old_date, title="Old"))
        memory.record_signal(_make_record(entities=["Booking"], date=recent_date, title="Recent"))

        result = memory.get_recent_signals("Booking", days=7)
        assert len(result) == 1
        assert result[0].title == "Recent"

    def test_returns_empty_for_unknown_entity(self, memory: SignalMemory):
        memory.record_signal(_make_record(entities=["Booking"]))
        result = memory.get_recent_signals("UnknownCorp", days=7)
        assert result == []

    def test_returns_signal_record_objects(self, memory: SignalMemory):
        memory.record_signal(_make_record(entities=["Booking"]))
        result = memory.get_recent_signals("Booking", days=30)
        assert len(result) == 1
        assert isinstance(result[0], SignalRecord)
        assert result[0].entities == ["Booking"]

    def test_ordered_by_date_desc(self, memory: SignalMemory):
        today = datetime.now()
        for i in range(3):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            memory.record_signal(_make_record(entities=["Booking"], date=d, title=f"Day-{i}"))

        result = memory.get_recent_signals("Booking", days=7)
        assert len(result) == 3
        assert result[0].title == "Day-0"  # most recent first
        assert result[2].title == "Day-2"


# ---------------------------------------------------------------------------
# AC-42: get_entity_history returns formatted text
# ---------------------------------------------------------------------------

class TestGetEntityHistory:

    def test_returns_empty_when_no_data(self, memory: SignalMemory):
        result = memory.get_entity_history("NonExistent")
        assert result == ""

    def test_includes_signal_titles(self, memory: SignalMemory):
        memory.record_signal(_make_record(
            entities=["Booking"], title="Booking launches AI", reaction="idea",
            result_ref="IDEA-0001",
        ))
        result = memory.get_entity_history("Booking", weeks=4)
        assert "Booking launches AI" in result
        assert "idea" in result

    def test_includes_result_ref(self, memory: SignalMemory):
        memory.record_signal(_make_record(
            entities=["Booking"], reaction="report", result_ref="report-2026-08",
        ))
        result = memory.get_entity_history("Booking", weeks=4)
        assert "report-2026-08" in result

    def test_includes_trend_alert(self, memory: SignalMemory):
        memory.record_signal(_make_record(entities=["Booking"]))
        # Manually insert a trend alert
        conn = memory._get_conn()
        conn.execute(
            "INSERT INTO trend_alerts (entity, trend_type, description, evidence) "
            "VALUES (?, ?, ?, ?)",
            ("Booking", "spike", "Booking: 5 mentions this week", "[]"),
        )
        conn.commit()

        result = memory.get_entity_history("Booking", weeks=4)
        assert "Booking: 5 mentions this week" in result

    def test_includes_last_report_ref(self, memory: SignalMemory):
        memory.record_signal(_make_record(
            entities=["Booking"], reaction="report", result_ref="report-latest",
        ))
        result = memory.get_entity_history("Booking", weeks=4)
        assert "report-latest" in result


# ---------------------------------------------------------------------------
# AC-12..AC-16: detect_trends with 4 rules
# ---------------------------------------------------------------------------

class TestDetectTrends:

    def _insert_signals_for_weeks(
        self,
        memory: SignalMemory,
        entity: str,
        weeks_back: list[tuple[int, int, int]],  # (weeks_ago, count, relevance)
    ):
        """Insert signals for an entity across multiple weeks."""
        now = datetime.now()
        for weeks_ago, count, relevance in weeks_back:
            # Place signals on Monday of the target week
            target = now - timedelta(weeks=weeks_ago)
            date_str = target.strftime("%Y-%m-%d")
            for i in range(count):
                memory.record_signal(_make_record(
                    entities=[entity],
                    date=date_str,
                    title=f"{entity} signal w-{weeks_ago} #{i}",
                    relevance=relevance,
                    source=f"source-{i}",
                ))

    def test_spike_detection(self, memory: SignalMemory):
        """AC-13: spike = >= threshold mentions this week, avg < 1 previously."""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        # Current week: 3 signals
        for i in range(3):
            memory.record_signal(_make_record(
                entities=["NewPlayer"], date=today, title=f"NewPlayer #{i}",
                relevance=8,
            ))
        # No signals in previous weeks (new_entrant will also trigger)
        alerts = memory.detect_trends(lookback_weeks=4, spike_threshold=3)
        spike_alerts = [a for a in alerts if a.trend_type == "spike"]
        assert len(spike_alerts) == 1
        assert spike_alerts[0].entity == "NewPlayer"

    def test_sustained_detection(self, memory: SignalMemory):
        """AC-14: sustained = entity every week for 4+ consecutive weeks."""
        now = datetime.now()
        for weeks_ago in range(4):
            d = (now - timedelta(weeks=weeks_ago)).strftime("%Y-%m-%d")
            memory.record_signal(_make_record(
                entities=["SteadyEntity"], date=d,
                title=f"SteadyEntity w-{weeks_ago}",
            ))

        alerts = memory.detect_trends(lookback_weeks=8)
        sustained = [a for a in alerts if a.trend_type == "sustained"]
        assert len(sustained) == 1
        assert sustained[0].entity == "SteadyEntity"

    def test_new_entrant_detection(self, memory: SignalMemory):
        """AC-15: new_entrant = first appearance in all history."""
        today = datetime.now().strftime("%Y-%m-%d")
        memory.record_signal(_make_record(
            entities=["BrandNewCo"], date=today, title="BrandNewCo appears",
        ))

        alerts = memory.detect_trends(lookback_weeks=4)
        new_entrants = [a for a in alerts if a.trend_type == "new_entrant"]
        assert len(new_entrants) == 1
        assert new_entrants[0].entity == "BrandNewCo"

    def test_escalation_detection(self, memory: SignalMemory):
        """AC-16: escalation = avg_relevance rising 3 consecutive weeks."""
        now = datetime.now()
        # Week 2 ago: relevance 3
        d2 = (now - timedelta(weeks=2)).strftime("%Y-%m-%d")
        memory.record_signal(_make_record(
            entities=["Escalator"], date=d2, relevance=3, title="Esc w2",
        ))
        # Week 1 ago: relevance 6
        d1 = (now - timedelta(weeks=1)).strftime("%Y-%m-%d")
        memory.record_signal(_make_record(
            entities=["Escalator"], date=d1, relevance=6, title="Esc w1",
        ))
        # Current week: relevance 9
        d0 = now.strftime("%Y-%m-%d")
        memory.record_signal(_make_record(
            entities=["Escalator"], date=d0, relevance=9, title="Esc w0",
        ))

        alerts = memory.detect_trends(lookback_weeks=4)
        escalations = [a for a in alerts if a.trend_type == "escalation"]
        assert len(escalations) == 1
        assert escalations[0].entity == "Escalator"

    def test_no_duplicate_alerts(self, memory: SignalMemory):
        """Alerts should not be duplicated on repeated runs."""
        today = datetime.now().strftime("%Y-%m-%d")
        memory.record_signal(_make_record(
            entities=["OnceEntity"], date=today, title="Once",
        ))

        alerts1 = memory.detect_trends(lookback_weeks=4)
        alerts2 = memory.detect_trends(lookback_weeks=4)

        # Second run should produce 0 new alerts (already exist with notified=0)
        assert len(alerts2) == 0
        assert len(alerts1) > 0

    def test_returns_empty_when_no_signals(self, memory: SignalMemory):
        alerts = memory.detect_trends(lookback_weeks=4)
        assert alerts == []


# ---------------------------------------------------------------------------
# AC-50: update_trend_action
# ---------------------------------------------------------------------------

class TestUpdateTrendAction:

    def test_updates_acted_on(self, memory: SignalMemory, db_path: str):
        today = datetime.now().strftime("%Y-%m-%d")
        memory.record_signal(_make_record(entities=["TestEntity"], date=today))
        memory.detect_trends(lookback_weeks=4)

        # Get alert id
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id FROM trend_alerts WHERE entity = 'TestEntity' LIMIT 1"
        ).fetchone()
        conn.close()

        assert row is not None
        alert_id = row["id"]
        memory.update_trend_action(alert_id, "dispatched report-123")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        updated = conn.execute(
            "SELECT acted_on FROM trend_alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        conn.close()
        assert updated["acted_on"] == "dispatched report-123"


# ---------------------------------------------------------------------------
# mark_trend_notified
# ---------------------------------------------------------------------------

class TestMarkTrendNotified:

    def test_marks_as_notified(self, memory: SignalMemory, db_path: str):
        today = datetime.now().strftime("%Y-%m-%d")
        memory.record_signal(_make_record(entities=["NotifyEntity"], date=today))
        memory.detect_trends(lookback_weeks=4)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id FROM trend_alerts WHERE entity = 'NotifyEntity' LIMIT 1"
        ).fetchone()
        conn.close()

        assert row is not None
        memory.mark_trend_notified(row["id"])

        active = memory.get_active_trends()
        notified_entities = [a.entity for a in active]
        assert "NotifyEntity" not in notified_entities


# ---------------------------------------------------------------------------
# get_active_trends
# ---------------------------------------------------------------------------

class TestGetActiveTrends:

    def test_returns_only_unnotified(self, memory: SignalMemory):
        today = datetime.now().strftime("%Y-%m-%d")
        memory.record_signal(_make_record(entities=["Active1"], date=today, title="A1"))
        memory.record_signal(_make_record(entities=["Active2"], date=today, title="A2"))
        memory.detect_trends(lookback_weeks=4)

        active = memory.get_active_trends()
        entities = {a.entity for a in active}
        assert "Active1" in entities
        assert "Active2" in entities

    def test_returns_trend_alert_objects(self, memory: SignalMemory):
        today = datetime.now().strftime("%Y-%m-%d")
        memory.record_signal(_make_record(entities=["TypeCheck"], date=today))
        memory.detect_trends(lookback_weeks=4)

        active = memory.get_active_trends()
        assert len(active) > 0
        assert isinstance(active[0], TrendAlert)


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:

    def test_deletes_old_signals(self, memory: SignalMemory):
        old_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        recent_date = datetime.now().strftime("%Y-%m-%d")

        memory.record_signal(_make_record(date=old_date, title="Old"))
        memory.record_signal(_make_record(date=recent_date, title="Recent"))

        deleted = memory.cleanup(keep_days=180)
        assert deleted == 1

        remaining = memory.get_recent_signals("Booking", days=365)
        assert len(remaining) == 1
        assert remaining[0].title == "Recent"

    def test_returns_zero_when_nothing_to_delete(self, memory: SignalMemory):
        memory.record_signal(_make_record(date=datetime.now().strftime("%Y-%m-%d")))
        deleted = memory.cleanup(keep_days=180)
        assert deleted == 0


# ---------------------------------------------------------------------------
# WAL mode and connection management
# ---------------------------------------------------------------------------

class TestConnectionManagement:

    def test_wal_mode_enabled(self, memory: SignalMemory, db_path: str):
        memory.record_signal(_make_record())  # trigger connection
        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_close_and_reopen(self, db_path: str):
        mem1 = SignalMemory(db_path)
        mem1.record_signal(_make_record(title="Persist test"))
        mem1.close()

        mem2 = SignalMemory(db_path)
        signals = mem2.get_recent_signals("Booking", days=30)
        mem2.close()
        assert any(s.title == "Persist test" for s in signals)

    def test_tables_created(self, memory: SignalMemory, db_path: str):
        memory.record_signal(_make_record())  # trigger init

        conn = sqlite3.connect(db_path)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "signals" in tables
        assert "entity_trends" in tables
        assert "trend_alerts" in tables

    def test_directory_created_if_missing(self, tmp_path: Path):
        deep_path = str(tmp_path / "a" / "b" / "c" / "test.db")
        mem = SignalMemory(deep_path)
        mem.record_signal(_make_record())
        mem.close()
        assert Path(deep_path).exists()
