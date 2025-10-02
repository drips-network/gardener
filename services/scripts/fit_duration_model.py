#!/usr/bin/env python3
"""
Fit a parsimonious log-linear model and emit DURATION_MODEL_JSON

Features used:
- log1p_supported_code_total_bytes
- log1p_manifests_total_bytes
- manifests_present_count
- lang_share__JavaScript
- lang_share__TypeScript
- lang_share__Python
"""

import argparse
import json

import numpy as np
import pandas as pd


FEATURES = [
    "log1p_supported_code_total_bytes",
    "log1p_manifests_total_bytes",
    "manifests_present_count",
    "lang_share__JavaScript",
    "lang_share__TypeScript",
    "lang_share__Python",
]


def fit_log_linear(csv_path, out_json, version):
    df = pd.read_csv(csv_path)
    df = df.dropna(subset=["analysis_duration_seconds"])  # keep rows with target
    X = df[FEATURES].astype(float).copy()
    y = np.log(df["analysis_duration_seconds"].values.astype(float))

    mu = X.mean().values
    sigma = X.std(ddof=0).replace(0, 1).values
    Z = (X.values - mu) / sigma

    B = np.linalg.lstsq(np.c_[np.ones(len(Z)), Z], y, rcond=None)[0]
    intercept = float(B[0])
    beta = [float(v) for v in B[1:]]

    yhat = intercept + Z.dot(B[1:])
    # Residual std in log-space with dof adjustment
    s_res = float(np.std(y - yhat, ddof=len(FEATURES) + 1))

    model = {
        "version": version,
        "features": FEATURES,
        "mu": [float(v) for v in mu],
        "sigma": [float(v) for v in sigma],
        "beta": beta,
        "intercept": intercept,
        "s_res": s_res,
        "bias_correction": 0.5,
        "safety_multiplier": 1.10,
    }
    with open(out_json, "w") as f:
        json.dump(model, f, indent=2)
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", default="duration-v1")
    args = ap.parse_args()
    fit_log_linear(args.csv, args.out, args.version)
