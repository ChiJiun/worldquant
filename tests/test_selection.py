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

    with (output_dir / "best_alphas.csv").open("r", encoding="utf-8", newline="") as handle:
        best_rows = list(csv.DictReader(handle))
    best_ids = {row["alpha_id"] for row in best_rows}
    assert "alpha-2" in best_ids
    assert "alpha-1" not in best_ids

    rejected = (output_dir / "rejected_high_corr_alphas.csv").read_text(encoding="utf-8")
    assert "alpha-1" in rejected
    assert "alpha-2" in rejected
