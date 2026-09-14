"""M1 unit tests for the party-agent local data layer. Synthetic data only."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "services/party-agent"
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))
