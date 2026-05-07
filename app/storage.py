from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import csv
import json
import sqlite3

from app.models import AlphaCandidate, SimulationMetrics, SimulationRecord


class StorageRepository:
    def __init__(self, db_path: Path, output_dir: Path) -> None:
        self.db_path = db_path
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        cursor = self.connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS alphas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expression TEXT NOT NULL,
                normalized_expression TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE,
                template_type TEXT NOT NULL,
                status TEXT NOT NULL,
                params_json TEXT NOT NULL,
                wrappers_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS simulations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alpha_id INTEGER NOT NULL,
                simulation_id TEXT,
                submitted_at TEXT,
                completed_at TEXT,
                api_status TEXT NOT NULL,
                error TEXT,
                FOREIGN KEY(alpha_id) REFERENCES alphas(id)
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alpha_id INTEGER NOT NULL,
                sharpe REAL,
                fitness REAL,
                returns REAL,
                drawdown REAL,
                turnover REAL,
                margin REAL,
                extras_json TEXT NOT NULL,
                reward_json TEXT NOT NULL,
                FOREIGN KEY(alpha_id) REFERENCES alphas(id)
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alpha_id INTEGER NOT NULL,
                is_best INTEGER NOT NULL,
                reviewed INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                FOREIGN KEY(alpha_id) REFERENCES alphas(id)
            );

            CREATE TABLE IF NOT EXISTS mining_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                cycles_planned INTEGER NOT NULL,
                cycles_completed INTEGER NOT NULL DEFAULT 0,
                submitted_count INTEGER NOT NULL DEFAULT 0,
                completed_count INTEGER NOT NULL DEFAULT 0,
                best_count INTEGER NOT NULL DEFAULT 0,
                avg_reward REAL NOT NULL DEFAULT 0,
                checkpoint_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        self.connection.commit()

    def save_candidate(self, candidate: AlphaCandidate, status: str = "generated") -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO alphas
            (expression, normalized_expression, fingerprint, template_type, status, params_json, wrappers_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.expression,
                candidate.normalized_expression,
                candidate.fingerprint,
                candidate.template_type,
                status,
                json.dumps(candidate.params, sort_keys=True),
                json.dumps(candidate.wrappers),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()
        if cursor.lastrowid:
            candidate.candidate_id = cursor.lastrowid
            return cursor.lastrowid
        existing = self.connection.execute("SELECT id FROM alphas WHERE fingerprint = ?", (candidate.fingerprint,)).fetchone()
        candidate.candidate_id = int(existing["id"])
        return candidate.candidate_id

    def mark_status(self, alpha_id: int, status: str) -> None:
        self.connection.execute("UPDATE alphas SET status = ? WHERE id = ?", (status, alpha_id))
        self.connection.commit()

    def save_result(self, alpha_id: int, record: SimulationRecord, is_best: bool) -> None:
        self.connection.execute(
            "INSERT INTO simulations (alpha_id, simulation_id, submitted_at, completed_at, api_status, error) VALUES (?, ?, ?, ?, ?, ?)",
            (
                alpha_id,
                record.handle.simulation_id if record.handle else None,
                record.handle.submitted_at.isoformat() if record.handle else None,
                record.completed_at.isoformat() if record.completed_at else None,
                record.api_status,
                record.error,
            ),
        )
        self.connection.execute(
            "INSERT INTO metrics (alpha_id, sharpe, fitness, returns, drawdown, turnover, margin, extras_json, reward_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                alpha_id,
                record.metrics.sharpe,
                record.metrics.fitness,
                record.metrics.returns,
                record.metrics.drawdown,
                record.metrics.turnover,
                record.metrics.margin,
                json.dumps(record.metrics.extras, sort_keys=True),
                json.dumps(asdict(record.reward), sort_keys=True),
            ),
        )
        self.connection.execute(
            "INSERT INTO candidates (alpha_id, is_best, reviewed, notes) VALUES (?, ?, 0, ?)",
            (alpha_id, 1 if is_best else 0, record.error or ""),
        )
        self.connection.commit()

    def iter_fingerprints(self) -> Iterable[Tuple[str, str, str]]:
        rows = self.connection.execute("SELECT fingerprint, normalized_expression, template_type FROM alphas").fetchall()
        for row in rows:
            yield row["fingerprint"], row["normalized_expression"], row["template_type"]

    def list_best(self) -> List[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT a.expression, a.template_type, m.sharpe, m.fitness, m.returns, m.drawdown
            FROM candidates c
            JOIN alphas a ON a.id = c.alpha_id
            JOIN metrics m ON m.alpha_id = a.id
            WHERE c.is_best = 1
            ORDER BY m.fitness DESC, m.sharpe DESC
            """
        ).fetchall()

    def list_failed(self) -> List[sqlite3.Row]:
        return self.connection.execute("SELECT id, expression, template_type FROM alphas WHERE status IN ('failed', 'timeout')").fetchall()

    def list_seed_candidates(self, limit: int) -> List[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                a.expression,
                a.template_type,
                a.params_json,
                a.wrappers_json,
                COALESCE(m.fitness, 0) AS fitness,
                COALESCE(m.sharpe, 0) AS sharpe,
                COALESCE(json_extract(m.reward_json, '$.value'), 0) AS reward
            FROM alphas a
            LEFT JOIN metrics m ON m.alpha_id = a.id
            WHERE a.status = 'complete'
            ORDER BY reward DESC, fitness DESC, sharpe DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def summarize_template_performance(self) -> List[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                a.template_type,
                COUNT(*) AS total_runs,
                AVG(COALESCE(json_extract(m.reward_json, '$.value'), 0)) AS avg_reward,
                AVG(COALESCE(m.fitness, 0)) AS avg_fitness,
                AVG(COALESCE(m.sharpe, 0)) AS avg_sharpe,
                SUM(CASE WHEN s.api_status IN ('failed', 'error', 'timeout') THEN 1 ELSE 0 END) AS failed_runs,
                SUM(CASE WHEN s.api_status IN ('complete', 'completed', 'done') THEN 1 ELSE 0 END) AS completed_runs
            FROM alphas a
            JOIN metrics m ON m.alpha_id = a.id
            LEFT JOIN simulations s ON s.alpha_id = a.id
            GROUP BY a.template_type
            ORDER BY avg_reward DESC, avg_fitness DESC, avg_sharpe DESC
            """
        ).fetchall()

    def summarize_failure_reasons(self) -> List[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                a.template_type,
                COALESCE(s.error, '') AS error,
                COUNT(*) AS count
            FROM simulations s
            JOIN alphas a ON a.id = s.alpha_id
            WHERE s.api_status IN ('failed', 'error', 'timeout', 'filtered')
            GROUP BY a.template_type, COALESCE(s.error, '')
            ORDER BY count DESC
            """
        ).fetchall()

    def start_session(self, cycles_planned: int) -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO mining_sessions (started_at, cycles_planned, checkpoint_json)
            VALUES (?, ?, ?)
            """,
            (datetime.now(timezone.utc).isoformat(), cycles_planned, "{}"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_session(self, session_id: int, *, cycles_completed: int, submitted_count: int, completed_count: int, best_count: int, avg_reward: float, checkpoint: dict) -> None:
        self.connection.execute(
            """
            UPDATE mining_sessions
            SET cycles_completed = ?, submitted_count = ?, completed_count = ?, best_count = ?, avg_reward = ?, checkpoint_json = ?
            WHERE id = ?
            """,
            (
                cycles_completed,
                submitted_count,
                completed_count,
                best_count,
                avg_reward,
                json.dumps(checkpoint, sort_keys=True),
                session_id,
            ),
        )
        self.connection.commit()

    def finish_session(self, session_id: int) -> None:
        self.connection.execute(
            "UPDATE mining_sessions SET ended_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )
        self.connection.commit()

    def load_latest_checkpoint(self) -> Optional[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT *
            FROM mining_sessions
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    def list_recent_sessions(self, limit: int = 10) -> List[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT *
            FROM mining_sessions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def list_completed_behavior_profiles(self, limit: int = 500) -> List[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT
                a.expression,
                a.normalized_expression,
                a.fingerprint,
                a.template_type,
                m.sharpe,
                m.fitness,
                m.returns,
                m.drawdown,
                m.turnover,
                m.margin,
                m.extras_json
            FROM alphas a
            JOIN metrics m ON m.alpha_id = a.id
            JOIN simulations s ON s.alpha_id = a.id
            WHERE s.api_status IN ('complete', 'completed', 'done')
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def generate_session_dashboard(self, limit: int = 10) -> Path:
        dashboard_path = self.output_dir / "session_dashboard.md"
        recent_sessions = self.list_recent_sessions(limit)
        template_rows = self.summarize_template_performance()
        failure_rows = self.summarize_failure_reasons()[:10]
        best_rows = self.list_best()[:10]
        universe_rows = self.summarize_universe_breakdown()[:10]
        stage_rows = self.summarize_stage_breakdown()[:10]
        check_rows = self.summarize_check_breakdown()[:10]

        lines = [
            "# Session Dashboard",
            "",
            "## Recent Sessions",
            "",
        ]
        if recent_sessions:
            lines.extend(
                [
                    "| id | started_at | ended_at | planned | completed | submitted | complete | best | avg_reward |",
                    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for row in recent_sessions:
                lines.append(
                    f"| {row['id']} | {row['started_at']} | {row['ended_at'] or 'running'} | {row['cycles_planned']} | {row['cycles_completed']} | {row['submitted_count']} | {row['completed_count']} | {row['best_count']} | {float(row['avg_reward'] or 0.0):.4f} |"
                )
        else:
            lines.append("No sessions recorded yet.")

        lines.extend(["", "## Template Performance", ""])
        if template_rows:
            lines.extend(
                [
                    "| template | runs | completed | failed | avg_reward | avg_fitness | avg_sharpe |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for row in template_rows[:10]:
                lines.append(
                    f"| {row['template_type']} | {row['total_runs']} | {row['completed_runs']} | {row['failed_runs']} | {float(row['avg_reward'] or 0.0):.4f} | {float(row['avg_fitness'] or 0.0):.4f} | {float(row['avg_sharpe'] or 0.0):.4f} |"
                )
        else:
            lines.append("No template performance data yet.")

        lines.extend(["", "## Frequent Failures", ""])
        if failure_rows:
            lines.extend(
                [
                    "| template | error | count |",
                    "| --- | --- | --- |",
                ]
            )
            for row in failure_rows:
                lines.append(f"| {row['template_type']} | {row['error']} | {row['count']} |")
        else:
            lines.append("No failure rows recorded yet.")

        lines.extend(["", "## Universe Breakdown", ""])
        if universe_rows:
            lines.extend(
                [
                    "| universe | count | avg_sharpe | avg_fitness |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for row in universe_rows:
                lines.append(
                    f"| {row['universe']} | {row['count']} | {row['avg_sharpe']:.4f} | {row['avg_fitness']:.4f} |"
                )
        else:
            lines.append("No universe data available yet.")

        lines.extend(["", "## Stage Breakdown", ""])
        if stage_rows:
            lines.extend(
                [
                    "| stage | count | avg_sharpe | avg_fitness |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for row in stage_rows:
                lines.append(
                    f"| {row['stage']} | {row['count']} | {row['avg_sharpe']:.4f} | {row['avg_fitness']:.4f} |"
                )
        else:
            lines.append("No stage data available yet.")

        lines.extend(["", "## Failed Checks", ""])
        if check_rows:
            lines.extend(
                [
                    "| check | count |",
                    "| --- | --- |",
                ]
            )
            for row in check_rows:
                lines.append(f"| {row['check']} | {row['count']} |")
        else:
            lines.append("No failed checks recorded yet.")

        lines.extend(["", "## Best Alphas", ""])
        if best_rows:
            lines.extend(
                [
                    "| template | sharpe | fitness | returns | drawdown | expression |",
                    "| --- | --- | --- | --- | --- | --- |",
                ]
            )
            for row in best_rows:
                lines.append(
                    f"| {row['template_type']} | {float(row['sharpe'] or 0.0):.4f} | {float(row['fitness'] or 0.0):.4f} | {float(row['returns'] or 0.0):.4f} | {float(row['drawdown'] or 0.0):.4f} | `{row['expression']}` |"
                )
        else:
            lines.append("No best alphas have met the current thresholds yet.")

        lines.extend(["", "## Quality Buckets", ""])
        quality_rows = self.summarize_quality_breakdown()
        if quality_rows:
            lines.extend(["| quality | count | avg_sharpe | avg_fitness |", "| --- | --- | --- | --- |"])
            for row in quality_rows:
                lines.append(f"| {row['quality']} | {row['count']} | {row['avg_sharpe']:.4f} | {row['avg_fitness']:.4f} |")
        else:
            lines.append("No quality bucket data available yet.")

        dashboard_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return dashboard_path

    def summarize_universe_breakdown(self) -> List[dict]:
        buckets: dict[str, dict[str, float]] = {}
        for row in self.list_completed_behavior_profiles():
            extras = json.loads(row["extras_json"] or "{}")
            universe = str(extras.get("universe") or "unknown")
            bucket = buckets.setdefault(universe, {"count": 0.0, "sharpe": 0.0, "fitness": 0.0})
            bucket["count"] += 1
            bucket["sharpe"] += float(row["sharpe"] or 0.0)
            bucket["fitness"] += float(row["fitness"] or 0.0)
        return [
            {
                "universe": name,
                "count": int(payload["count"]),
                "avg_sharpe": payload["sharpe"] / payload["count"],
                "avg_fitness": payload["fitness"] / payload["count"],
            }
            for name, payload in sorted(buckets.items(), key=lambda item: (-item[1]["count"], item[0]))
            if payload["count"]
        ]

    def summarize_stage_breakdown(self) -> List[dict]:
        buckets: dict[str, dict[str, float]] = {}
        for row in self.list_completed_behavior_profiles():
            extras = json.loads(row["extras_json"] or "{}")
            stage = str(extras.get("stage") or "unknown")
            bucket = buckets.setdefault(stage, {"count": 0.0, "sharpe": 0.0, "fitness": 0.0})
            bucket["count"] += 1
            bucket["sharpe"] += float(row["sharpe"] or 0.0)
            bucket["fitness"] += float(row["fitness"] or 0.0)
        return [
            {
                "stage": name,
                "count": int(payload["count"]),
                "avg_sharpe": payload["sharpe"] / payload["count"],
                "avg_fitness": payload["fitness"] / payload["count"],
            }
            for name, payload in sorted(buckets.items(), key=lambda item: (-item[1]["count"], item[0]))
            if payload["count"]
        ]

    def summarize_check_breakdown(self) -> List[dict]:
        buckets: dict[str, int] = {}
        for row in self.list_completed_behavior_profiles():
            extras = json.loads(row["extras_json"] or "{}")
            for check_name in extras.get("failed_check_names", []):
                buckets[str(check_name)] = buckets.get(str(check_name), 0) + 1
        return [
            {"check": name, "count": count}
            for name, count in sorted(buckets.items(), key=lambda item: (-item[1], item[0]))
        ]

    def summarize_quality_breakdown(self) -> List[dict]:
        buckets: dict[str, dict[str, float]] = {}
        for row in self.list_completed_behavior_profiles():
            extras = json.loads(row["extras_json"] or "{}")
            quality = str(extras.get("quality_tier") or "unknown")
            bucket = buckets.setdefault(quality, {"count": 0.0, "sharpe": 0.0, "fitness": 0.0})
            bucket["count"] += 1
            bucket["sharpe"] += float(row["sharpe"] or 0.0)
            bucket["fitness"] += float(row["fitness"] or 0.0)
        return [
            {
                "quality": name,
                "count": int(payload["count"]),
                "avg_sharpe": payload["sharpe"] / payload["count"],
                "avg_fitness": payload["fitness"] / payload["count"],
            }
            for name, payload in sorted(buckets.items(), key=lambda item: (item[0] != "high", item[0] != "medium", item[0]))
            if payload["count"]
        ]

    def append_best_alpha(self, candidate: AlphaCandidate, metrics: SimulationMetrics, reward: Optional[object] = None) -> None:
        with (self.output_dir / "best_alphas.txt").open("a", encoding="utf-8") as handle:
            extras = metrics.extras or {}
            reward_value = getattr(reward, "value", "")
            handle.write(
                f"{candidate.expression} | quality={extras.get('quality_tier', '')} | "
                f"alpha_id={extras.get('alpha_id', '')} | sharpe={metrics.sharpe:.4f} | "
                f"fitness={metrics.fitness:.4f} | returns={metrics.returns:.4f} | "
                f"drawdown={metrics.drawdown:.4f} | turnover={metrics.turnover:.4f} | "
                f"margin={metrics.margin:.4f} | reward={reward_value}\n"
            )
        path = self.output_dir / "passed_alphas.csv"
        columns = [
            "expression",
            "template_type",
            "alpha_id",
            "grade",
            "status",
            "stage",
            "region",
            "universe",
            "delay",
            "neutralization",
            "checks_failed",
            "failed_check_names",
            "behavior_similarity",
            "quality_tier",
            "sharpe",
            "fitness",
            "returns",
            "drawdown",
            "turnover",
            "margin",
            "reward",
        ]
        self._rotate_csv_if_header_changed(path, columns)
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(columns)
            extras = metrics.extras or {}
            writer.writerow(
                [
                    candidate.expression,
                    candidate.template_type,
                    extras.get("alpha_id", ""),
                    extras.get("grade", ""),
                    extras.get("status", ""),
                    extras.get("stage", ""),
                    extras.get("region", ""),
                    extras.get("universe", ""),
                    extras.get("delay", ""),
                    extras.get("neutralization", ""),
                    extras.get("checks_failed", 0),
                    ";".join(str(item) for item in extras.get("failed_check_names", [])),
                    extras.get("behavior_similarity", 0.0),
                    extras.get("quality_tier", ""),
                    metrics.sharpe,
                    metrics.fitness,
                    metrics.returns,
                    metrics.drawdown,
                    metrics.turnover,
                    metrics.margin,
                    getattr(reward, "value", ""),
                ]
            )

    def _rotate_csv_if_header_changed(self, path: Path, expected_columns: List[str]) -> None:
        if not path.exists() or path.stat().st_size == 0:
            return
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            current = next(reader, [])
        if current == expected_columns:
            return
        legacy_path = path.with_name(path.stem + "_legacy" + path.suffix)
        counter = 1
        while legacy_path.exists():
            legacy_path = path.with_name(f"{path.stem}_legacy_{counter}{path.suffix}")
            counter += 1
        path.replace(legacy_path)

    def append_run_summary(self, record: SimulationRecord) -> None:
        path = self.output_dir / "run_summary.csv"
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(
                    [
                        "expression",
                        "template_type",
                        "status",
                        "stage",
                        "universe",
                        "checks_failed",
                        "behavior_similarity",
                        "quality_tier",
                        "sharpe",
                        "fitness",
                        "returns",
                        "drawdown",
                        "turnover",
                        "margin",
                        "reward",
                    ]
                )
            extras = record.metrics.extras or {}
            writer.writerow(
                [
                    record.candidate.expression,
                    record.candidate.template_type,
                    record.api_status,
                    extras.get("stage", ""),
                    extras.get("universe", ""),
                    extras.get("checks_failed", 0),
                    extras.get("behavior_similarity", 0.0),
                    extras.get("quality_tier", ""),
                    record.metrics.sharpe,
                    record.metrics.fitness,
                    record.metrics.returns,
                    record.metrics.drawdown,
                    record.metrics.turnover,
                    record.metrics.margin,
                    record.reward.value,
                ]
            )

    def append_failure(self, candidate: AlphaCandidate, error: str) -> None:
        path = self.output_dir / "failed_alphas.csv"
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(["expression", "template_type", "error"])
            writer.writerow([candidate.expression, candidate.template_type, error])

    def close(self) -> None:
        self.connection.close()

