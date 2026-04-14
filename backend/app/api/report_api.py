"""
QuantWeave - 报告导出 API
支持将回测结果导出为 Excel (.xlsx) 和 JSON 格式
"""
import os
import json
import datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.config import get_settings
from ..models.models import BacktestResult
from ..services.report.report_exporter import ReportExporter

router = APIRouter(prefix="/report", tags=["报告导出"])

settings = get_settings()
EXPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "exports")


@router.post("/export/excel", summary="导出回测Excel报告")
def export_excel_report(data: dict, db: Session = Depends(get_db)):
    """
    导出回测结果为 Excel 文件。
    
    两种模式：
    1. 传入 results 字典（完整回测结果）
    2. 传入 backtest_ids 列表（从数据库拉取结果）
    
    body: {
        "results": {...},           // 可选，直接传入回测结果
        "backtest_ids": [1, 2, 3],  // 可选，从数据库拉取指定回测
        "filename": "my_report"     // 可选，自定义文件名
    }
    """
    results = data.get("results")
    backtest_ids = data.get("backtest_ids", [])
    filename = data.get("filename")

    # 如果没有直接传入 results，从数据库拉取
    if not results and backtest_ids:
        results = _build_results_from_db(db, backtest_ids)
    elif not results:
        # 拉取所有回测结果
        bt_records = db.query(BacktestResult).order_by(BacktestResult.created_at.desc()).limit(50).all()
        if not bt_records:
            raise HTTPException(status_code=404, detail="没有可导出的回测结果")
        results = _build_results_from_records(bt_records)

    if not results:
        raise HTTPException(status_code=404, detail="没有可导出的回测数据")

    if not filename:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backtest_report_{timestamp}.xlsx"
    elif not filename.endswith(".xlsx"):
        filename += ".xlsx"

    exporter = ReportExporter(output_dir=EXPORT_DIR)
    filepath = exporter.export_excel(results, filename=filename)

    if not filepath:
        raise HTTPException(status_code=500, detail="Excel 导出失败，请检查 openpyxl 依赖是否已安装")

    return {
        "success": True,
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "message": f"报告已导出: {os.path.basename(filepath)}"
    }


@router.post("/export/json", summary="导出回测JSON摘要")
def export_json_report(data: dict, db: Session = Depends(get_db)):
    """导出精简版 JSON 汇总"""
    results = data.get("results")
    backtest_ids = data.get("backtest_ids", [])
    filename = data.get("filename")

    if not results and backtest_ids:
        results = _build_results_from_db(db, backtest_ids)
    elif not results:
        bt_records = db.query(BacktestResult).order_by(BacktestResult.created_at.desc()).limit(50).all()
        if not bt_records:
            raise HTTPException(status_code=404, detail="没有可导出的回测结果")
        results = _build_results_from_records(bt_records)

    if not results:
        raise HTTPException(status_code=404, detail="没有可导出的回测数据")

    if not filename:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backtest_summary_{timestamp}.json"
    elif not filename.endswith(".json"):
        filename += ".json"

    exporter = ReportExporter(output_dir=EXPORT_DIR)
    filepath = exporter.export_json_summary(results, filename=filename)

    return {
        "success": True,
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "message": f"JSON 摘要已导出: {os.path.basename(filepath)}"
    }


@router.get("/download/{filename}", summary="下载导出的报告文件")
def download_report(filename: str):
    """下载已导出的报告文件"""
    filepath = os.path.join(EXPORT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/list", summary="列出已导出的报告")
def list_reports():
    """列出 exports 目录下的所有报告文件"""
    if not os.path.exists(EXPORT_DIR):
        return {"files": []}

    files = []
    for f in os.listdir(EXPORT_DIR):
        filepath = os.path.join(EXPORT_DIR, f)
        if os.path.isfile(filepath) and (f.endswith(".xlsx") or f.endswith(".json") or f.endswith(".pdf")):
            stat = os.stat(filepath)
            files.append({
                "filename": f,
                "size_kb": round(stat.st_size / 1024, 2),
                "created_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "type": f.split(".")[-1],
            })

    files.sort(key=lambda x: x["created_at"], reverse=True)
    return {"files": files, "total": len(files)}


# ========== 辅助函数 ==========

def _build_results_from_db(db: Session, backtest_ids: list) -> dict:
    """从数据库 BacktestResult 记录构建导出用 results 字典"""
    records = db.query(BacktestResult).filter(BacktestResult.id.in_(backtest_ids)).all()
    return _build_results_from_records(records)


def _build_results_from_records(records: list) -> dict:
    """将 BacktestResult ORM 记录转为 {stock_code: {strategy: metrics}} 结构"""
    results = {}
    for r in records:
        stock_code = getattr(r, "ts_code", "unknown")
        strategy_key = f"strategy_{r.strategy_id}"

        if stock_code not in results:
            results[stock_code] = {}

        results[stock_code][strategy_key] = {
            "total_return": r.total_return or 0,
            "annual_return": r.annual_return or 0,
            "max_drawdown": r.max_drawdown or 0,
            "sharpe_ratio": r.sharpe_ratio or 0,
            "win_rate": r.win_rate or 0,
            "profit_loss_ratio": r.profit_loss_ratio or 0,
            "total_trades": r.total_trades or 0,
        }
    return results
