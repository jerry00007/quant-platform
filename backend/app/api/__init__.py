from .data_api import router as data_router
from .strategy_api import router as strategy_router
from .backtest_api import router as backtest_router
from .risk_api import router as risk_router
from .system_api import router as system_router
from .screening_api import router as screening_router
from .portfolio_api import router as portfolio_router
from .report_api import router as report_router
from .market_api import router as market_router

all_routers = [data_router, strategy_router, backtest_router, risk_router, system_router, screening_router, portfolio_router, report_router, market_router]
