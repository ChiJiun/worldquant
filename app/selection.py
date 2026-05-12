from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import csv
import json
import math
import re

from app.models import utc_now_iso
from app.research_paths import existing_or_new, research_paths


REGISTRY_FIELDS = [
    "alpha_id",
    "candidate_id",
    "expression",
    "parent_alpha_id",
    "workflow_type",
    "family",
    "core_signal",
    "fields",
    "operators",
    "lookbacks",
    "direction",
    "sharpe",
    "fitness",
    "returns",
    "turnover",
    "drawdown",
    "margin",
    "sub_universe_status",
    "weight_concentration_status",
    "self_corr_status",
    "quality_score",
    "status",
]

REJECTED_FIELDS = REGISTRY_FIELDS + ["cluster_id", "replaced_by", "reject_reason"]
BEST_FIELDS = REGISTRY_FIELDS + ["cluster_id"]
QUEUE_FIELDS = BEST_FIELDS + ["submit_score"]

KNOWN_FIELDS = [
    "adv20",
    "adv60",
    "adv5",
    "assets",
    "cashflow",
    "close",
    "debt",
    "ebitda",
    "enterprise_value",
    "est_eps",
    "est_fcf",
    "forward_price_90",
    "high",
    "historical_volatility_180",
    "historical_volatility_20",
    "inventory",
    "low",
    "news_eod_vwap",
    "news_max_up_ret",
    "open",
    "option_breakeven_30",
    "pcr_vol_60",
    "returns",
    "rp_css_assets",
    "sales",
    "scl12_sentiment",
    "snt1_cored1_score",
    "snt1_d1_earningsrevision",
    "snt1_d1_netrecpercent",
    "volume",
    "vwap",
]

KNOWN_OPERATORS = [
    "abs",
    "add",
    "group_backfill",
    "hump",
    "rank",
    "signed_power",
    "trade_when",
    "ts_backfill",
    "ts_decay_linear",
    "ts_delta",
    "ts_mean",
    "ts_std_dev",
    "zscore",
]


@dataclass
class AlphaRecord:
    alpha_id: str
    candidate_id: str
    expression: str
    parent_alpha_id: str
    workflow_type: str
    family: str
    core_signal: str
    fields: List[str]
    operators: List[str]
    lookbacks: List[int]
    direction: str
    sharpe: Optional[float]
    fitness: Optional[float]
    returns: Optional[float]
    turnover: Optional[float]
    drawdown: Optional[float]
    margin: Optional[float] = None
    sub_universe_status: str = "unknown"
    weight_concentration_status: str = "unknown"
    self_corr_status: str = "pending"
    quality_score: float = 0.0
    status: str = "candidate"
    cluster_id: str = ""
    replaced_by: str = ""
    reject_reason: str = ""
    fingerprint: Dict[str, Any] = field(default_factory=dict)

    def as_row(self, include_cluster: bool = False) -> Dict[str, Any]:
        row = {
            "alpha_id": self.alpha_id,
            "candidate_id": self.candidate_id,
            "expression": self.expression,
            "parent_alpha_id": self.parent_alpha_id,
            "workflow_type": self.workflow_type,
            "family": self.family,
            "core_signal": self.core_signal,
            "fields": "|".join(self.fields),
            "operators": "|".join(self.operators),
            "lookbacks": "|".join(str(value) for value in self.lookbacks),
            "direction": self.direction,
            "sharpe": _format_number(self.sharpe),
            "fitness": _format_number(self.fitness),
            "returns": _format_number(self.returns),
            "turnover": _format_number(self.turnover),
            "drawdown": _format_number(self.drawdown),
            "margin": _format_number(self.margin),
            "sub_universe_status": self.sub_universe_status,
            "weight_concentration_status": self.weight_concentration_status,
            "self_corr_status": self.self_corr_status,
            "quality_score": _format_number(self.quality_score),
            "status": self.status,
        }
        if include_cluster:
            row["cluster_id"] = self.cluster_id
        return row


def run_selection_pipeline(research_dir: Path, output_dir: Path) -> Dict[str, Any]:
    paths = research_paths(research_dir)
    records = load_passed_alpha_records(existing_or_new(paths.passed_alphas, research_dir / "passed_alphas.csv", research_dir / "old" / "passed_alphas.csv"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for record in records:
        record.fingerprint = build_fingerprint(record.expression, record.family, record.parent_alpha_id)
        record.core_signal = str(record.fingerprint["core_signal"])
        record.fields = list(record.fingerprint["fields"])
        record.operators = list(record.fingerprint["operators"])
        record.lookbacks = list(record.fingerprint["lookbacks"])
        record.direction = str(record.fingerprint["direction"])
        record.quality_score = quality_score(record)

    edges, correlation_matrix = detect_correlation_edges(records)
    clusters = connected_components(records, edges)
    best, rejected = select_cluster_representatives(clusters)
    queue = build_submit_queue(best)

    _write_csv(output_dir / "candidate_alphas.csv", REGISTRY_FIELDS, [record.as_row() for record in records])
    _write_csv(output_dir / "alpha_registry.csv", REGISTRY_FIELDS, [record.as_row() for record in records])
    _write_json(output_dir / "alpha_fingerprints.json", {record.alpha_id: record.fingerprint for record in records})
    _write_json(output_dir / "alpha_family_memory.json", family_memory(records, clusters))
    _write_csv(output_dir / "alpha_correlation_matrix.csv", ["alpha_id"] + [record.alpha_id for record in records], correlation_matrix)
    _write_json(output_dir / "alpha_clusters.json", serialize_clusters(clusters))
    _write_csv(output_dir / "best_alphas.csv", BEST_FIELDS, [record.as_row(include_cluster=True) for record in best])
    _write_csv(output_dir / "rejected_high_corr_alphas.csv", REJECTED_FIELDS, [_rejected_row(record) for record in rejected])
    _write_csv(output_dir / "submit_queue.csv", QUEUE_FIELDS, [_queue_row(record) for record in queue])
    _write_report(output_dir / "correlation_report.md", records, clusters, best, rejected)

    return {
        "record_count": len(records),
        "cluster_count": len(clusters),
        "best_count": len(best),
        "rejected_high_corr_count": len(rejected),
        "outputs": {
            "candidate_alphas": str(output_dir / "candidate_alphas.csv"),
            "alpha_registry": str(output_dir / "alpha_registry.csv"),
            "best_alphas": str(output_dir / "best_alphas.csv"),
            "submit_queue": str(output_dir / "submit_queue.csv"),
            "correlation_report": str(output_dir / "correlation_report.md"),
        },
    }


def load_passed_alpha_records(path: Path) -> List[AlphaRecord]:
    if not path.exists():
        return []
    records: List[AlphaRecord] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            expression = str(row.get("expression") or "").strip()
            alpha_id = str(row.get("result_id") or row.get("candidate_id") or "").strip()
            if not expression or not alpha_id:
                continue
            record = AlphaRecord(
                alpha_id=alpha_id,
                candidate_id=str(row.get("candidate_id") or alpha_id),
                expression=expression,
                parent_alpha_id=_infer_parent_id(row),
                workflow_type=_infer_workflow_type(str(row.get("candidate_id") or "")),
                family=str(row.get("family") or "manual"),
                core_signal="unknown",
                fields=[],
                operators=[],
                lookbacks=[],
                direction="unknown",
                sharpe=_float(row.get("sharpe")),
                fitness=_float(row.get("fitness")),
                returns=_float(row.get("returns")),
                turnover=_float(row.get("turnover")),
                drawdown=_float(row.get("drawdown")),
                status="candidate",
            )
            record.quality_score = quality_score(record)
            records.append(record)
    return records


def build_fingerprint(expression: str, family: str = "", parent_alpha_id: str = "") -> Dict[str, Any]:
    fields = _extract_known_tokens(expression, KNOWN_FIELDS)
    operators = _extract_known_tokens(expression, KNOWN_OPERATORS)
    lookbacks = sorted({int(value) for value in re.findall(r"\b\d+\b", expression) if int(value) <= 252})
    direction = _infer_direction(expression)
    core_signal = _infer_core_signal(fields, family, expression)
    return {
        "core_signal": core_signal,
        "fields": fields,
        "operators": operators,
        "lookbacks": lookbacks,
        "direction": direction,
        "parent_alpha_id": parent_alpha_id,
    }


def quality_score(record: AlphaRecord) -> float:
    hard_fail_count = sum(
        1 for status in [record.weight_concentration_status, record.sub_universe_status, record.self_corr_status]
        if status == "fail"
    )
    fitness = record.fitness or 0.0
    sharpe = record.sharpe or 0.0
    returns = record.returns or 0.0
    drawdown = record.drawdown or 0.0
    drawdown_penalty = max(drawdown - 0.10, 0.0) * 10
    return round(fitness + 0.25 * sharpe + 0.10 * returns - 0.10 * drawdown_penalty - 0.50 * hard_fail_count, 6)


def detect_correlation_edges(records: List[AlphaRecord]) -> Tuple[List[Tuple[str, str, str]], List[Dict[str, Any]]]:
    edges: List[Tuple[str, str, str]] = []
    score_lookup: Dict[Tuple[str, str], float] = {}
    for left, right in combinations(records, 2):
        structural = structural_similarity(left, right)
        metric_corr = metric_similarity(left, right)
        score_lookup[(left.alpha_id, right.alpha_id)] = max(structural, metric_corr)
        score_lookup[(right.alpha_id, left.alpha_id)] = max(structural, metric_corr)
        if structural >= 0.85:
            edges.append((left.alpha_id, right.alpha_id, "structural_high"))

    matrix_rows: List[Dict[str, Any]] = []
    for left in records:
        row: Dict[str, Any] = {"alpha_id": left.alpha_id}
        for right in records:
            row[right.alpha_id] = 1.0 if left.alpha_id == right.alpha_id else round(score_lookup.get((left.alpha_id, right.alpha_id), 0.0), 4)
        matrix_rows.append(row)
    return edges, matrix_rows


def structural_similarity(left: AlphaRecord, right: AlphaRecord) -> float:
    if left.parent_alpha_id and left.parent_alpha_id == right.parent_alpha_id:
        return 1.0
    if left.core_signal == right.core_signal and left.direction == right.direction:
        return 0.95
    field_score = _jaccard(set(left.fields), set(right.fields))
    operator_score = _jaccard(set(left.operators), set(right.operators))
    family_bonus = 0.2 if left.family == right.family else 0.0
    return min(1.0, 0.55 * field_score + 0.35 * operator_score + family_bonus)


def metric_similarity(left: AlphaRecord, right: AlphaRecord) -> float:
    left_values = _metric_vector(left)
    right_values = _metric_vector(right)
    if len(left_values) < 3 or len(right_values) < 3:
        return 0.0
    corr = _pearson(left_values, right_values)
    return abs(corr) if corr is not None else 0.0


def connected_components(records: List[AlphaRecord], edges: List[Tuple[str, str, str]]) -> List[List[AlphaRecord]]:
    by_id = {record.alpha_id: record for record in records}
    graph: Dict[str, Set[str]] = {record.alpha_id: set() for record in records}
    for left, right, _reason in edges:
        if left in graph and right in graph:
            graph[left].add(right)
            graph[right].add(left)

    visited: Set[str] = set()
    clusters: List[List[AlphaRecord]] = []
    for alpha_id in graph:
        if alpha_id in visited:
            continue
        stack = [alpha_id]
        component: List[AlphaRecord] = []
        visited.add(alpha_id)
        while stack:
            current = stack.pop()
            component.append(by_id[current])
            for neighbor in graph[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        clusters.append(sorted(component, key=lambda record: record.quality_score, reverse=True))

    clusters.sort(key=lambda cluster: max(record.quality_score for record in cluster), reverse=True)
    for index, cluster in enumerate(clusters, start=1):
        cluster_id = f"C{index:03d}"
        for record in cluster:
            record.cluster_id = cluster_id
    return clusters


def select_cluster_representatives(clusters: List[List[AlphaRecord]]) -> Tuple[List[AlphaRecord], List[AlphaRecord]]:
    best: List[AlphaRecord] = []
    rejected: List[AlphaRecord] = []
    for cluster in clusters:
        winner = max(cluster, key=lambda record: record.quality_score)
        winner.status = "best"
        best.append(winner)
        for record in cluster:
            if record.alpha_id == winner.alpha_id:
                continue
            record.status = "rejected_high_corr"
            record.replaced_by = winner.alpha_id
            record.reject_reason = "same_correlation_cluster_lower_quality"
            rejected.append(record)
    return best, rejected


def build_submit_queue(best: List[AlphaRecord]) -> List[AlphaRecord]:
    family_counts: Dict[str, int] = defaultdict(int)
    queue: List[AlphaRecord] = []
    for record in sorted(best, key=lambda item: item.quality_score, reverse=True):
        family_penalty = 0.3 * family_counts[record.family]
        setattr(record, "submit_score", round(record.quality_score - family_penalty, 6))
        family_counts[record.family] += 1
        queue.append(record)
    return sorted(queue, key=lambda item: getattr(item, "submit_score", item.quality_score), reverse=True)


def serialize_clusters(clusters: List[List[AlphaRecord]]) -> List[Dict[str, Any]]:
    payload = []
    for cluster in clusters:
        winner = max(cluster, key=lambda record: record.quality_score)
        payload.append({
            "cluster_id": winner.cluster_id,
            "winner_alpha_id": winner.alpha_id,
            "members": [
                {
                    "alpha_id": record.alpha_id,
                    "candidate_id": record.candidate_id,
                    "family": record.family,
                    "core_signal": record.core_signal,
                    "quality_score": record.quality_score,
                    "status": record.status,
                }
                for record in cluster
            ],
        })
    return payload


def family_memory(records: List[AlphaRecord], clusters: List[List[AlphaRecord]]) -> Dict[str, Any]:
    families: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "best_alpha_id": "", "best_quality_score": None, "clusters": []})
    for record in records:
        item = families[record.family]
        item["count"] += 1
        if item["best_quality_score"] is None or record.quality_score > item["best_quality_score"]:
            item["best_alpha_id"] = record.alpha_id
            item["best_quality_score"] = record.quality_score
    for cluster in clusters:
        for record in cluster:
            families[record.family]["clusters"].append(record.cluster_id)
    return {"updated_at": utc_now_iso(), "families": dict(families)}


def _rejected_row(record: AlphaRecord) -> Dict[str, Any]:
    row = record.as_row()
    row.update({"cluster_id": record.cluster_id, "replaced_by": record.replaced_by, "reject_reason": record.reject_reason})
    return row


def _queue_row(record: AlphaRecord) -> Dict[str, Any]:
    row = record.as_row(include_cluster=True)
    row["submit_score"] = _format_number(getattr(record, "submit_score", record.quality_score))
    return row


def _write_report(path: Path, records: List[AlphaRecord], clusters: List[List[AlphaRecord]], best: List[AlphaRecord], rejected: List[AlphaRecord]) -> None:
    lines = [
        "# Correlation Report",
        "",
        f"- generated_at: {utc_now_iso()}",
        f"- alpha_count: {len(records)}",
        f"- cluster_count: {len(clusters)}",
        f"- best_count: {len(best)}",
        f"- rejected_high_corr_count: {len(rejected)}",
        "",
        "## Clusters",
        "",
    ]
    for cluster in clusters:
        winner = max(cluster, key=lambda record: record.quality_score)
        lines.append(f"### {winner.cluster_id} winner={winner.alpha_id} quality={winner.quality_score:g}")
        for record in cluster:
            lines.append(f"- {record.alpha_id} `{record.family}` quality={record.quality_score:g} status={record.status}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _extract_known_tokens(expression: str, known: List[str]) -> List[str]:
    found = []
    for token in sorted(known, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", expression):
            found.append(token)
    return sorted(set(found))


def _infer_core_signal(fields: List[str], family: str, expression: str) -> str:
    text = f"{family} {expression}".lower()
    if "socialmedia" in text:
        return "social_sentiment"
    if "sentiment" in text:
        return "research_sentiment"
    if "option" in text:
        return "option_implied_expectation"
    if "news" in text:
        return "news_event_response"
    if "model" in text:
        return "model_revision_score"
    if "analyst" in text:
        return "analyst_revision"
    if "fundamental" in text:
        return "fundamental_value_quality"
    if "price_volume" in text or "pv" in text:
        return "price_volume_flow"
    if any(field.startswith("news") or field.startswith("rp_") for field in fields):
        return "news_event_response"
    if any(field.startswith("option") or field.startswith("forward_price") or field.startswith("historical_volatility") or field.startswith("pcr_") for field in fields):
        return "option_implied_expectation"
    if any(field.startswith("snt1") for field in fields):
        return "research_sentiment"
    if any(field.startswith("scl12") for field in fields):
        return "social_sentiment"
    if any(field.startswith("est_") for field in fields):
        return "analyst_revision"
    if "analyst_revision_rank_derivative" in text:
        return "model_revision_score"
    if {"vwap", "volume", "adv20"} & set(fields):
        return "price_volume_flow"
    if {"sales", "enterprise_value", "assets"} & set(fields):
        return "fundamental_value_quality"
    if "returns" in fields:
        return "return_reversal"
    return "unknown"


def _infer_direction(expression: str) -> str:
    text = expression.lower()
    if "-ts_decay_linear(returns" in text or "rank(-ts_decay_linear(returns" in text:
        return "reversal"
    if "rank(returns" in text or "ts_delta" in text:
        return "momentum"
    return "mixed"


def _infer_parent_id(row: Dict[str, Any]) -> str:
    candidate_id = str(row.get("candidate_id") or "")
    parts = candidate_id.split("_")
    if len(parts) >= 3 and parts[0] == "IMPROVE8C":
        return f"IMPROVE8A_{parts[1]}_*"
    if len(parts) >= 3 and parts[0] == "IMPROVE8A":
        return f"SEARCH8E_{parts[1]}_*"
    return ""


def _infer_workflow_type(candidate_id: str) -> str:
    if candidate_id.startswith("IMPROVE"):
        return "improvement"
    if candidate_id.startswith("SEARCH"):
        return "mining"
    return "legacy"


def _metric_vector(record: AlphaRecord) -> List[float]:
    values = [record.sharpe, record.fitness, record.returns, record.turnover, record.drawdown]
    return [float(value) for value in values if value is not None]


def _pearson(left: List[float], right: List[float]) -> Optional[float]:
    count = min(len(left), len(right))
    if count < 3:
        return None
    x = left[:count]
    y = right[:count]
    mean_x = sum(x) / count
    mean_y = sum(y) / count
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    denom_x = math.sqrt(sum((a - mean_x) ** 2 for a in x))
    denom_y = math.sqrt(sum((b - mean_y) ** 2 for b in y))
    if denom_x == 0 or denom_y == 0:
        return None
    return numerator / (denom_x * denom_y)


def _jaccard(left: Set[str], right: Set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def _write_csv(path: Path, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return value
