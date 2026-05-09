"""ML策略选股API"""
from fastapi import APIRouter, HTTPException
import subprocess, json, os, math

router = APIRouter(prefix="/ml", tags=["ML策略"])

PYTHON = "/opt/anaconda3/envs/quant-platform/bin/python"
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "output")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")


@router.get("/picks")
async def get_ml_picks():
    """获取最新ML选股结果"""
    # 查找最新的选股JSON
    output_dir = os.path.abspath(OUTPUT_DIR)
    picks_files = sorted([f for f in os.listdir(output_dir) if f.startswith("ml_picks_") and f.endswith(".json")])
    
    if not picks_files:
        # 没有缓存结果，运行选股
        script = os.path.join(SCRIPTS_DIR, "ml_picks_today.py")
        try:
            result = subprocess.run(
                [PYTHON, script],
                capture_output=True, text=True, timeout=120,
                cwd=PROJECT_ROOT,
                env={**os.environ, "PYTHONPATH": BACKEND_DIR},
            )
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=f"选股执行失败: {result.stderr[-200:]}")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail="选股执行超时(120s)")
        
        # 重新查找
        picks_files = sorted([f for f in os.listdir(output_dir) if f.startswith("ml_picks_") and f.endswith(".json")])
    
    if not picks_files:
        raise HTTPException(status_code=404, detail="无选股结果")
    
    latest_file = os.path.join(output_dir, picks_files[-1])
    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    data = _sanitize(data)
    
    return {
        "status": "success",
        "data": data
    }


@router.post("/picks")
async def refresh_ml_picks():
    """重新运行ML选股脚本"""
    output_dir = os.path.abspath(OUTPUT_DIR)
    script = os.path.join(SCRIPTS_DIR, "ml_picks_today.py")
    try:
        result = subprocess.run(
            [PYTHON, script],
            capture_output=True, text=True, timeout=180,
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONPATH": BACKEND_DIR},
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"选股执行失败: {result.stderr[-300:]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="选股执行超时(180s)")

    picks_files = sorted([f for f in os.listdir(output_dir) if f.startswith("ml_picks_") and f.endswith(".json")])
    if not picks_files:
        raise HTTPException(status_code=404, detail="选股完成但未生成结果文件")

    latest_file = os.path.join(output_dir, picks_files[-1])
    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    data = _sanitize(data)

    return {
        "status": "success",
        "data": data
    }


def _sanitize(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


@router.get("/strategy-info")
async def get_strategy_info():
    """获取ML策略信息"""
    return {
        "status": "success",
        "data": {
            "name": "共振+ML择时 v2.0",
            "description": "机器学习趋势回调反弹策略",
            "model": "HistGradientBoostingClassifier",
            "features": 18,
            "params": {
                "prob_threshold": 0.55,
                "hold_days": 3,
                "top_n": 3,
                "stop_loss": -0.07,
                "pullback_depth": -0.03,
                "max_positions": 6,
            },
            "backtest": {
                "period": "2024.08 ~ 2026.04 (2年)",
                "total_return": 98.68,
                "sharpe": 1.948,
                "max_drawdown": -9.03,
                "win_rate": 51.5,
                "total_trades": 802,
                "stop_loss_count": 43,
            },
            "triple_verified": True,
            "triple_review": {
                "hawk": "✅ 训练样本55万条，无数据泄露，止损率5.4%",
                "fox": "✅ 夏普1.948，回撤-9.03%，参数鲁棒",
                "owl": "✅ 802笔交易统计显著，hold=3天核心优化",
            }
        }
    }
