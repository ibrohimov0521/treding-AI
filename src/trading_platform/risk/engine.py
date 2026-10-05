"""Independent long-only portfolio limits; this module has no exchange client."""

from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Loss thresholds are percentages; maximum exposure is a fraction of equity."""

    max_daily_loss_pct: Decimal = Decimal("2")
    max_drawdown_pct: Decimal = Decimal("8")
    max_exposure: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.max_daily_loss_pct.is_finite():
            raise ValueError("max_daily_loss_pct must be finite")
        if not self.max_drawdown_pct.is_finite():
            raise ValueError("max_drawdown_pct must be finite")
        if not self.max_exposure.is_finite():
            raise ValueError("max_exposure must be finite")
        if not ZERO < self.max_daily_loss_pct <= HUNDRED:
            raise ValueError("max_daily_loss_pct must be in (0, 100]")
        if not ZERO < self.max_drawdown_pct <= HUNDRED:
            raise ValueError("max_drawdown_pct must be in (0, 100]")
        if not ZERO <= self.max_exposure <= ONE:
            raise ValueError("max_exposure must be between 0 and 1 for Spot")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved_target: Decimal
    halted: bool
    reason: str | None
    daily_loss_pct: Decimal
    drawdown_pct: Decimal


class RiskEngine:
    """Evaluate a requested paper exposure against latched loss controls."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def assess(
        self,
        *,
        desired_target: Decimal,
        equity: Decimal,
        daily_start_equity: Decimal,
        peak_equity: Decimal,
        already_halted: bool = False,
    ) -> RiskDecision:
        if not desired_target.is_finite():
            raise ValueError("desired_target must be finite")
        if not equity.is_finite():
            raise ValueError("equity must be finite")
        if not daily_start_equity.is_finite() or not peak_equity.is_finite():
            raise ValueError("Risk reference equity must be finite")
        if not ZERO <= desired_target <= ONE:
            raise ValueError("desired_target must be between 0 and 1 for Spot")
        if daily_start_equity <= ZERO or peak_equity <= ZERO:
            raise ValueError("Risk reference equity must be positive")
        daily_loss = max(ZERO, (daily_start_equity - equity) / daily_start_equity * HUNDRED)
        drawdown = max(ZERO, (peak_equity - equity) / peak_equity * HUNDRED)

        reason: str | None = None
        halted = already_halted
        if already_halted:
            reason = "risk halt is latched; manual review is required to resume"
        elif equity <= ZERO:
            halted = True
            reason = "equity is zero or negative"
        elif daily_loss >= self.limits.max_daily_loss_pct:
            halted = True
            reason = "maximum daily loss reached"
        elif drawdown >= self.limits.max_drawdown_pct:
            halted = True
            reason = "maximum drawdown reached"

        if halted:
            approved_target = ZERO
        else:
            approved_target = min(desired_target, self.limits.max_exposure)
            if approved_target < desired_target:
                reason = "target capped by maximum exposure"
        return RiskDecision(
            approved_target=approved_target,
            halted=halted,
            reason=reason,
            daily_loss_pct=daily_loss,
            drawdown_pct=drawdown,
        )
