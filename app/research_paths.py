from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResearchPaths:
    root: Path
    state_dir: Path
    logs_dir: Path
    submissions_dir: Path
    notes_dir: Path
    schema_dir: Path
    examples_dir: Path
    family_memory: Path
    best_alphas: Path
    portfolio: Path
    experiment_decisions: Path
    passed_alphas: Path
    failed_alphas: Path
    validation_reports_jsonl: Path
    validation_reports_csv: Path
    final_selection_reports_jsonl: Path
    latest_final_selection_report: Path
    submitted_alphas: Path
    hypotheses: Path
    failure_taxonomy: Path


def research_paths(root: Path) -> ResearchPaths:
    state_dir = root / "state"
    logs_dir = root / "logs"
    submissions_dir = root / "submissions"
    notes_dir = root / "notes"
    schema_dir = root / "schema"
    examples_dir = root / "examples"
    return ResearchPaths(
        root=root,
        state_dir=state_dir,
        logs_dir=logs_dir,
        submissions_dir=submissions_dir,
        notes_dir=notes_dir,
        schema_dir=schema_dir,
        examples_dir=examples_dir,
        family_memory=state_dir / "family_memory.json",
        best_alphas=state_dir / "best_alphas.txt",
        portfolio=state_dir / "portfolio.json",
        experiment_decisions=logs_dir / "experiment_decisions.jsonl",
        passed_alphas=logs_dir / "passed_alphas.csv",
        failed_alphas=logs_dir / "failed_alphas.csv",
        validation_reports_jsonl=logs_dir / "validation_reports.jsonl",
        validation_reports_csv=logs_dir / "validation_reports.csv",
        final_selection_reports_jsonl=logs_dir / "final_selection_reports.jsonl",
        latest_final_selection_report=state_dir / "latest_final_selection_report.json",
        submitted_alphas=submissions_dir / "submitted_alphas.csv",
        hypotheses=notes_dir / "hypotheses.md",
        failure_taxonomy=root / "failure_taxonomy.json",
    )


def ensure_research_layout(root: Path) -> ResearchPaths:
    paths = research_paths(root)
    for directory in [
        paths.root,
        paths.state_dir,
        paths.logs_dir,
        paths.submissions_dir,
        paths.notes_dir,
        paths.schema_dir,
        paths.examples_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def existing_or_new(preferred: Path, *legacy_paths: Path) -> Path:
    if preferred.exists():
        return preferred
    for legacy in legacy_paths:
        if legacy.exists():
            return legacy
    return preferred
