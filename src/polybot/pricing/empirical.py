"""Model 2: empirical model trained from recorded intervals.

A regularized logistic regression (numpy IRLS/gradient descent, no sklearn
dependency) over :mod:`polybot.pricing.features` vectors labeled with the
actual interval outcome. Trained offline via ``polybot train`` from the
recorded captures; persisted as versioned JSON with feature standardization
parameters. The live process refuses to load a model trained on fewer than
``empirical_min_training_samples`` samples.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from polybot.pricing.features import FEATURE_NAMES, FeatureVector

FloatArray = NDArray[np.float64]

MODEL_VERSION = 1


@dataclass(frozen=True)
class EmpiricalModel:
    weights: FloatArray  # includes bias as last element
    mean: FloatArray
    scale: FloatArray
    training_samples: int
    trained_at: float
    version: int = MODEL_VERSION

    def probability_up(self, features: FeatureVector) -> float:
        x = (np.asarray(features.as_list(), dtype=np.float64) - self.mean) / self.scale
        z = float(x @ self.weights[:-1] + self.weights[-1])
        return float(1.0 / (1.0 + np.exp(-np.clip(z, -30, 30))))

    def save(self, path: str | Path) -> None:
        payload = {
            "version": self.version,
            "feature_names": list(FEATURE_NAMES),
            "weights": self.weights.tolist(),
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "training_samples": self.training_samples,
            "trained_at": self.trained_at,
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: str | Path, *, min_samples: int) -> EmpiricalModel | None:
        target = Path(path)
        if not target.is_file():
            return None
        payload = json.loads(target.read_text())
        if payload.get("version") != MODEL_VERSION:
            return None
        if payload.get("feature_names") != list(FEATURE_NAMES):
            return None
        if int(payload.get("training_samples", 0)) < min_samples:
            return None
        return cls(
            weights=np.asarray(payload["weights"], dtype=np.float64),
            mean=np.asarray(payload["mean"], dtype=np.float64),
            scale=np.asarray(payload["scale"], dtype=np.float64),
            training_samples=int(payload["training_samples"]),
            trained_at=float(payload["trained_at"]),
        )


def train_logistic(
    features: FloatArray,
    labels: FloatArray,
    *,
    l2: float = 1.0,
    max_iter: int = 500,
    tol: float = 1e-8,
) -> EmpiricalModel:
    """Train standardized L2-regularized logistic regression via Newton-IRLS."""
    if features.ndim != 2 or features.shape[0] != labels.shape[0]:
        raise ValueError("features/labels shape mismatch")
    n_samples, n_features = features.shape
    if n_features != len(FEATURE_NAMES):
        raise ValueError(f"expected {len(FEATURE_NAMES)} features, got {n_features}")

    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    scale[scale < 1e-9] = 1.0
    x = (features - mean) / scale
    x_bias = np.hstack([x, np.ones((n_samples, 1))])
    y = labels.astype(np.float64)

    w = np.zeros(n_features + 1)
    reg = np.full(n_features + 1, l2)
    reg[-1] = 0.0  # do not regularize the bias
    for _ in range(max_iter):
        z = np.clip(x_bias @ w, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        gradient = x_bias.T @ (p - y) + reg * w
        weight = np.clip(p * (1 - p), 1e-6, None)
        hessian = (x_bias * weight[:, None]).T @ x_bias + np.diag(reg + 1e-9)
        step = np.linalg.solve(hessian, gradient)
        w -= step
        if float(np.max(np.abs(step))) < tol:
            break

    return EmpiricalModel(
        weights=w,
        mean=mean,
        scale=scale,
        training_samples=n_samples,
        trained_at=time.time(),
    )
