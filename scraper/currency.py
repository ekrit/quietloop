"""Currency and derived-metric helpers."""
from __future__ import annotations

from typing import Optional

from .config import BAM_PER_EUR


def bam_to_eur(price_bam: Optional[float]) -> Optional[float]:
    if price_bam is None:
        return None
    return round(price_bam / BAM_PER_EUR, 2)


def price_per_km(price_bam: Optional[float], mileage_km: Optional[int]) -> Optional[float]:
    if not price_bam or not mileage_km:
        return None
    return round(price_bam / mileage_km, 4)
