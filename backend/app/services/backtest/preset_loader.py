"""
QuantWeave - 策略沙盒预设加载器

从 config/strategy_presets.json 读取预设配置，
构建可直接传入 QuickPicksBacktestEngine 的 strategies_override 和 scoring_weights。

用法:
    from app.services.backtest.preset_loader import load_preset

    config = load_preset("共振策略")  # 或 "resonance-v1"
    engine = QuickPicksBacktestEngine(
        strategies_override=config["strategies_override"],
        scoring_weights=config["scoring_weights"],
        **config["backtest_params"],
    )
    result = engine.run(start_date="20240101", end_date="20260401")
"""

import json
import sys
from pathlib import Path
from loguru import logger

# ---------------------------------------------------------------------------
# 导入 CORE_STRATEGIES（需要 sys.path 操作，同 quick_picks_backtest.py 模式）
# ---------------------------------------------------------------------------
CORE_SIGNALS_PATH = Path(__file__).resolve().parent.parent / "strategy"
if str(CORE_SIGNALS_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_SIGNALS_PATH))

from core_signals import CORE_STRATEGIES  # noqa: E402

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
PRESETS_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "strategy_presets.json"

REQUIRED_SCORING_KEYS = {"tech", "base", "sentiment", "fund"}
REQUIRED_BACKTEST_PARAM_KEYS = {"max_positions", "top_n", "scan_interval", "stop_loss", "max_hold_days"}


# ---------------------------------------------------------------------------
# 内部函数
# ---------------------------------------------------------------------------

def _load_presets_json() -> dict:
    """读取并解析预设 JSON 文件。

    Returns:
        dict: 原始 JSON 内容

    Raises:
        FileNotFoundError: JSON 文件不存在
        ValueError: JSON 解析失败
    """
    if not PRESETS_FILE.exists():
        raise FileNotFoundError(
            f"预设配置文件不存在: {PRESETS_FILE}\n"
            f"请确认 config/strategy_presets.json 已正确部署。"
        )

    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"预设配置文件 JSON 解析失败: {PRESETS_FILE}\n"
            f"错误详情: {exc}"
        ) from exc


def _extract_presets(raw: dict) -> dict:
    """从原始 JSON 中提取有效预设（跳过 _meta 键）。

    Args:
        raw: json.load() 的原始返回值

    Returns:
        dict: {preset_id: preset_config, ...}
    """
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _match_preset(presets: dict, query: str):
    """根据 preset_id 或 short_names 匹配预设。

    Args:
        presets: _extract_presets() 的返回值
        query: 用户输入的预设 ID 或别名

    Returns:
        tuple: (preset_id, preset_config) 或 (None, None)
    """
    # 1. 精确匹配 preset_id
    if query in presets:
        return query, presets[query]

    # 2. 大小写不敏感精确匹配 preset_id
    lower_query = query.lower()
    for pid, preset in presets.items():
        if pid.lower() == lower_query:
            return pid, preset

    # 3. 模糊匹配 short_names（大小写不敏感）
    for pid, preset in presets.items():
        short_names = preset.get("short_names", [])
        for alias in short_names:
            if alias.lower() == lower_query:
                return pid, preset

    return None, None


def _validate_preset(preset: dict, preset_id: str) -> None:
    """校验预设配置的完整性和合法性。

    Args:
        preset: 单个预设配置 dict
        preset_id: 预设 ID（用于错误消息）

    Raises:
        ValueError: 校验失败时抛出
    """
    # --- 校验 strategies ---
    strategies = preset.get("strategies")
    if not strategies or not isinstance(strategies, list):
        raise ValueError(
            f"预设 '{preset_id}' 的 strategies 必须是非空列表，"
            f"当前值: {strategies!r}"
        )

    invalid = [s for s in strategies if s not in CORE_STRATEGIES]
    if invalid:
        valid_keys = list(CORE_STRATEGIES.keys())
        raise ValueError(
            f"预设 '{preset_id}' 包含无效策略名: {invalid}\n"
            f"有效策略名: {valid_keys}"
        )

    # --- 校验 scoring_weights ---
    weights = preset.get("scoring_weights")
    if not weights or not isinstance(weights, dict):
        raise ValueError(
            f"预设 '{preset_id}' 缺少 scoring_weights 或类型错误，"
            f"当前值: {weights!r}"
        )

    missing_keys = REQUIRED_SCORING_KEYS - set(weights.keys())
    if missing_keys:
        raise ValueError(
            f"预设 '{preset_id}' 的 scoring_weights 缺少键: {missing_keys}\n"
            f"需要: {REQUIRED_SCORING_KEYS}"
        )

    weight_sum = sum(weights.values())
    if not (0.95 <= weight_sum <= 1.05):
        logger.warning(
            f"预设 '{preset_id}' 的 scoring_weights 权重之和 = {weight_sum:.4f}，"
            f"不在 [0.95, 1.05] 范围内，请确认是否故意。"
        )

    # --- 校验 backtest_params ---
    bt_params = preset.get("backtest_params")
    if not bt_params or not isinstance(bt_params, dict):
        raise ValueError(
            f"预设 '{preset_id}' 缺少 backtest_params 或类型错误，"
            f"当前值: {bt_params!r}"
        )

    missing_bt = REQUIRED_BACKTEST_PARAM_KEYS - set(bt_params.keys())
    if missing_bt:
        raise ValueError(
            f"预设 '{preset_id}' 的 backtest_params 缺少键: {missing_bt}\n"
            f"需要: {REQUIRED_BACKTEST_PARAM_KEYS}"
        )


def _build_strategies_override(strategy_names: list) -> dict:
    """根据策略名列表构建 strategies_override dict。

    每个条目的结构与 quick_picks_backtest.py 中 ACTIVE_STRATEGIES 一致：
    {
        "name": str,
        "func": callable,
        "needs_full": bool,
        "params": dict,
        "exit_config": dict,
    }

    Args:
        strategy_names: 策略键名列表，如 ["dual_ma", "pullback_stable"]

    Returns:
        dict: {strategy_key: {name, func, needs_full, params, exit_config}, ...}

    Raises:
        ValueError: 策略名不在 CORE_STRATEGIES 中
    """
    override = {}
    for name in strategy_names:
        if name not in CORE_STRATEGIES:
            raise ValueError(
                f"策略 '{name}' 不在 CORE_STRATEGIES 中。"
                f"可用策略: {list(CORE_STRATEGIES.keys())}"
            )
        entry = CORE_STRATEGIES[name]
        override[name] = {
            "name": entry["name"],
            "func": entry["func"],
            "needs_full": len(entry["needs"]) > 1,
            "params": entry["default_params"],
            "exit_config": entry["exit_config"],
        }
    return override


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def load_preset(preset_id_or_alias: str) -> dict:
    """加载并验证预设配置，返回可直接用于回测引擎的配置 dict。

    Args:
        preset_id_or_alias: 预设 ID（如 "resonance-v1"）或别名（如 "共振策略"）

    Returns:
        dict: {
            "preset_id": str,
            "preset_name": str,
            "is_verified": bool,
            "description": str,
            "strategies_override": dict,
            "scoring_weights": dict,
            "backtest_params": dict,
            "use_ml_timing": bool | None,
        }

    Raises:
        FileNotFoundError: 预设 JSON 文件不存在
        ValueError: JSON 解析失败 / 预设不存在 / 预设校验失败
    """
    raw = _load_presets_json()
    presets = _extract_presets(raw)

    preset_id, preset = _match_preset(presets, preset_id_or_alias)
    if preset_id is None or preset is None:
        available = []
        for pid, p in presets.items():
            aliases = p.get("short_names", [])
            available.append(f"  - {pid} (别名: {', '.join(aliases)})")
        raise ValueError(
            f"未找到预设 '{preset_id_or_alias}'。\n"
            f"可用预设:\n" + "\n".join(available)
        )

    logger.info(f"匹配到预设: {preset_id} ({preset.get('name', '')})")

    _validate_preset(preset, preset_id)

    strategies_override = _build_strategies_override(preset["strategies"])

    return {
        "preset_id": preset_id,
        "preset_name": preset["name"],
        "is_verified": preset.get("is_verified", False),
        "description": preset.get("description", ""),
        "strategies_override": strategies_override,
        "scoring_weights": preset["scoring_weights"],
        "backtest_params": preset["backtest_params"],
        "use_ml_timing": preset.get("use_ml_timing"),
    }


def list_presets() -> list:
    """列出所有可用预设的摘要信息。

    Returns:
        list[dict]: 每个元素包含 id, name, short_names, is_verified,
                    description, strategies 字段
    """
    raw = _load_presets_json()
    presets = _extract_presets(raw)

    result = []
    for pid, p in presets.items():
        result.append({
            "id": pid,
            "name": p.get("name", ""),
            "short_names": p.get("short_names", []),
            "is_verified": p.get("is_verified", False),
            "description": p.get("description", ""),
            "strategies": p.get("strategies", []),
        })
    return result
