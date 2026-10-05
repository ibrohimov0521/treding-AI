from datetime import timedelta
from decimal import Decimal

import pytest

from trading_platform.features.engineering import compute_features
from trading_platform.observability.audit import AuditLog
from trading_platform.risk.engine import RiskEngine, RiskLimits
from trading_platform.signals.engine import SignalEngine


class AlwaysLong:
    @property
    def name(self) -> str:
        return "test_always_long"

    def target_exposure(self, features):
        return Decimal("1")


def test_signal_is_reproducible_and_risk_capped(candle_factory) -> None:
    candles = [candle_factory(index) for index in range(30)]
    feature = compute_features(candles, as_of=candles[-1].close_time + timedelta(microseconds=1))[
        -1
    ]
    engine = SignalEngine(RiskEngine(RiskLimits(max_exposure=Decimal("0.4"))))
    kwargs = {
        "current_exposure": Decimal("0"),
        "equity": Decimal("1000"),
        "daily_start_equity": Decimal("1000"),
        "peak_equity": Decimal("1000"),
    }

    first = engine.evaluate(feature, AlwaysLong(), **kwargs)
    second = engine.evaluate(feature, AlwaysLong(), **kwargs)

    assert first.signal_id == second.signal_id
    assert first.feature_hash == second.feature_hash
    assert first.status == "CAPPED"
    assert first.requested_target == "1"
    assert first.approved_target == "0.4"
    assert first.effective_target == "0.4"


def test_signal_latches_halted_risk_as_flat_target(candle_factory) -> None:
    candle = candle_factory(29)
    feature = compute_features([candle], as_of=candle.close_time + timedelta(microseconds=1))[0]
    engine = SignalEngine(RiskEngine(RiskLimits(max_daily_loss_pct=Decimal("2"))))

    decision = engine.evaluate(
        feature,
        AlwaysLong(),
        current_exposure=Decimal("1"),
        equity=Decimal("970"),
        daily_start_equity=Decimal("1000"),
        peak_equity=Decimal("1000"),
    )

    assert decision.status == "HALTED"
    assert decision.effective_target == "0"
    assert decision.risk_reason == "maximum daily loss reached"


def test_audit_log_verifies_append_chain_and_detects_tampering(tmp_path) -> None:
    path = tmp_path / "audit" / "events.jsonl"
    audit = AuditLog(path)
    first = audit.append("signal", {"symbol": "BTCUSDT", "target": "1"})
    second = audit.append("risk", {"approved": False, "reason": "halted"})

    verification = AuditLog.verify(path)
    assert verification.event_count == 2
    assert verification.last_hash == second["event_hash"]
    assert first["event_hash"] != second["event_hash"]

    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"target":"1"', '"target":"0"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash does not match"):
        AuditLog.verify(path)


def test_audit_rejects_incomplete_last_record(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"unfinished":', encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete"):
        AuditLog.verify(path)
