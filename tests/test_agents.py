"""
agents.py 核心验证逻辑单元测试

运行方式（在项目根目录）：
    python -m pytest tests/test_agents.py -v
"""

import sys
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加根目录到 sys.path（模拟运行时路径）
_ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT_DIR))


class TestCrossValidateRequirements:
    """cross_validate_requirements 交叉校验逻辑测试"""

    def _load_fn(self):
        from src.agents import cross_validate_requirements
        return cross_validate_requirements

    def test_matching_dim_field(self):
        """维度字段在 key_fields 中存在 → 无警告"""
        cross_validate = self._load_fn()

        req_output = {
            "parsed_requirements": {
                "dimensions_spec": [
                    {"name": "user_id", "source_table": "t_user"}
                ]
            }
        }
        user_input = {
            "data_sources": [
                {
                    "table_name": "t_user",
                    "key_fields": ["user_id", "name"]
                }
            ]
        }

        warnings = cross_validate(req_output, user_input)
        assert len(warnings) == 0

    def test_missing_source_table(self):
        """source_table 指向不存在的表 → 警告"""
        cross_validate = self._load_fn()

        req_output = {
            "parsed_requirements": {
                "dimensions_spec": [
                    {"name": "user_id", "source_table": "t_ghost"}
                ]
            }
        }
        user_input = {
            "data_sources": [
                {"table_name": "t_user", "key_fields": ["user_id"]}
            ]
        }

        warnings = cross_validate(req_output, user_input)
        assert len(warnings) == 1
        assert "t_ghost" in warnings[0]

    def test_field_mapping_alias(self):
        """维度字段是 field_mappings 的 value（别名）→ 警告建议使用 key"""
        cross_validate = self._load_fn()

        req_output = {
            "parsed_requirements": {
                "dimensions_spec": [
                    {"name": "买家ID", "source_table": "t_order"}
                ]
            }
        }
        user_input = {
            "data_sources": [
                {
                    "table_name": "t_order",
                    "key_fields": ["order_id", "buyer_id"],
                    "field_mappings": {
                        "buyer_id": "买家ID"
                    }
                }
            ]
        }

        warnings = cross_validate(req_output, user_input)
        assert len(warnings) == 1
        assert "buyer_id" in warnings[0]

    def test_no_matching_field(self):
        """维度字段既不在 key_fields 也不在 field_mappings → 警告"""
        cross_validate = self._load_fn()

        req_output = {
            "parsed_requirements": {
                "dimensions_spec": [
                    {"name": "xyz_field", "source_table": "t_user"}
                ]
            }
        }
        user_input = {
            "data_sources": [
                {"table_name": "t_user", "key_fields": ["user_id", "name"]}
            ]
        }

        warnings = cross_validate(req_output, user_input)
        assert len(warnings) == 1
        assert "xyz_field" in warnings[0]


class TestRequirementsParserValidation:
    """RequirementsParserAgent 校验逻辑测试（无需 LLM）"""

    def _load_fn(self):
        from src.agents import RequirementsParserAgent
        return RequirementsParserAgent

    def test_missing_parsed_requirements(self):
        """输出缺少 parsed_requirements → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "llm") as mock:
            with patch.object(agent, "system_prompt", ""):
                mock.chat_json.return_value = {}

                with patch.object(agent, "build_user_message", return_value=""):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "parsed_requirements" in str(e)

    def test_empty_metrics_spec(self):
        """metrics_spec 为空 → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "system_prompt", ""):
            with patch.object(agent, "build_user_message", return_value=""):
                with patch.object(agent.llm, "chat_json", return_value={
                    "parsed_requirements": {"metrics_spec": []},
                    "confirmation_items": [{"item": "x"}]
                }):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "metrics_spec" in str(e)

    def test_empty_confirmation_items(self):
        """confirmation_items 为空 → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "system_prompt", ""):
            with patch.object(agent, "build_user_message", return_value=""):
                with patch.object(agent.llm, "chat_json", return_value={
                    "parsed_requirements": {
                        "metrics_spec": [{"name": "DAU", "confidence": 0.9}],
                    },
                    "confirmation_items": []
                }):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "confirmation_items" in str(e)

    def test_dimension_missing_source_table(self):
        """维度缺少 source_table → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "system_prompt", ""):
            with patch.object(agent, "build_user_message", return_value=""):
                with patch.object(agent.llm, "chat_json", return_value={
                    "parsed_requirements": {
                        "metrics_spec": [{"name": "DAU", "confidence": 0.9}],
                        "dimensions_spec": [{"name": "date"}]  # 缺少 source_table
                    },
                    "confirmation_items": [{"item": "x"}]
                }):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "source_table" in str(e)


class TestSemanticModelValidation:
    """SemanticModelAgent 校验逻辑测试"""

    def _load_fn(self):
        from src.agents import SemanticModelAgent
        return SemanticModelAgent

    def test_missing_semantic_models(self):
        """输出缺少 semantic_models → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "system_prompt", ""):
            with patch.object(agent, "build_user_message", return_value=""):
                with patch.object(agent.llm, "chat_json", return_value={}):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "semantic_model" in str(e)

    def test_model_missing_sql(self):
        """模型缺少 sql 字段 → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "system_prompt", ""):
            with patch.object(agent, "build_user_message", return_value=""):
                with patch.object(agent.llm, "chat_json", return_value={
                    "semantic_models": [
                        {
                            "model_name": "test_model",
                            "dimensions": [{"field_name": "dt"}],
                            "metrics": [{"field_name": "cnt"}]
                        }
                    ]
                }):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "sql" in str(e)

    def test_dim_metric_field_overlap(self):
        """维度和指标字段名重复 → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "system_prompt", ""):
            with patch.object(agent, "build_user_message", return_value=""):
                with patch.object(agent.llm, "chat_json", return_value={
                    "semantic_models": [
                        {
                            "model_name": "test_model",
                            "sql": "SELECT 1",
                            "dimensions": [{"field_name": "user_id"}],
                            "metrics": [{"field_name": "user_id"}]  # 重复！
                        }
                    ]
                }):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "重复" in str(e)

    def test_custom_metric_missing_depends_on(self):
        """衍生指标缺少 depends_on → ValueError"""
        AgentClass = self._load_fn()
        mock_llm = MagicMock()
        agent = AgentClass(mock_llm)

        with patch.object(agent, "system_prompt", ""):
            with patch.object(agent, "build_user_message", return_value=""):
                with patch.object(agent.llm, "chat_json", return_value={
                    "semantic_models": [
                        {
                            "model_name": "test_model",
                            "sql": "SELECT 1",
                            "dimensions": [{"field_name": "dt"}],
                            "metrics": [
                                {"field_name": "cnt", "aggregation": "SUM"},
                                {"field_name": "avg_price", "aggregation": "自定义"}  # 缺少 depends_on
                            ]
                        }
                    ]
                }):
                    try:
                        agent.run({})
                        assert False, "应抛出 ValueError"
                    except ValueError as e:
                        assert "depends_on" in str(e)


class TestBIPushValidation:
    """BI 推送相关校验函数测试"""

    def _load_fns(self):
        from src.agents import validate_bi_config, validate_publish_mode_output, extract_bi_config
        return validate_bi_config, validate_publish_mode_output, extract_bi_config

    def test_validate_bi_config_none(self):
        validate, _, _ = self._load_fns()
        result = validate(None)
        assert result != ""

    def test_validate_bi_config_missing_space_id(self):
        validate, _, _ = self._load_fns()
        result = validate({"creator": "kai"})
        assert "space_id" in result

    def test_validate_bi_config_invalid_space_id(self):
        validate, _, _ = self._load_fns()
        result = validate({"space_id": "abc", "creator": "kai"})
        assert "space_id" in result

    def test_validate_bi_config_ok(self):
        validate, _, _ = self._load_fns()
        result = validate({"space_id": 123, "creator": "kai"})
        assert result == ""

    def test_validate_publish_mode_empty_sql(self):
        _, validate, _ = self._load_fns()
        output = {
            "semantic_models": [
                {
                    "model_name": "m1",
                    "sql": "",
                    "dimensions": [{"name": "d1"}],
                    "metrics": [{"field_name": "cnt", "sql_expression": "count(1)"}]
                }
            ]
        }
        result = validate(output)
        assert "SQL 为空" in result

    def test_validate_publish_mode_missing_dims(self):
        _, validate, _ = self._load_fns()
        output = {
            "semantic_models": [
                {
                    "model_name": "m1",
                    # SQL 需要 >= 20 字符才能通过前两项检查
                    "sql": "SELECT * FROM t_user WHERE dt = '2024-01-01'",
                    "dimensions": [],
                    "metrics": [{"field_name": "cnt", "sql_expression": "count(1)"}]
                }
            ]
        }
        result = validate(output)
        assert "维度" in result

    def test_validate_publish_mode_missing_metrics(self):
        _, validate, _ = self._load_fns()
        output = {
            "semantic_models": [
                {
                    "model_name": "m1",
                    "sql": "SELECT * FROM t_user WHERE dt = '2024-01-01'",
                    "dimensions": [{"name": "d1"}],
                    "metrics": []
                }
            ]
        }
        result = validate(output)
        assert "指标" in result

    def test_validate_publish_mode_metric_missing_expression(self):
        _, validate, _ = self._load_fns()
        output = {
            "semantic_models": [
                {
                    "model_name": "m1",
                    "sql": "SELECT * FROM t_user WHERE dt = '2024-01-01'",
                    "dimensions": [{"name": "d1"}],
                    "metrics": [{"field_name": "cnt"}]  # 缺少 sql_expression
                }
            ]
        }
        result = validate(output)
        assert "sql_expression" in result

    def test_extract_bi_config(self):
        _, _, extract = self._load_fns()
        user_input = {"bi_config": {"space_id": 123, "creator": "kai"}}
        result = extract(user_input)
        assert result == {"space_id": 123, "creator": "kai"}

    def test_extract_bi_config_missing(self):
        _, _, extract = self._load_fns()
        user_input = {}
        result = extract(user_input)
        assert result is None


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
