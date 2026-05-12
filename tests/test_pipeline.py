"""
pipeline.py 编排逻辑单元测试

运行方式（在项目根目录）：
    python -m pytest tests/test_pipeline.py -v
"""

import sys
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

_ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT_DIR))


class TestPipelineConfirmationItems:
    """确认项收集与去重测试"""

    def _load_fn(self):
        from src.pipeline import Pipeline
        return Pipeline

    def test_merge_confirmation_items(self):
        """相同 category+item 应去重"""
        Pipeline = self._load_fn()

        mock_llm = MagicMock()
        p = Pipeline(llm=mock_llm)

        # 模拟注入确认项
        p._confirmation_items_buffer = [
            {"category": "指标口径", "item": "DAU的定义"},
            {"category": "指标口径", "item": "DAU的定义"},  # 重复
            {"category": "维度粒度", "item": "日期粒度"},
        ]

        result = p._merge_confirmation_items()
        assert len(result) == 2

    def test_merge_confirmation_items_risk_order(self):
        """确认项应按风险顺序排列"""
        Pipeline = self._load_fn()
        mock_llm = MagicMock()
        p = Pipeline(llm=mock_llm)

        p._confirmation_items_buffer = [
            {"category": "其他", "item": "x"},
            {"category": "指标口径", "item": "GMV口径"},
            {"category": "图表类型", "item": "用折线图"},
        ]

        result = p._merge_confirmation_items()
        # 指标口径应在最前，图表类型次之
        categories = [item["category"] for item in result]
        assert categories.index("指标口径") < categories.index("图表类型")
        assert categories.index("图表类型") < categories.index("其他")


class TestPipelineRunMode:
    """Pipeline 运行模式测试"""

    def _load_fn(self):
        from src.pipeline import Pipeline
        return Pipeline

    def test_get_start_agent_for_category_metric(self):
        """指标口径 → 从 semantic_model 开始"""
        Pipeline = self._load_fn()
        result = Pipeline.get_start_agent_for_category("指标口径")
        assert result == "semantic_model"

    def test_get_start_agent_for_category_chart(self):
        """图表类型 → 从 instruction_generator 开始"""
        Pipeline = self._load_fn()
        result = Pipeline.get_start_agent_for_category("图表类型")
        assert result == "instruction_generator"

    def test_get_start_agent_for_unknown_category(self):
        """未知类别 → 默认从 semantic_model 开始"""
        Pipeline = self._load_fn()
        result = Pipeline.get_start_agent_for_category("未知的类别")
        assert result == "semantic_model"


class TestPipelineCancel:
    """Pipeline 取消机制测试"""

    def _load_fn(self):
        from src.pipeline import Pipeline
        return Pipeline

    def test_cancel_flag(self):
        """cancel() 后 cancel 标志应为 True"""
        Pipeline = self._load_fn()
        mock_llm = MagicMock()
        p = Pipeline(llm=mock_llm)
        assert p._cancelled is False
        p.cancel()
        assert p._cancelled is True

    def test_check_cancelled_raises(self):
        """cancel 后 _check_cancelled 应抛出 InterruptedError"""
        Pipeline = self._load_fn()
        mock_llm = MagicMock()
        p = Pipeline(llm=mock_llm)
        p.cancel()
        try:
            p._check_cancelled()
            assert False, "应抛出 InterruptedError"
        except InterruptedError:
            pass


class TestPipelineProgressCallback:
    """进度回调测试"""

    def _load_fn(self):
        from src.pipeline import Pipeline
        return Pipeline

    def test_emit_calls_callback(self):
        """_emit 应调用 on_progress 回调"""
        Pipeline = self._load_fn()
        mock_llm = MagicMock()
        callback_events = []

        def on_progress(event_type, data):
            callback_events.append((event_type, data))

        p = Pipeline(llm=mock_llm, on_progress=on_progress)
        p._emit("step_start", {"agent_name": "test"})

        assert len(callback_events) == 1
        assert callback_events[0][0] == "step_start"
        assert callback_events[0][1]["agent_name"] == "test"

    def test_emit_ignores_callback_error(self):
        """回调异常不应打断主流程"""
        Pipeline = self._load_fn()
        mock_llm = MagicMock()

        def bad_callback(event_type, data):
            raise RuntimeError("callback error")

        p = Pipeline(llm=mock_llm, on_progress=bad_callback)
        # 不应抛出异常
        p._emit("step_start", {"agent_name": "test"})


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
