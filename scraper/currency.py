"""Derived-metric helpers."""
from __future__ import annotations

from typing import Optional


def price_per_km(price_bam: Optional[float], mileage_km: Optional[int]) -> Optional[float]:
    if not price_bam or not mileage_km:
        return None
    return round(price_bam / mileage_km, 4)
