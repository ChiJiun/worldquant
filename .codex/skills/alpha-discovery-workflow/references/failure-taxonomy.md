# Failure Taxonomy

Use standardized failure labels. Multiple labels are allowed, but choose one dominant bottleneck in reflection.

| failure_type | Meaning | Typical Evidence |
| --- | --- | --- |
| `direction_wrong` | Signal works in the opposite direction. | Sharpe/returns strongly negative while turnover is plausible. |
| `turnover_too_high` | Trading frequency destroys Fitness or platform checks. | Turnover above target, often above 70%. |
| `return_density_too_low` | Filtered/gated alpha trades too little or loses returns. | Turnover falls but returns/Fitness collapse. |
| `fitness_low` | Overall objective too weak. | Fitness below refinement threshold. |
| `returns_low` | Sharpe may be acceptable but absolute return is too low. | Returns fail platform or internal target. |
| `sharpe_unstable_by_year` | Performance concentrated in too few years. | Yearly Sharpe swings or many weak years. |
| `drawdown_too_high` | Tail loss or path risk is too high. | Drawdown too high relative to return. |
| `weight_concentration` | Alpha exposure is too concentrated. | Weight concentration check fails or likely fails. |
| `sub_universe_fail` | Alpha fails sub-universe robustness. | Sub-universe Sharpe/check failure. |
| `self_corr_risk` | Behavior too similar to existing alphas. | Self-correlation/behavior similarity high or pending risk. |
| `self_corr_fail` | Self-correlation check fails. | Platform self-correlation fail. |
| `self_corr_pending` | Self-correlation is not known yet. | Candidate otherwise promising but self-corr still pending. |
| `operator_invalid` | Unsupported operator or syntax. | Platform validation/simulation error. |
| `unit_incompatible` | Fields/operators have incompatible units. | Unit verification failure. |
| `platform_timeout` | Platform did not return metrics before polling limit. | Simulation timeout after a valid submission. |
| `platform_auth_error` | Authentication or network access failed. | Login failed or connection denied. |
| `over_smoothing` | Smoothing lowers turnover but also destroys edge. | Turnover improves while Sharpe/returns fall. |
| `signal_amplitude_destroyed` | Transform removes useful signal magnitude. | Full `rank()` or hard clipping lowers returns/Fitness. |
| `hard_filter_destroyed_returns` | Gating/filtering lowers turnover by removing too many profitable observations. | `trade_when` or event filter sharply reduces returns/Fitness. |
| `no_directional_edge` | Signal has no usable direction. | Metrics near zero after variants. |

Do not judge only by Sharpe. BRAIN-like Fitness commonly reflects Sharpe, returns, turnover, and other checks, so a high-Sharpe alpha with explosive turnover can still be a poor candidate.
