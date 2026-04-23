"""Signal candle selection helpers."""

from __future__ import annotations

from typing import Tuple

import pandas as pd


def _is_confirmed(value: object) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def select_signal_features(features: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    if features is None or features.empty:
        return features, "latest_only"
    if "confirm" not in features.columns:
        return features, "latest_confirmed"

    for idx in range(len(features) - 1, -1, -1):
        if _is_confirmed(features.iloc[idx].get("confirm")):
            selected = features.iloc[: idx + 1].copy()
            source = "latest_confirmed" if idx == len(features) - 1 else "previous_confirmed"
            return selected, source

    if len(features) >= 2:
        return features.iloc[:-1].copy(), "previous_confirmed"
    return features, "latest_only"
