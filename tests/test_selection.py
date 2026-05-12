import csv

from app.selection import run_selection_pipeline


def test_selection_pipeline_clusters_high_corr_variants(tmp_path):
    research_dir = tmp_path / "research"
    output_dir = tmp_path / "outputs"
    research_dir.mkdir(parents=True)
    (research_dir / "passed_alphas.csv").write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                '2026-05-10T00:00:00Z,A1,price_volume,"rank(returns) + rank(volume / adv20)",alpha-1,1.3,1.1,0.10,0.05,0.20,validate_best_candidate',
                '2026-05-10T00:01:00Z,A2,price_volume,"rank(returns) + rank(volume / adv20) + 0.1 * rank(vwap / close)",alpha-2,1.6,1.4,0.12,0.05,0.20,validate_best_candidate',
                '2026-05-10T00:02:00Z,N1,news,"rank(ts_backfill(news_max_up_ret, 120))",alpha-3,1.5,1.2,0.09,0.04,0.18,validate_best_candidate',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_selection_pipeline(research_dir, output_dir)

    assert report["record_count"] == 3
    assert (output_dir / "candidate_alphas.csv").exists()
    assert (output_dir / "alpha_registry.csv").exists()
    assert (output_dir / "alpha_correlation_matrix.csv").exists()
    assert (output_dir / "alpha_clusters.json").exists()
    assert (output_dir / "submit_queue.csv").exists()
    assert (output_dir / "final_alpha_recommendations.md").exists()

    with (output_dir / "best_alphas.csv").open("r", encoding="utf-8", newline="") as handle:
        best_rows = list(csv.DictReader(handle))
    best_ids = {row["alpha_id"] for row in best_rows}
    assert "alpha-2" in best_ids
    assert "alpha-1" not in best_ids

    rejected = (output_dir / "rejected_high_corr_alphas.csv").read_text(encoding="utf-8")
    assert "alpha-1" in rejected
    assert "alpha-2" in rejected


def test_selection_pipeline_excludes_high_corr_submitted_alpha(tmp_path):
    research_dir = tmp_path / "research"
    output_dir = tmp_path / "outputs"
    (research_dir / "logs").mkdir(parents=True)
    (research_dir / "submissions").mkdir(parents=True)
    (research_dir / "logs" / "passed_alphas.csv").write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                '2026-05-10T00:00:00Z,A1,price_volume,"rank(returns) + rank(volume / adv20)",alpha-1,1.5,1.3,0.10,0.05,0.20,validate_best_candidate',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (research_dir / "submissions" / "submitted_alphas.csv").write_text(
        "\n".join(
            [
                "alpha_id,candidate_id,family,expression,sharpe,fitness,returns,drawdown,turnover",
                'submitted-1,S1,price_volume,"rank(returns) + rank(volume / adv20)",1.4,1.2,0.09,0.05,0.20',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_selection_pipeline(research_dir, output_dir)

    assert report["submitted_count"] == 1
    assert report["submit_queue_count"] == 0
    rejected = (output_dir / "rejected_high_corr_alphas.csv").read_text(encoding="utf-8")
    assert "high_corr_with_submitted_alpha" in rejected
    assert "submitted-1" in rejected
    report_text = (output_dir / "final_alpha_recommendations.md").read_text(encoding="utf-8")
    assert "No alpha passed all submit queue gates" in report_text


def test_selection_pipeline_rejects_hypothesis_meaning_drift(tmp_path):
    research_dir = tmp_path / "research"
    output_dir = tmp_path / "outputs"
    (research_dir / "logs").mkdir(parents=True)
    (research_dir / "logs" / "passed_alphas.csv").write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                '2026-05-10T00:00:00Z,A1,news_event_response,"rank(returns)",alpha-1,1.5,1.3,0.10,0.05,0.20,validate_best_candidate',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_selection_pipeline(research_dir, output_dir)

    assert report["submit_queue_count"] == 0
    rejected = (output_dir / "rejected_high_corr_alphas.csv").read_text(encoding="utf-8")
    assert "hypothesis_economic_meaning_drift" in rejected


def test_selection_pipeline_finalizes_state_and_can_clear_candidates(tmp_path):
    research_dir = tmp_path / "research"
    output_dir = tmp_path / "outputs"
    candidate_file = tmp_path / "data" / "candidates.jsonl"
    (research_dir / "logs").mkdir(parents=True)
    candidate_file.parent.mkdir(parents=True)
    candidate_file.write_text('{"candidate_id":"next","expression":"rank(close)"}\n', encoding="utf-8")
    (research_dir / "logs" / "passed_alphas.csv").write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                '2026-05-10T00:00:00Z,A1,price_volume,"rank(returns) + rank(volume / adv20)",alpha-1,1.5,1.3,0.10,0.05,0.20,validate_best_candidate',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_selection_pipeline(
        research_dir,
        output_dir,
        finalize=True,
        candidate_file=candidate_file,
        clear_candidates=True,
    )

    assert report["finalized"] is True
    assert candidate_file.read_text(encoding="utf-8") == ""
    assert (research_dir / "state" / "latest_final_selection_report.json").exists()
    assert (research_dir / "logs" / "final_selection_reports.jsonl").exists()
