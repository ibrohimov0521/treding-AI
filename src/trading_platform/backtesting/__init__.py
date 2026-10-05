"""Offline historical simulation. No exchange order APIs are used here."""

from trading_platform.backtesting.engine import BacktestConfig, BacktestResult, run_backtest

__all__ = ["BacktestConfig", "BacktestResult", "run_backtest"]
