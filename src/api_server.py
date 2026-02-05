import logging

from fastapi import FastAPI

from .api.health import health_router
from .api.ev import ev_router
from .api.position import position_router
from .api.market import market_router
from .api.pnl import pnl_router
from .api.pm import pm_router
from .api.db import db_router
from .api.options import options_router
from .api.trade import trade_router
from .api.lifespan import lifespan
from .utils.logging_config import setup_logging

setup_logging(log_file_prefix="server_proarb")
logger = logging.getLogger(__name__)

app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(ev_router)
app.include_router(position_router)
app.include_router(market_router)
app.include_router(pnl_router)
app.include_router(pm_router)
app.include_router(db_router)
app.include_router(options_router)
app.include_router(trade_router)
