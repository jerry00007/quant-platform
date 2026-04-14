from .strategy_service import (
    StrategyBase, DualMAStrategy, BollingerBreakStrategy,
    RSIStrategy, MACDStrategy, STRATEGY_REGISTRY, get_strategy,
    Signal, SignalType,
)
