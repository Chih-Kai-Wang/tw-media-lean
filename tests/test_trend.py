import numpy as np

from twmedia.trend import smooth, summarize


def _periods(truth, n, rng, jurors=3, noise=0.8):
    out = []
    for mu, k in zip(truth, n):
        arts = [list(np.clip(np.round(mu + rng.normal(0, noise) + rng.normal(0, 0.3, jurors)), -2, 2)) for _ in range(k)]
        out.append(summarize(arts) if k else None)
    return out


def test_recovers_slow_drift_and_bridges_gaps():
    rng = np.random.default_rng(0)
    truth = np.linspace(-0.5, 0.5, 36)
    n = np.full(36, 60)
    n[10:13] = 0  # three months with no articles
    fit = smooth(_periods(truth, n, rng))
    assert np.mean(np.abs(fit["mean"] - truth)) < 0.12
    assert fit["sd"][11] > fit["sd"][5]  # wider where there is no data
    assert np.mean((fit["lo"] <= truth) & (truth <= fit["hi"])) > 0.8


def test_jump_at_known_event_is_followed_quickly():
    rng = np.random.default_rng(1)
    truth = np.r_[np.full(24, -0.6), np.full(24, 0.6)]
    jump = np.ones(48)
    jump[24] = 400.0  # e.g. a change of ownership announced for that month
    fit = smooth(_periods(truth, np.full(48, 80), rng), jump=jump)
    assert abs(fit["mean"][24] - 0.6) < 0.25 and abs(fit["mean"][23] + 0.6) < 0.25


def test_events_config_aligns_to_periods():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from fit_trends import load_events

    mult, ev = load_events("month")
    assert mult > 1
    assert [e["period"] for e in ev["*"]] == ["2016-05"]  # the only KMT<->DPP turnover in range
    assert "2015-01" in [e["period"] for e in ev["news_tvbs"]]  # month-only dates fall in their month
    assert all(o == "*" or o.startswith("news_") for o in ev)
    assert load_events("week")[1]["*"][0]["period"] == "2016-W20"
