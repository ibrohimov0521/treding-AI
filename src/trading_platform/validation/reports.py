"""Write validation reports for later inspection."""

import json
from pathlib import Path

from trading_platform.validation.candles import DataQualityReport


def save_report(report: DataQualityReport, data_dir: Path) -> Path:
    """Write a stable, human-readable report under data/reports."""
    path = (
        data_dir
        / "reports"
        / report.exchange.lower()
        / report.market_type.lower()
        / report.symbol.upper()
        / report.timeframe
        / "quality.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path
