"""
统一日志配置模块

提供标准化的 logging 配置，支持：
- 彩色控制台输出（INFO 级及以上）
- 可配置的日志级别
- 按模块名区分日志来源

使用方式：
    from utils.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("消息内容")

控制台颜色（通过 ColorizingFormatter）：
    - DEBUG   → 灰色
    - INFO    → 白色（默认）
    - WARNING → 黄色
    - ERROR   → 红色
    - CRITICAL → 红色 + 加粗
"""

import logging
import os
import sys
import re
from typing import Optional

# Windows GBK 兼容
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# ANSI 颜色码（用于彩色终端输出）
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

_COLORS = {
    "reset":     "\033[0m",
    "bold":      "\033[1m",
    "grey":      "\033[90m",
    "red":       "\033[91m",
    "green":     "\033[92m",
    "yellow":    "\033[93m",
    "blue":      "\033[94m",
    "magenta":   "\033[95m",
    "cyan":      "\033[96m",
    "white":     "\033[97m",
}

# 级别 → 颜色映射
_LEVEL_COLORS = {
    logging.DEBUG:    _COLORS["grey"],
    logging.INFO:     _COLORS["white"],
    logging.WARNING:  _COLORS["yellow"],
    logging.ERROR:    _COLORS["red"],
    logging.CRITICAL: _COLORS["red"] + _COLORS["bold"],
}

# 级别 → 前缀文字
_LEVEL_PREFIXES = {
    logging.DEBUG:    "[DEBUG]",
    logging.INFO:     "[INFO]",
    logging.WARNING:  "[WARN]",
    logging.ERROR:    "[ERROR]",
    logging.CRITICAL: "[CRIT]",
}


class ColorizingFormatter(logging.Formatter):
    """
    带颜色的日志格式化器：

    - 自动为 WARNING 及以上级别添加颜色
    - 自动为 DEBUG 级别添加灰色
    - 保留原始日志内容，兼容非 ANSI 终端
    """

    def __init__(self, fmt: str, use_color: bool = True):
        super().__init__(fmt)
        self._use_color = use_color and _supports_color()

    def format(self, record: logging.LogRecord) -> str:
        # 复制 record，避免修改全局对象
        record = logging.makeLogRecord(record.__dict__)

        if self._use_color:
            color = _LEVEL_COLORS.get(record.levelno, _COLORS["white"])
            record.levelname = f"{color}{record.levelname}{_COLORS['reset']}"
            # 给消息本身也上色（WARNING 及以上）
            if record.levelno >= logging.WARNING:
                record.msg = f"{color}{record.msg}{_COLORS['reset']}"

        return super().format(record)


class CompactFormatter(logging.Formatter):
    """
    紧凑格式化器：去掉模块名，保留时间戳和级别。

    用于 Pipeline 耗时分析等需要紧凑输出的场景。
    """

    def __init__(self, fmt: Optional[str] = None):
        if fmt is None:
            fmt = "%(levelname)-8s %(message)s"
        super().__init__(fmt)


def _supports_color() -> bool:
    """检测终端是否支持 ANSI 颜色"""
    # 强制关闭
    if os.getenv("NO_COLOR") or os.getenv("FORCE_COLOR") == "0":
        return False
    # IDE / 非 TTY 环境下可强制开启
    if os.getenv("FORCE_COLOR") == "1":
        return True
    # 标准 TTY 检测
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        return True
    if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        return True
    return False


def _get_level() -> int:
    """从环境变量解析日志级别"""
    env_level = os.getenv("LOG_LEVEL", "INFO").upper()
    try:
        return getattr(logging, env_level, logging.INFO)
    except AttributeError:
        return logging.INFO


def setup_logging(
    level: int = None,
    use_color: bool = None,
    compact: bool = False,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    配置根日志器（一次性调用）。

    Args:
        level: 日志级别，默认从 LOG_LEVEL 环境变量读取或 INFO
        use_color: 是否使用彩色输出，默认自动检测
        compact: 是否使用紧凑格式（去掉模块名）
        log_file: 可选的文件处理器路径
    """
    if level is None:
        level = _get_level()
    if use_color is None:
        use_color = _supports_color()

    root = logging.getLogger()
    root.setLevel(level)

    # 避免重复添加 handler
    if root.handlers:
        root.handlers.clear()

    if compact:
        fmt = "%(asctime)s %(levelname)-8s %(message)s"
        datefmt = "%H:%M:%S"
        formatter = CompactFormatter()
    else:
        # [模块名] 格式便于定位日志来源
        fmt = "%(asctime)s [%(name)s] %(levelname)-8s %(message)s"
        datefmt = "%H:%M:%S"
        formatter = ColorizingFormatter(fmt, use_color=use_color)

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # 文件 handler（可选）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # 文件记录全部级别
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)-8s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """
    获取指定模块的 Logger。

    首次调用时自动初始化根日志器（幂等操作）。
    """
    logger = logging.getLogger(name)

    # 懒初始化：没有 handler 时自动设置
    if not logging.getLogger().handlers:
        setup_logging()

    return logger
