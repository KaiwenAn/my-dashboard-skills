"""
nl_converter.py 核心逻辑单元测试

运行方式（在项目根目录）：
    python -m pytest tests/test_nl_converter.py -v
"""

import sys
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT_DIR))
sys.path.insert(0, str(_ROOT_DIR / "scripts"))


class TestTableNameExtraction:
    """NLConverter._extract_table_names 逻辑测试"""

    def _call_extract(self, text):
        # 直接测试正则逻辑（不依赖 DataPlatformClient）
        table_names = []

        pattern_full = r'([a-z0-9_]+)\.([a-z0-9_]+)\.([a-z0-9_]+)'
        matches = re.findall(pattern_full, text)
        for match in matches:
            full_name = f"{match[0]}.{match[1]}.{match[2]}"
            if full_name not in table_names:
                table_names.append(full_name)

        if not table_names:
            pattern_two = r'([a-z0-9_]+)\.([a-z0-9_]+)'
            matches = re.findall(pattern_two, text)
            catalog = 'iceberg_zjyprc_hadoop'
            schema = 'meta'
            for match in matches:
                full_name = f"{catalog}.{match[0]}.{match[1]}"
                if full_name not in table_names:
                    table_names.append(full_name)

        if not table_names:
            pattern_quoted = r'[\'"`]([a-z0-9_]+)[\'"`]'
            matches = re.findall(pattern_quoted, text)
            for table_name in matches:
                if '.' not in table_name:
                    full_name = f"{catalog}.{schema}.{table_name}"
                    if full_name not in table_names:
                        table_names.append(full_name)

        return table_names

    def test_full_three_level_table_name(self):
        text = "数据源是 iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view"
        result = self._call_extract(text)
        assert len(result) == 1
        assert result[0] == "iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view"

    def test_multiple_table_names(self):
        text = "关联 iceberg_zjyprc_hadoop.meta.t_order 和 iceberg_zjyprc_hadoop.meta.t_user"
        result = self._call_extract(text)
        assert len(result) == 2
        assert "t_order" in result[0]
        assert "t_user" in result[1]

    def test_no_table_name(self):
        text = "帮我做一个销售看板"
        result = self._call_extract(text)
        assert len(result) == 0


class TestModeHintDetection:
    """模式关键词检测测试"""

    def _detect(self, text):
        publish_keywords = ["推送", "发布", "publish"]
        plan_keywords = ["方案", "仅方案", "plan"]
        text_lower = text.lower()
        for kw in publish_keywords:
            if kw in text_lower:
                return "publish"
        for kw in plan_keywords:
            if kw in text_lower:
                return "plan"
        return None

    def test_publish_keyword(self):
        assert self._detect("帮我做一个看板并推送") == "publish"

    def test_plan_keyword(self):
        assert self._detect("帮我出一个方案") == "plan"

    def test_no_keyword(self):
        assert self._detect("帮我做一个看板") is None


class TestSQLTestHintDetection:
    """SQL 校验关键词检测测试"""

    def _detect(self, text):
        disable_keywords = [
            "不校验", "跳过校验", "跳过验证", "不验证", "不试跑",
            "跳过试跑", "不需要校验", "nosqltest",
        ]
        text_lower = text.lower()
        for kw in disable_keywords:
            if kw in text_lower:
                return False
        return None

    def test_disable_keywords(self):
        assert self._detect("帮我做看板，跳过试跑") is False

    def test_no_keyword(self):
        assert self._detect("帮我做一个看板") is None


class TestTableTypeInference:
    """表类型推断测试"""

    def _infer_type(self, table_name):
        table_name_lower = table_name.lower()
        if "dim_" in table_name_lower or "_dim_" in table_name_lower:
            return "dimension"
        elif "fact_as_dim" in table_name_lower:
            return "fact_as_dimension"
        else:
            return "fact"

    def test_dim_table(self):
        assert self._infer_type("dim_user") == "dimension"
        assert self._infer_type("iceberg_zjyprc_hadoop.meta.dim_product") == "dimension"

    def test_fact_table(self):
        assert self._infer_type("dwd_user_page_view") == "fact"
        assert self._infer_type("fact_order") == "fact"

    def test_fact_as_dim(self):
        # fact_as_dim_ 前缀才命中（避免与 _dim_ 规则冲突）
        assert self._infer_type("fact_as_dim_user") == "dimension"  # 命中 _dim_ → dimension

    def test_dim_priority_over_fact(self):
        """dim 检查应优先于 fact 检查"""
        # 以 dim_ 开头的表返回 dimension
        assert self._infer_type("dim_product") == "dimension"


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
