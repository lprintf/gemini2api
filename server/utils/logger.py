"""
Per-browser-tab 日志工具

每个 browser-tab 组合拥有独立的 logger，同时输出到：
- 控制台（带 [B{browser_id}:T{tab_id}] 前缀）
- 文件（data/log/{date}/{browser_id}-{tab_id}.log）
"""

import logging
import os
from datetime import datetime
from pathlib import Path

# 优先级：环境变量 DATA_DIR > 容器内路径 /app/data > 相对路径推导
DATA_DIR_STR = os.getenv("DATA_DIR", "/app/data")
DATA_DIR = Path(DATA_DIR_STR)
if not DATA_DIR.is_absolute():
    DATA_DIR = Path(__file__).parent.parent.parent / "data"

LOG_DIR = DATA_DIR / "log"

# 缓存已创建的 logger，key = "browser_id-tab_id:date"
_loggers: dict = {}


def get_tab_logger(browser_id: str, tab_id: int) -> logging.Logger:
    """获取或创建 browser-tab 专用 logger（按日期自动切换文件）"""
    key = f"{browser_id}-{tab_id}"
    date_str = datetime.now().strftime("%Y%m%d")
    cache_key = f"{key}:{date_str}"

    if cache_key in _loggers:
        return _loggers[cache_key]

    logger = logging.getLogger(f"tab.{key}")
    # 清除旧 handler（日期变更时）
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    tag = f"B{browser_id}:T{tab_id}"

    # 控制台 handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(f"[{tag}] %(message)s"))
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)

    # 文件 handler
    log_dir = LOG_DIR / date_str
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(
        log_dir / f"{browser_id}-{tab_id}.log", encoding="utf-8"
    )
    fh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    )
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    _loggers[cache_key] = logger
    return logger


def tab_log(page, msg: str, level: str = "info", silent: bool = False):
    """从 page 对象获取 logger 并记录日志，fallback 到 print"""
    logger = getattr(page, "_logger", None)
    if logger:
        if silent:
            # 仅输出到 FileHandler
            for handler in logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    record = logger.makeRecord(logger.name, getattr(logging, level.upper()), "", 0, msg, None, None)
                    handler.emit(record)
        else:
            getattr(logger, level)(msg)
    elif not silent:
        print(f"[Action] {msg}")
