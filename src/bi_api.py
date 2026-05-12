"""
BI平台API封装：通过Open API自动创建并发布语义模型

API文档：
- POST /os/open-apis/model          → 创建模型骨架，返回 modelId
- POST /os/open-apis/model/publish → 发布模型（SQL + 字段结构 + 维度指标配置）

认证方式：请求体中通过 creator/modifier 字段指定操作人，无需认证头。
"""

import json
import time
import httpx
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class BIConfig:
    """BI平台连接配置"""
    # 必需字段
    datasource_id: int      # 数据源ID（对应 API 中的 datasourceId）
    creator: str            # 创建人（对应 API 中的 creator/modifier）
    # 可选字段
    datasource_type: int = 1  # 数据源类型，默认 MySQL (code=1)
    base_url: str = ""         # BI平台API地址（不含 /os 前缀），不填则使用默认地址
    model_kind: int = 1         # 模型类型，默认 1

    def get_base_url(self) -> str:
        """获取API基础地址（不含 /os 前缀，后端自动拼接）"""
        return self.base_url.strip().rstrip("/") if self.base_url else "https://staging-api-smp.dt.mi.com"


@dataclass
class SemanticModel:
    """
    语义模型数据（来自 SemanticModelAgent 的输出）
    """
    model_name: str
    purpose: str
    sql: str
    tables_used: list
    dimensions: list = field(default_factory=list)
    metrics: list = field(default_factory=list)
    join_logic: list = field(default_factory=list)
    filter_config: dict = field(default_factory=dict)
    quality_notes: list = field(default_factory=list)


# ============================================================
# 工具函数
# ============================================================

def _sql_to_virtual_table(sql: str, dimensions: list, metrics: list) -> dict:
    """
    从 SQL 和字段配置生成 virtualTable 结构

    根据 BI 平台真实请求格式，virtualTable 包含：
    - name: 虚拟表名，格式为 sql_virtual_table_{时间戳}
    - fields: 字段映射数组，每个元素包含 table/field/alias/type
    - filters: 过滤条件数组（暂为空）
    - construct: 字段结构数组，每个元素包含 tableName/columnName/typeName
    - code: 固定为 0

    Args:
        sql: 完整的 SELECT 语句
        dimensions: 维度字段列表
        metrics: 指标字段列表

    Returns:
        virtualTable dict
    """
    # 生成唯一的虚拟表名（与 BI 平台真实请求格式保持一致）
    table_name = f"sql_virtual_table_{int(time.time() * 1000)}"

    # 构建 fields 数组（字段映射）
    fields = []
    construct = []

    # 按 dimensions + metrics 的 field_name 顺序构建
    all_fields = [(d, "dim") for d in dimensions] + [(m, "metric") for m in metrics]

    for field_info, field_type in all_fields:
        field_name = field_info.get("field_name", "")
        data_type = field_info.get("data_type", "STRING")

        # fields 数组：使用简单类型名（int/string/double）
        type_name_simple = _map_to_typename(data_type)
        fields.append({
            "table": table_name,
            "field": field_name,
            "alias": field_name,
            "type": type_name_simple,
        })

        # construct 数组：也使用简单类型名
        construct.append({
            "tableName": table_name,
            "columnName": field_name,
            "typeName": type_name_simple,
        })

    return {
        "name": table_name,
        "fields": fields,
        "filters": [],
        "construct": construct,
        "code": 0,
    }


def _build_analysis_vo(dimensions: list, metrics: list) -> dict:
    """
    从维度/指标配置生成 analysisVO 结构

    根据 BI 平台真实请求格式，analysisVO 包含：
    - dimension: 普通维度（字符串类型），每个字段包含 extInfo/alias/code/multilingual/position
    - timeDimension: 时间维度（日期/时间类型），真实请求中为 timeDimesion（API拼写错误）
    - index: 指标（数值类型），每个字段包含 extInfo/alias/code/multilingual/position
    - dimensionLevel: 维度层级（暂为空数组）
    - timeLevel: 时间层级（包含年/月/日 层级）
    - dimensionGroups: 维度分组（暂为空数组）

    Args:
        dimensions: 维度字段列表
        metrics: 指标字段列表

    Returns:
        analysisVO dict
    """
    dimension_list = []
    time_dimension_list = []

    # 构建维度列表（普通维度 + 时间维度）
    position = 2  # 从2开始（真实请求中的起始值）
    for dim in dimensions:
        field_name = dim.get("field_name", "")
        label = dim.get("bi_config", {}).get("label", field_name) if isinstance(dim.get("bi_config"), dict) else field_name
        semantic_type = dim.get("semantic_type", "")
        data_type = dim.get("data_type", "STRING")

        # 时间维度 vs 普通维度
        if semantic_type in ("日期", "时间维度") or data_type in ("DATE", "TIMESTAMP"):
            # 时间维度：暂时不添加到 time_dimension_list，而是添加到 timeLevel
            pass  # 时间维度的处理在 timeLevel 中
        else:
            # 普通维度
            dimension_list.append({
                "name": field_name,
                "label": label,
                "type": "string",
                "fieldType": 1,  # AnalysisTypeEnum: 维度=1
                "extInfo": {
                    "weekOfFirstDayCode": 1,
                    "yearOfFirstWeekCode": 4,
                    "isMultiChoice": 0,
                    "isMybatisParam": 0,
                },
                "originName": field_name,
                "alias": field_name,
                "code": 0,
                "multilingual": [],
                "isEdited": False,  # 真实请求中使用 False
                "position": position,
            })
            position += 1

    # 构建 timeLevel（时间层级），包含年/月/日 三个层级
    date_field = None
    for dim in dimensions:
        if dim.get("semantic_type") in ("日期", "时间维度") or dim.get("data_type") in ("DATE", "TIMESTAMP"):
            date_field = dim
            break

    if date_field:
        date_name = date_field.get("field_name", "date")
        time_level = {
            "alias": date_name,
            "children": [
                {
                    "name": f"substring({date_name},1,4)",
                    "label": f"{date_name}_年",
                    "type": "date",
                    "fieldType": 1,
                    "extInfo": {
                        "dateStorageFormat": "yyyy",
                        "dateDisplayFormat": "yyyy",
                        "dateStorageType": "number",
                        "originStorageFormat": "yyyyMMdd",
                    },
                    "originName": date_name,
                    "alias": f"{date_name}_年",
                    "code": 0,
                    "unit": "year",
                    "multilingual": [],
                    "isEdited": False,
                    "order": 3,
                },
                {
                    "name": f"DATE_FORMAT({date_name},'%Y%m')",
                    "label": f"{date_name}_月",
                    "type": "date",
                    "fieldType": 1,
                    "extInfo": {
                        "dateStorageFormat": "yyyyMM",
                        "dateDisplayFormat": "yyyyMM",
                        "dateStorageType": "number",
                        "originStorageFormat": "yyyyMMdd",
                    },
                    "originName": date_name,
                    "alias": f"{date_name}_月",
                    "code": 0,
                    "unit": "month",
                    "multilingual": [],
                    "isEdited": False,
                    "order": 2,
                },
                {
                    "name": date_name,
                    "label": f"{date_name}_天",
                    "type": "date",
                    "fieldType": 1,
                    "extInfo": {
                        "dateStorageFormat": "yyyyMMdd",
                        "dateDisplayFormat": "yyyyMMdd",
                        "dateStorageType": "number",
                        "originStorageFormat": "yyyyMMdd",
                    },
                    "originName": date_name,
                    "alias": f"{date_name}_天",
                    "code": 0,
                    "unit": "day",
                    "multilingual": [],
                    "isEdited": False,
                    "order": 1,
                },
            ],
            "code": 0,
            "dateFormat": "yyyyMMdd",
            "multilingual": [],
            "isEdited": False,
            "originName": date_name,
            "levelName": date_name,
            "position": 1,
        }
    else:
        time_level = None

    # 构建指标列表
    index_list = []
    position = 12  # 从12开始（真实请求中的起始值）
    for metric in metrics:
        field_name = metric.get("field_name", "")
        label = metric.get("bi_config", {}).get("label", field_name) if isinstance(metric.get("bi_config"), dict) else field_name
        aggregation = metric.get("aggregation", "SUM")
        data_type = metric.get("data_type", "DOUBLE")

        index_list.append({
            "name": field_name,
            "label": label,
            "type": "number",
            "fieldType": 2,  # AnalysisTypeEnum: 指标=2
            "aggregator": _normalize_aggregator(aggregation).lower(),  # 真实请求中使用小写（sum/avg等）
            "extInfo": {
                "digit": 2,
                "formatter": "number",
                "weekOfFirstDayCode": 1,
                "yearOfFirstWeekCode": 4,
                "isMultiChoice": 0,
                "isMybatisParam": 0,
                "isNewIndex": True,
            },
            "originName": field_name,
            "alias": field_name,
            "code": 0,
            "multilingual": [],
            "isEdited": False,  # 真实请求中使用 False
            "position": position,
        })
        position += 1

    result = {
        "dimension": dimension_list,
        "dimensionLevel": [],
        "dimensionGroups": [],
        "timeDimesion": [],  # 注意：真实请求中拼写错误，必须是 timeDimesion
        "index": index_list,
    }

    if time_level:
        result["timeLevel"] = [time_level]
    else:
        result["timeLevel"] = []

    return result


def _python_type_to_sql_type(data_type: str) -> str:
    """将 Python/JSON 类型名映射为 SQL 类型名"""
    mapping = {
        "STRING": "VARCHAR",
        "INT": "BIGINT",
        "INTEGER": "BIGINT",
        "BIGINT": "BIGINT",
        "DOUBLE": "DOUBLE",
        "DECIMAL": "DECIMAL",
        "FLOAT": "FLOAT",
        "DATE": "DATE",
        "TIMESTAMP": "TIMESTAMP",
        "DATETIME": "DATETIME",
        "BOOLEAN": "BOOLEAN",
    }
    return mapping.get(data_type.upper(), "VARCHAR")


def _map_to_typename(data_type: str) -> str:
    """
    将 Python/JSON 类型名映射为 BI 平台 virtualTable.construct 所需的简单类型名

    BI 平台 virtualTable.construct[].typeName 字段只支持以下简单类型名：
    - int: 整数类型（DATE/DATETIME/TIMESTAMP/INT/INTEGER/BIGINT）
    - double: 浮点数类型（DOUBLE/DECIMAL/FLOAT）
    - string: 字符串类型（STRING/VARCHAR/BOOLEAN）

    注意：不要使用 SQL 类型名（如 VARCHAR/BIGINT/DECIMAL），否则接口会报"未识别异常"
    """
    data_type_upper = data_type.upper()
    # 整数类型（包括日期类型）
    if data_type_upper in ("INT", "INTEGER", "BIGINT", "DATE", "DATETIME", "TIMESTAMP"):
        return "int"
    # 浮点数类型
    elif data_type_upper in ("DOUBLE", "DECIMAL", "FLOAT"):
        return "double"
    # 字符串类型（默认）
    else:
        return "string"


def _normalize_aggregator(aggregation: str) -> str:
    """规范化聚合函数名（转大写）"""
    agg_map = {
        "sum": "SUM",
        "count": "COUNT",
        "count_distinct": "COUNT_DISTINCT",
        "avg": "AVG",
        "max": "MAX",
        "min": "MIN",
        "自定义": "SUM",  # 衍生指标默认用 SUM，后续可按需调整
        "custom": "SUM",
    }
    return agg_map.get(aggregation.lower(), aggregation.upper())


def _infer_time_unit(data_type: str) -> str:
    """根据数据类型推断时间粒度"""
    mapping = {
        "DATE": "day",
        "TIMESTAMP": "second",
        "DATETIME": "second",
    }
    return mapping.get(data_type.upper(), "day")


# ============================================================
# BI API Client
# ============================================================

class BIClient:
    """
    BI平台 Open API 客户端

    用法：
        config = BIConfig(datasource_id=123, creator="zhangsan", datasource_type=1)
        client = BIClient(config)
        model_id = client.create_model("订单分析模型")
        client.publish_model(model_id, sql, dimensions, metrics)
    """

    def __init__(self, config: BIConfig):
        self.config = config
        self.base_url = config.get_base_url()
        self.timeout = httpx.Timeout(30.0, connect=10.0)

    def _post(self, path: str, payload: dict) -> dict:
        """发送 POST 请求到 BI 平台"""
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            code = result.get("code", -1)
            if code not in (0, 200):
                raise ValueError(f"BI API 错误: code={code}, msg={result.get('msg', '')}")
            return result

    def _get(self, path: str, params: dict = None) -> dict:
        """发送 GET 请求到 BI 平台"""
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            result = response.json()
            code = result.get("code", -1)
            if code not in (0, 200):
                raise ValueError(f"BI API 错误: code={code}, msg={result.get('msg', '')}")
            return result

    @staticmethod
    def get_datasource_id(user: str, space_id: int, base_url: str = "") -> int:
        """
        第零步：根据用户名和工场空间ID获取数据源连接ID

        Args:
            user: 用户名
            space_id: 工场空间ID
            base_url: BI平台API地址，不填则使用默认生产环境地址

        Returns:
            datasourceId（整数）

        Raises:
            ValueError: 接口返回错误或查不到数据源
        """
        url = (base_url.strip().rstrip("/") if base_url else "https://api-smp.dt.mi.com")
        full_url = f"{url}/os/source/open-apis/datasource"
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = client.get(full_url, params={"user": user, "spaceId": str(space_id)})
            response.raise_for_status()
            result = response.json()
            code = result.get("code", -1)
            if code not in (0, 200):
                raise ValueError(f"获取数据源ID失败: code={code}, msg={result.get('msg', '')}")
            datasource_id = result.get("data")
            if datasource_id is None:
                raise ValueError(f"查不到数据源: user={user}, spaceId={space_id}")
            print(f"  [成功] 获取数据源ID成功: datasourceId={datasource_id}")
            return int(datasource_id)

    def create_model(self, model_name: str) -> int:
        """
        第一步：创建模型骨架

        Args:
            model_name: 模型名称

        Returns:
            modelId（整数）

        Raises:
            ValueError: API 返回错误
        """
        payload = {
            "name": model_name,
            "datasourceId": self.config.datasource_id,
            "datasourceType": self.config.datasource_type,
            "creator": self.config.creator,
            "modelKind": self.config.model_kind,
        }
        result = self._post("/os/open-apis/model", payload)
        model_id = result.get("data")
        if model_id is None:
            raise ValueError(f"创建模型失败，API 返回: {result}")
        print(f"  [成功] 模型骨架创建成功，modelId={model_id}")
        return int(model_id)

    def publish_model(
        self,
        model_id: int,
        model_name: str,
        sql: str,
        semantic_model: SemanticModel,
    ) -> int:
        """
        第二步：发布模型（SQL + 字段结构 + 维度指标配置）

        Args:
            model_id: 模型ID（来自 create_model 返回值）
            model_name: 模型名称（用于展示）
            sql: 完整的 SELECT 语句
            semantic_model: 语义模型数据（来自 Agent 输出）

        Returns:
            modelId（与输入相同，发布成功后返回）

        Raises:
            ValueError: API 返回错误
        """
        # 构建 virtualTable
        virtual_table = _sql_to_virtual_table(
            sql=sql,
            dimensions=semantic_model.dimensions,
            metrics=semantic_model.metrics,
        )

        # 构建 analysisVO
        analysis_vo = _build_analysis_vo(
            dimensions=semantic_model.dimensions,
            metrics=semantic_model.metrics,
        )

        payload = {
            "modelId": model_id,
            "modifier": self.config.creator,
            "type": 4,          # SQL模型类型
            "isSqlModel": 1,    # 标识为SQL模型
            "datasourceId": self.config.datasource_id,
            "sqlInfo": sql,
            "virtualTable": virtual_table,
            "analysisVO": analysis_vo,
        }

        result = self._post("/os/open-apis/model/publish", payload)
        print(f"  [成功] 模型发布成功，modelId={model_id}")
        return model_id

    def create_and_publish(
        self,
        model_name: str,
        semantic_model: SemanticModel,
    ) -> int:
        """
        完整流程：创建模型 + 发布（串行调用两步API）

        Args:
            model_name: 模型名称
            semantic_model: 语义模型数据

        Returns:
            modelId

        Raises:
            ValueError: 任何一步 API 调用失败
        """
        # 第一步：创建模型骨架
        model_id = self.create_model(model_name)

        # 第二步：发布模型
        self.publish_model(
            model_id=model_id,
            model_name=model_name,
            sql=semantic_model.sql,
            semantic_model=semantic_model,
        )

        return model_id


# ============================================================
# 顶层便捷函数
# ============================================================

def create_and_publish_all(
    bi_config: dict,
    semantic_models_output: dict,
) -> dict:
    """
    便捷入口：将语义模型Agent输出批量发布到BI平台

    Args:
        bi_config: BI平台配置（来自 user_input.bi_config）
            {
                "datasource_id": 123,
                "creator": "zhangsan",
                "datasource_type": 1,   # 可选，默认1
                "base_url": "...",      # 可选
            }
        semantic_models_output: 语义模型Agent的完整输出
            {
                "semantic_models": [...]
            }

    Returns:
        {
            "total": 成功发布的模型数量,
            "results": [
                {"model_name": "xxx", "model_id": 123},
                ...
            ],
            "errors": [
                {"model_name": "xxx", "error": "..."},
                ...
            ]
        }
    """
    config = BIConfig(
        datasource_id=bi_config["datasource_id"],
        creator=bi_config["creator"],
        datasource_type=bi_config.get("datasource_type", 1),
        base_url=bi_config.get("base_url", ""),
        model_kind=bi_config.get("model_kind", 1),
    )

    client = BIClient(config)
    semantic_models = semantic_models_output.get("semantic_models", [])

    results = []
    errors = []

    for model_data in semantic_models:
        try:
            sm = SemanticModel(
                model_name=model_data.get("model_name", ""),
                purpose=model_data.get("purpose", ""),
                sql=model_data.get("sql", ""),
                tables_used=model_data.get("tables_used", []),
                dimensions=model_data.get("dimensions", []),
                metrics=model_data.get("metrics", []),
                join_logic=model_data.get("join_logic", []),
                filter_config=model_data.get("filter_config", {}),
                quality_notes=model_data.get("quality_notes", []),
            )
            model_id = client.create_and_publish(
                model_name=sm.model_name,
                semantic_model=sm,
            )
            results.append({
                "model_name": sm.model_name,
                "model_id": model_id,
            })
        except Exception as e:
            errors.append({
                "model_name": model_data.get("model_name", "?"),
                "error": str(e),
            })

    return {
        "total": len(results),
        "results": results,
        "errors": errors,
    }
