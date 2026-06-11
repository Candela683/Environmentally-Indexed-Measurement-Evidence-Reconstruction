"""Analysis helpers for taxonomic and environmental summaries."""

from __future__ import annotations

import numpy as np
import pandas as pd


def summarize_taxonomic_variance(records: pd.DataFrame) -> pd.DataFrame:
    """Approximate taxonomic variance contribution with nested group means."""

    df = records.dropna(subset=["arsenic_mg_per_kg_ww"]).copy()
    df["log10_arsenic"] = np.log10(df["arsenic_mg_per_kg_ww"].clip(lower=1e-12))
    total = float(df["log10_arsenic"].var(ddof=1)) if len(df) > 1 else 0.0
    rows = []
    for rank in ["phylum", "class", "order", "family", "genus", "species"]:
        if rank not in df:
            continue
        means = df.groupby(rank, dropna=True)["log10_arsenic"].mean()
        variance = float(means.var(ddof=1)) if len(means) > 1 else 0.0
        rows.append(
            {
                "component": rank,
                "variance_proxy": variance,
                "proportion_of_total_variance": variance / total if total else np.nan,
                "n_groups": int(means.shape[0]),
            }
        )
    return pd.DataFrame(rows)


def fit_environment_models(records: pd.DataFrame, env_columns: list[str]) -> pd.DataFrame:
    """Fit one-predictor OLS summaries for environmental gradients."""

    try:
        import statsmodels.formula.api as smf
    except ImportError:
        smf = None

    df = records.dropna(subset=["arsenic_mg_per_kg_ww"]).copy()
    df["log10_arsenic"] = np.log10(df["arsenic_mg_per_kg_ww"].clip(lower=1e-12))
    rows = []
    for env in env_columns:
        if env not in df:
            continue
        work = df.dropna(subset=[env, "tissue_category", "log10_arsenic"]).copy()
        if work[env].nunique() < 2 or len(work) < 4:
            rows.append({"env_var": env, "status": "skipped", "reason": "insufficient variation or sample size"})
            continue
        sd = work[env].std(ddof=0)
        if sd == 0:
            rows.append({"env_var": env, "status": "skipped", "reason": "zero standard deviation"})
            continue
        work[f"{env}_z"] = (work[env] - work[env].mean()) / sd
        if smf is not None:
            model = smf.ols(f"log10_arsenic ~ {env}_z + C(tissue_category)", data=work).fit()
            coef = float(model.params.get(f"{env}_z", np.nan))
            p_value = float(model.pvalues.get(f"{env}_z", np.nan))
            r2 = float(model.rsquared)
            nobs = int(model.nobs)
            method = "statsmodels_ols"
        else:
            y = work["log10_arsenic"].to_numpy(dtype=float)
            x = pd.DataFrame({"intercept": 1.0, f"{env}_z": work[f"{env}_z"].to_numpy(dtype=float)})
            dummies = pd.get_dummies(work["tissue_category"], prefix="tissue", drop_first=True, dtype=float)
            x = pd.concat([x, dummies.reset_index(drop=True)], axis=1)
            beta, *_ = np.linalg.lstsq(x.to_numpy(dtype=float), y, rcond=None)
            coef = float(beta[list(x.columns).index(f"{env}_z")])
            fitted = x.to_numpy(dtype=float) @ beta
            ss_res = float(np.sum((y - fitted) ** 2))
            ss_tot = float(np.sum((y - y.mean()) ** 2))
            p_value = np.nan
            r2 = 1.0 - ss_res / ss_tot if ss_tot else np.nan
            nobs = int(len(work))
            method = "numpy_lstsq_no_p_value"
        rows.append(
            {
                "env_var": env,
                "status": "ok",
                "method": method,
                "n": nobs,
                "coef_log10_per_1sd": coef,
                "effect_percent_per_1sd": 100.0 * (10.0**coef - 1.0),
                "p_value": p_value,
                "r2": r2,
            }
        )
    return pd.DataFrame(rows)


def spearman_environment_correlation(records: pd.DataFrame, env_columns: list[str]) -> pd.DataFrame:
    """Calculate pairwise Spearman correlations among environmental variables."""

    available = [col for col in env_columns if col in records.columns]
    if not available:
        return pd.DataFrame(columns=["env_var_1", "env_var_2", "spearman_r"])
    corr = records[available].corr(method="spearman")
    rows = []
    for i, first in enumerate(available):
        for second in available[i + 1 :]:
            rows.append({"env_var_1": first, "env_var_2": second, "spearman_r": float(corr.loc[first, second])})
    return pd.DataFrame(rows)


def taxon_environment_response(
    records: pd.DataFrame,
    env_columns: list[str],
    rank: str = "phylum",
    min_records: int = 3,
) -> pd.DataFrame:
    """Fit simple within-taxon environmental summaries for eligible nodes."""

    rows = []
    if rank not in records.columns:
        return pd.DataFrame(columns=["rank", "taxon", "env_var", "status"])
    for taxon, group in records.groupby(rank, dropna=True):
        if len(group) < min_records:
            continue
        models = fit_environment_models(group, env_columns)
        if models.empty:
            continue
        models = models.copy()
        models.insert(0, "taxon", taxon)
        models.insert(0, "rank", rank)
        rows.append(models)
    if not rows:
        return pd.DataFrame(columns=["rank", "taxon", "env_var", "status"])
    return pd.concat(rows, ignore_index=True)
