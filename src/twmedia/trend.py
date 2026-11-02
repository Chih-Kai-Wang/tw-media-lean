"""Method E (PLAN.md §5.6), v0: a local-level (random-walk) model per outlet x party, solved exactly.

    mu_t = mu_{t-1} + eta_t,   eta_t ~ N(0, tau^2 * jump_t)     (jump_t > 1 at known events, e.g. turnovers)
    y_t  = mu_t + eps_t,       eps_t ~ N(0, v_t)                 (y_t: mean stance of the period's articles)

v_t combines article-to-article spread and juror disagreement, so periods where the LLM jurors disagree get
wider intervals (PLAN.md §5.5, "不確定性怎麼算"). tau is chosen by maximising the marginal likelihood over a
grid; the Kalman filter + RTS smoother then gives the exact posterior mean and variance of mu_t. Periods with
no articles are bridged by the random walk. A hierarchical PyMC version (pooling across outlets) can replace
this later; this one is fast, has no heavy dependencies and is easy to check.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TAU_GRID = np.geomspace(0.005, 1.0, 60)


@dataclass
class Period:
    n: int  # articles with a stance for this party
    mean: float  # mean over articles of the jurors' mean stance
    var_between: float  # variance across articles of the jurors' mean stance
    var_jurors: float  # mean over articles of the variance across jurors
    jurors: int  # jurors per article


def summarize(stances: list[list[float]]) -> Period | None:
    """stances: one list of juror stances per article (None/NaN already dropped). Returns None if empty."""
    rows = [s for s in stances if len(s)]
    if not rows:
        return None
    means = np.array([np.mean(s) for s in rows])
    jvar = np.array([np.var(s, ddof=1) if len(s) > 1 else 0.0 for s in rows])
    return Period(
        n=len(rows),
        mean=float(means.mean()),
        var_between=float(means.var(ddof=1)) if len(rows) > 1 else float("nan"),
        var_jurors=float(jvar.mean()),
        jurors=int(np.median([len(s) for s in rows])),
    )


def obs_variance(p: Period, floor: float) -> float:
    """Variance of the period mean: article spread / n plus juror disagreement / (jurors * n)."""
    between = p.var_between if np.isfinite(p.var_between) else floor
    return max(between, floor) / p.n + p.var_jurors / (max(p.jurors, 1) * p.n)


def _filter(y, v, tau, jump, m0, p0):
    T = len(y)
    m_pred, p_pred, m_filt, p_filt = (np.empty(T) for _ in range(4))
    loglik, m, p = 0.0, m0, p0
    for t in range(T):
        mp = m
        pp = p + tau**2 * jump[t] if t else p0
        m_pred[t], p_pred[t] = mp, pp
        if np.isnan(y[t]):
            m, p = mp, pp
        else:
            s = pp + v[t]
            k = pp / s
            loglik += -0.5 * (np.log(2 * np.pi * s) + (y[t] - mp) ** 2 / s)
            m, p = mp + k * (y[t] - mp), (1 - k) * pp
        m_filt[t], p_filt[t] = m, p
    return m_pred, p_pred, m_filt, p_filt, loglik


def smooth(periods: list[Period | None], jump: np.ndarray | None = None, tau: float | None = None,
           prior_sd: float = 1.0) -> dict:
    """Posterior of mu_t for every period. Returns mean, sd, lo/hi (95%), chosen tau and its log-likelihood."""
    T = len(periods)
    jump = np.ones(T) if jump is None else np.asarray(jump, float)
    observed = [p for p in periods if p is not None]
    if not observed:
        raise ValueError("no observed periods")
    pooled = [p.var_between for p in observed if np.isfinite(p.var_between)]
    floor = float(np.median(pooled)) if pooled else 1.0  # for periods with a single article
    y = np.array([np.nan if p is None else p.mean for p in periods])
    v = np.array([np.nan if p is None else obs_variance(p, floor) for p in periods])
    m0, p0 = float(np.nanmean(y)), prior_sd**2

    if tau is None:
        lls = [_filter(y, v, t, jump, m0, p0)[4] for t in TAU_GRID]
        tau = float(TAU_GRID[int(np.argmax(lls))])
    m_pred, p_pred, m_filt, p_filt, ll = _filter(y, v, tau, jump, m0, p0)

    m_s, p_s = m_filt.copy(), p_filt.copy()
    for t in range(T - 2, -1, -1):  # Rauch-Tung-Striebel
        g = p_filt[t] / p_pred[t + 1]
        m_s[t] = m_filt[t] + g * (m_s[t + 1] - m_pred[t + 1])
        p_s[t] = p_filt[t] + g**2 * (p_s[t + 1] - p_pred[t + 1])
    sd = np.sqrt(p_s)
    return {"mean": m_s, "sd": sd, "lo": m_s - 1.96 * sd, "hi": m_s + 1.96 * sd, "tau": tau, "loglik": ll}
