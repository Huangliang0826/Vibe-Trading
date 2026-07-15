"""SignalProvider: the one-method interface every scanner signal source implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from src.scanner.core import Candidate


class SignalProvider(ABC):
    """A signal source. Implementations rank a cross-section into Candidates.

    Attributes:
        provider_id: Stable identifier surfaced in Candidate.provider_id and the
            enablement manifest.
    """

    provider_id: str = ""

    @abstractmethod
    def compute(self, panel: dict[str, pd.DataFrame], asof: str) -> list[Candidate]:
        """Rank the universe as of ``asof`` using only data up to and including it.

        Args:
            panel: Column-keyed wide OHLCV(+amount/vwap) frames (date x symbol),
                already truncated by the caller to rows <= asof.
            asof: ISO ``YYYY-MM-DD`` close date being scanned.

        Returns:
            Possibly-empty list of Candidates (unranked; core sorts them).
        """
        raise NotImplementedError
