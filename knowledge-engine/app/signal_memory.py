from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SignalRecord:
    date: str  # YYYY-MM-DD
    title: str
    summary: str | None = None
    source: str | None = None
    source_url: str | None = None
    relevance: int = 0
    reaction: str = ""  # 'idea' | 'report' | 'skip'
    result_ref: str | None = None  # IDEA-NNNN or report path
    entities: list[str] = field(default_factory=list)
    quality_score: int | None = None
    attempts: int = 1


@dataclass
class TrendAlert:
    entity: str
    trend_type: str  # 'spike' | 'sustained' | 'new_entrant' | 'escalation'
    description: str
    evidence: list[dict] = field(default_factory=list)


class SignalMemory:
    """Persistent memory for signal processing: SQLite storage + trend detection."""

    def __init__(self, db_path: str):
        """Initialize SQLite with WAL mode."""
        self.db_path = db_path
        self._ensure_dir()
        self._conn: sqlite3.Connection | None = None
        self._initialized = False
        logger.info(f"SignalMemory initialized with db_path={db_path}")

    def _ensure_dir(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.row_factory = sqlite3.Row
            logger.info(f"SQLite connection opened: {self.db_path}")
        if not self._initialized:
            self._init_db()
            self._initialized = True
        return self._conn

    def _init_db(self):
        """Create 3 tables + indexes."""
        conn = self._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                title       TEXT NOT NULL,
                summary     TEXT,
                source      TEXT,
                source_url  TEXT,
                relevance   INTEGER NOT NULL DEFAULT 0,
                reaction    TEXT NOT NULL DEFAULT '',
                result_ref  TEXT,
                entities    TEXT NOT NULL DEFAULT '[]',
                quality_score INTEGER,
                attempts    INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS entity_trends (
                entity          TEXT NOT NULL,
                week            TEXT NOT NULL,
                mention_count   INTEGER NOT NULL DEFAULT 0,
                avg_relevance   REAL NOT NULL DEFAULT 0.0,
                reactions       TEXT NOT NULL DEFAULT '{}',
                top_sources     TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (entity, week)
            );

            CREATE TABLE IF NOT EXISTS trend_alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entity      TEXT NOT NULL,
                trend_type  TEXT NOT NULL,
                description TEXT NOT NULL,
                evidence    TEXT NOT NULL DEFAULT '[]',
                detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
                notified    INTEGER NOT NULL DEFAULT 0,
                acted_on    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);
            CREATE INDEX IF NOT EXISTS idx_signals_entities ON signals(entities);
        """)
        conn.commit()
        logger.info("SignalMemory tables initialized")

    def record_signal(self, signal: SignalRecord) -> int:
        """INSERT into signals table. Return inserted row id."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO signals (date, title, summary, source, source_url,
               relevance, reaction, result_ref, entities, quality_score, attempts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.date,
                signal.title,
                signal.summary,
                signal.source,
                signal.source_url,
                signal.relevance,
                signal.reaction,
                signal.result_ref,
                json.dumps(signal.entities, ensure_ascii=False),
                signal.quality_score,
                signal.attempts,
            ),
        )
        conn.commit()
        rid = cursor.lastrowid
        logger.info(f"Recorded signal id={rid}: {signal.title[:50]}")
        return rid

    def get_recent_signals(self, entity: str, days: int = 7) -> list[SignalRecord]:
        """SELECT from signals WHERE entities contains entity AND date >= cutoff."""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        pattern = f"%{entity}%"
        rows = conn.execute(
            "SELECT * FROM signals WHERE entities LIKE ? AND date >= ? ORDER BY date DESC",
            (pattern, cutoff),
        ).fetchall()
        result = [self._row_to_record(row) for row in rows]
        logger.info(f"get_recent_signals('{entity}', {days}d): {len(result)} records")
        return result

    def get_entity_history(self, entity: str, weeks: int = 4) -> str:
        """Aggregated history formatted for LLM prompt injection (AC-42)."""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        pattern = f"%{entity}%"

        signals = conn.execute(
            "SELECT date, title, reaction, result_ref FROM signals "
            "WHERE entities LIKE ? AND date >= ? ORDER BY date DESC",
            (pattern, cutoff),
        ).fetchall()

        alerts = conn.execute(
            "SELECT description, detected_at FROM trend_alerts "
            "WHERE entity = ? ORDER BY detected_at DESC LIMIT 3",
            (entity,),
        ).fetchall()

        if not signals and not alerts:
            logger.info(f"get_entity_history('{entity}', {weeks}w): empty")
            return ""

        lines = [f"Accumulated signals for {entity} (last {weeks * 7} days):"]
        for s in signals:
            ref = f" ({s['result_ref']})" if s["result_ref"] else ""
            lines.append(f"  {s['date']}: {s['title']} -> {s['reaction']}{ref}")

        if alerts:
            lines.append(f"Detected trend: {alerts[0]['description']}")

        report_refs = [
            s["result_ref"]
            for s in signals
            if s["result_ref"] and "report" in (s["reaction"] or "").lower()
        ]
        if report_refs:
            lines.append(f"Last report: {report_refs[0]}")

        result = "\n".join(lines)
        logger.info(f"get_entity_history('{entity}', {weeks}w): {len(signals)} signals, {len(alerts)} alerts")
        return result

    def detect_trends(
        self, lookback_weeks: int = 4, spike_threshold: int = 3
    ) -> list[TrendAlert]:
        """Weekly cron: 4 trend detection rules."""
        conn = self._get_conn()
        now = datetime.now()

        # Step a: update entity_trends aggregation
        self._update_entity_trends(lookback_weeks)

        # Step b: apply detection rules
        new_alerts: list[TrendAlert] = []
        cutoff = (now - timedelta(weeks=lookback_weeks)).strftime("%Y-%m-%d")

        # Collect all entities from recent signals
        rows = conn.execute(
            "SELECT DISTINCT entities FROM signals WHERE date >= ?", (cutoff,)
        ).fetchall()

        all_entities: set[str] = set()
        for row in rows:
            try:
                entities = json.loads(row["entities"])
                all_entities.update(entities)
            except (json.JSONDecodeError, TypeError):
                pass

        for entity in all_entities:
            weeks_data = conn.execute(
                "SELECT week, mention_count, avg_relevance FROM entity_trends "
                "WHERE entity = ? ORDER BY week DESC LIMIT ?",
                (entity, lookback_weeks + 4),
            ).fetchall()

            if not weeks_data:
                continue

            current_count = weeks_data[0]["mention_count"]
            prev_counts = [w["mention_count"] for w in weeks_data[1:5]]
            prev_avg = sum(prev_counts) / max(len(prev_counts), 1) if prev_counts else 0

            # Rule 1: spike -- >= spike_threshold this week, avg < 1 previously
            if current_count >= spike_threshold and prev_avg < 1:
                alert = TrendAlert(
                    entity=entity,
                    trend_type="spike",
                    description=f"{entity}: {current_count} mentions this week (usually <1)",
                    evidence=[{"week": w["week"], "count": w["mention_count"]} for w in weeks_data[:5]],
                )
                if not self._alert_exists(entity, "spike"):
                    new_alerts.append(alert)

            # Rule 2: sustained -- entity every week for 4+ consecutive weeks
            if len(weeks_data) >= 4:
                consecutive = all(w["mention_count"] > 0 for w in weeks_data[:4])
                if consecutive:
                    alert = TrendAlert(
                        entity=entity,
                        trend_type="sustained",
                        description=f"{entity}: mentioned every week for {len(weeks_data[:4])}+ consecutive weeks",
                        evidence=[{"week": w["week"], "count": w["mention_count"]} for w in weeks_data[:4]],
                    )
                    if not self._alert_exists(entity, "sustained"):
                        new_alerts.append(alert)

            # Rule 3: new_entrant -- first appearance ever
            total_history = conn.execute(
                "SELECT COUNT(*) as cnt FROM signals WHERE entities LIKE ?",
                (f"%{entity}%",),
            ).fetchone()["cnt"]
            current_signals = conn.execute(
                "SELECT COUNT(*) as cnt FROM signals WHERE entities LIKE ? AND date >= ?",
                (f"%{entity}%", cutoff),
            ).fetchone()["cnt"]
            if total_history == current_signals and current_signals > 0:
                alert = TrendAlert(
                    entity=entity,
                    trend_type="new_entrant",
                    description=f"{entity}: first appearance in signals ({current_signals} mentions)",
                    evidence=[{"total": total_history, "recent": current_signals}],
                )
                if not self._alert_exists(entity, "new_entrant"):
                    new_alerts.append(alert)

            # Rule 4: escalation -- avg_relevance rising 3 consecutive weeks
            if len(weeks_data) >= 3:
                # weeks_data is DESC, reverse for chronological order
                relevances = [w["avg_relevance"] for w in weeks_data[:3]]
                relevances.reverse()
                if relevances[0] < relevances[1] < relevances[2]:
                    alert = TrendAlert(
                        entity=entity,
                        trend_type="escalation",
                        description=f"{entity}: avg relevance rising 3 weeks ({relevances})",
                        evidence=[
                            {"week": w["week"], "avg_relevance": w["avg_relevance"]}
                            for w in weeks_data[:3]
                        ],
                    )
                    if not self._alert_exists(entity, "escalation"):
                        new_alerts.append(alert)

        # Step d: INSERT new alerts
        for alert in new_alerts:
            conn.execute(
                "INSERT INTO trend_alerts (entity, trend_type, description, evidence) "
                "VALUES (?, ?, ?, ?)",
                (
                    alert.entity,
                    alert.trend_type,
                    alert.description,
                    json.dumps(alert.evidence, ensure_ascii=False),
                ),
            )
            logger.info(f"New trend alert: {alert.trend_type} for {alert.entity}")
        conn.commit()

        logger.info(f"detect_trends: {len(new_alerts)} new alerts from {len(all_entities)} entities")
        return new_alerts

    def get_active_trends(self) -> list[TrendAlert]:
        """SELECT from trend_alerts WHERE notified=0."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM trend_alerts WHERE notified = 0 ORDER BY detected_at DESC"
        ).fetchall()
        result = [
            TrendAlert(
                entity=row["entity"],
                trend_type=row["trend_type"],
                description=row["description"],
                evidence=json.loads(row["evidence"]),
            )
            for row in rows
        ]
        logger.info(f"get_active_trends: {len(result)} active alerts")
        return result

    def update_trend_action(self, alert_id: int, acted_on: str):
        """UPDATE acted_on field on a trend alert (AC-50)."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE trend_alerts SET acted_on = ? WHERE id = ?",
            (acted_on, alert_id),
        )
        conn.commit()
        logger.info(f"Updated trend_alert {alert_id} acted_on={acted_on}")

    def mark_trend_notified(self, alert_id: int):
        """Mark alert as notified."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE trend_alerts SET notified = 1 WHERE id = ?",
            (alert_id,),
        )
        conn.commit()
        logger.info(f"Marked trend_alert {alert_id} as notified")

    def cleanup(self, keep_days: int = 180) -> int:
        """DELETE old signals. Return count deleted."""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        cursor = conn.execute("DELETE FROM signals WHERE date < ?", (cutoff,))
        conn.commit()
        count = cursor.rowcount
        logger.info(f"Cleanup: deleted {count} signals older than {keep_days} days")
        return count

    def _update_entity_trends(self, lookback_weeks: int):
        """Aggregate signals into entity_trends table."""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(weeks=lookback_weeks)).strftime("%Y-%m-%d")

        rows = conn.execute(
            "SELECT date, entities, relevance, reaction, source FROM signals WHERE date >= ?",
            (cutoff,),
        ).fetchall()

        # Aggregate by (entity, week)
        agg: dict[tuple[str, str], dict] = {}
        for row in rows:
            try:
                entities = json.loads(row["entities"])
            except (json.JSONDecodeError, TypeError):
                continue
            week = datetime.strptime(row["date"], "%Y-%m-%d").strftime("%Y-W%W")
            for entity in entities:
                key = (entity, week)
                if key not in agg:
                    agg[key] = {"count": 0, "relevance_sum": 0, "reactions": {}, "sources": set()}
                agg[key]["count"] += 1
                agg[key]["relevance_sum"] += row["relevance"]
                reaction = row["reaction"] or "unknown"
                agg[key]["reactions"][reaction] = agg[key]["reactions"].get(reaction, 0) + 1
                if row["source"]:
                    agg[key]["sources"].add(row["source"])

        for (entity, week), data in agg.items():
            avg_rel = data["relevance_sum"] / data["count"] if data["count"] else 0
            conn.execute(
                """INSERT OR REPLACE INTO entity_trends
                   (entity, week, mention_count, avg_relevance, reactions, top_sources)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entity,
                    week,
                    data["count"],
                    round(avg_rel, 2),
                    json.dumps(data["reactions"]),
                    json.dumps(list(data["sources"])),
                ),
            )
        conn.commit()
        logger.info(f"Updated entity_trends: {len(agg)} entries")

    def _alert_exists(self, entity: str, trend_type: str) -> bool:
        """Check if non-notified alert exists for this entity+type."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id FROM trend_alerts WHERE entity = ? AND trend_type = ? AND notified = 0",
            (entity, trend_type),
        ).fetchone()
        return row is not None

    def _row_to_record(self, row: sqlite3.Row) -> SignalRecord:
        entities: list[str] = []
        try:
            entities = json.loads(row["entities"])
        except (json.JSONDecodeError, TypeError):
            pass
        return SignalRecord(
            date=row["date"],
            title=row["title"],
            summary=row["summary"],
            source=row["source"],
            source_url=row["source_url"],
            relevance=row["relevance"],
            reaction=row["reaction"],
            result_ref=row["result_ref"],
            entities=entities,
            quality_score=row["quality_score"],
            attempts=row["attempts"],
        )

    def close(self):
        """Close the SQLite connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("SignalMemory connection closed")
