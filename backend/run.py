"""
QuantWeave 量化交易平台 - 启动脚本
"""
import uvicorn
from app.core.config import get_settings

settings = get_settings()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
    )
