"""
数据平台API封装
封装数据平台SQL查询相关HTTP接口，提供简化的Python调用方式
"""
import json
import time
import requests
from typing import Optional, Dict, List, Any


class DataPlatformError(Exception):
    """数据平台API通用异常"""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class AuthenticationError(DataPlatformError):
    """认证失败异常 (4007402)"""
    pass


class SQLExecutionError(DataPlatformError):
    """SQL执行异常 (4007406)"""
    pass


class ConnectionError(DataPlatformError):
    """连接异常"""
    pass


class DataPlatformClient:
    """
    数据平台API客户端
    
    使用方式：
        # 方式1：不传 catalog/schema（SQL中使用完整三级表名）
        client = DataPlatformClient(
            base_url="https://proxy-service-http-cnbj1-dp.api.xiaomi.net",
            token="your_token"
        )
        
        # 方式2：传 catalog/schema（可选）
        client = DataPlatformClient(
            base_url="https://proxy-service-http-cnbj1-dp.api.xiaomi.net",
            token="your_token",
            catalog="iceberg_zjyprc_hadoop",
            schema="meta"
        )
        
        # 执行查询（SQL中可以使用完整三级表名）
        result = client.execute_query("SELECT * FROM iceberg_zjyprc_hadoop.meta.table1")
        
        # 分步执行（需要更多控制时使用）
        query_id = client.submit_query("SELECT 1")
        client.wait_for_completion(query_id)
        result = client.fetch_results(query_id)
        client.close_query(query_id)
        
    注意：
        - catalog 和 schema 是可选参数（根据API文档，这两个请求头不是必填项）
        - 如果SQL中使用完整三级表名（catalog.schema.table），可以不传这两个参数
        - 如果SQL中只使用表名或两级表名，建议传 catalog 和 schema
    """
    
    def __init__(
        self,
        base_url: str,
        token: str,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        engine: str = "Presto",
        timeout: int = 300
    ):
        """
        初始化客户端
        
        Args:
            base_url: 数据平台API基础地址，如 https://proxy-service-http-cnbj1-dp.api.xiaomi.net
            token: 认证token，会通过 X-SqlProxy-User 请求头传递
            catalog: 数据目录（可选，SQL中可使用完整三级表名如 catalog.schema.table）
            schema: 数据库schema（可选，SQL中可使用完整三级表名）
            engine: 执行引擎，默认 Presto（可选 Presto/Spark）
            timeout: 查询超时时间（秒），默认300秒
        """
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.catalog = catalog
        self.schema = schema
        self.engine = engine
        self.timeout = timeout
        self.session = requests.Session()
        
    def _get_headers(self) -> Dict[str, str]:
        """构建请求头"""
        headers = {
            "X-SqlProxy-User": self.token,
            "X-SqlProxy-Engine": self.engine,
            "Content-Type": "application/json"
        }
        # 只在有值时添加 catalog 和 schema（根据API文档，这两个参数不是必填项）
        if self.catalog:
            headers["X-SqlProxy-Catalog"] = self.catalog
        if self.schema:
            headers["X-SqlProxy-Schema"] = self.schema
        return headers
    
    def _handle_error(self, error_code: str, error_msg: str):
        """根据错误码抛出对应异常"""
        error_map = {
            "4007402": AuthenticationError,
            "4007406": SQLExecutionError,
        }
        exc_class = error_map.get(error_code, DataPlatformError)
        raise exc_class(error_code, error_msg)
    
    def submit_query(self, sql: str) -> str:
        """
        异步提交SQL查询
        
        Args:
            sql: 要执行的SQL语句
            
        Returns:
            query_id: 查询ID，用于后续查询状态和获取结果
            
        Raises:
            AuthenticationError: 认证失败
            ConnectionError: 网络连接异常
            DataPlatformError: 其他API错误
        """
        url = f"{self.base_url}/olap/api/v2/statement/query"
        # submit_query 必须发送原始 SQL 文本作为 body
        # 如果用 json= 发送 {"sql": "..."}, 数据平台会把整个 JSON
        # body 当成 SQL 交给 Spark 执行 → syntax error at '{'
        headers = self._get_headers()
        headers["Content-Type"] = "text/plain"
        
        try:
            resp = self.session.post(
                url,
                data=sql.encode('utf-8'),
                headers=headers,
                timeout=30
            )
            
            # 打印完整请求和响应（调试用）
            print(f"[DEBUG] 请求URL: {url}")
            print(f"[DEBUG] 请求Headers: {headers}")
            print(f"[DEBUG] 请求Body（原始SQL，前200字符）: {sql[:200]}...")
            print(f"[DEBUG] 响应状态码: {resp.status_code}")
            print(f"[DEBUG] 响应内容: {resp.text}")
            
            resp.raise_for_status()
            data = resp.json()

            # 实际响应格式：{"meta": {"errCode": 0, "errMsg": ""}, "data": {"queryId": "..."}}
            # 判断逻辑：meta.errCode == 0 表示成功
            meta = data.get("meta", {})
            if meta.get("errCode") == 0:
                query_id = data.get("data", {}).get("queryId")
                if not query_id:
                    raise DataPlatformError("UNKNOWN", "响应中缺少queryId")
                return query_id
            else:
                error_code = str(meta.get("errCode", "UNKNOWN"))
                error_msg = meta.get("errMsg", "未知错误")
                print(f"[ERROR] API返回错误: code={error_code}, message={error_msg}")
                print(f"[ERROR] 完整响应: {data}")
                self._handle_error(error_code, error_msg)
                
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] 网络请求异常: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[ERROR] 响应内容: {e.response.text}")
            raise ConnectionError("CONNECTION", f"网络连接异常: {str(e)}")
    
    def get_status(self, query_id: str) -> Dict[str, Any]:
        """
        获取查询执行状态
        
        Args:
            query_id: 查询ID
            
        Returns:
            状态字典，包含以下字段：
            - status: 状态码（RUNNING/SUCCESS/FAILED/CANCELLED等）
            - nextQueryId: 获取结果时使用的queryId（可能与原始queryId不同）
            - errorCode: 错误码（如果失败）
            - errorMsg: 错误信息（如果失败）
            - percent: 执行进度百分比
            
        Raises:
            ConnectionError: 网络连接异常
            DataPlatformError: API返回错误
        """
        url = f"{self.base_url}/olap/api/v2/statement/getStatusAndLog"
        params = {"queryId": query_id}

        try:
            resp = self.session.post(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            # 实际响应格式：{"meta": {"errCode": 0}, "data": {...}}
            meta = data.get("meta", {})
            if meta.get("errCode") == 0:
                result = data.get("data", {})
                state = result.get("state", "")
                if state == "ERROR":
                    print(f"[DEBUG] getStatusAndLog ERROR: state={state}")
                    print(f"[DEBUG] 完整data: {json.dumps(result, ensure_ascii=False, indent=2)[:3000]}")
                return result
            else:
                error_code = str(meta.get("errCode", "UNKNOWN"))
                error_msg = meta.get("errMsg", "未知错误")
                self._handle_error(error_code, error_msg)
                
        except requests.exceptions.RequestException as e:
            raise ConnectionError("CONNECTION", f"网络连接异常: {str(e)}")
    
    def wait_for_completion(
        self,
        query_id: str,
        timeout: Optional[int] = None,
        poll_interval: float = 2.0
    ) -> Dict[str, Any]:
        """
        轮询等待查询执行完成
        
        Args:
            query_id: 查询ID
            timeout: 超时时间（秒），默认使用初始化时的timeout
            poll_interval: 轮询间隔（秒），默认2秒
            
        Returns:
            最终状态字典（同get_status返回值）
            
        Raises:
            TimeoutError: 查询超时
            SQLExecutionError: SQL执行失败
            ConnectionError: 网络连接异常
        """
        if timeout is None:
            timeout = self.timeout
            
        start_time = time.time()
        
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"查询超时（{timeout}秒），query_id: {query_id}")
            
            status_data = self.get_status(query_id)
            state = status_data.get("state", "")
            
            # 状态说明（根据API文档）：
            # PENDING: 等待中
            # RUNNING: 执行中
            # FINISHED: 执行成功
            # CLOSED: 已关闭（可能是取消或超时）
            # TIMEOUT: 超时
            # ERROR: 执行失败
            
            if state == "FINISHED":
                return status_data
            elif state == "ERROR":
                error_code = status_data.get("errorCode", "UNKNOWN")
                error_msg = status_data.get("errorMsg", "SQL执行失败")
                # 尝试更多可能的错误字段名
                if error_msg == "SQL执行失败":
                    error_msg = status_data.get("error", status_data.get("errMsg", error_msg))
                print(f"[DEBUG] SQL执行失败: errorCode={error_code}, errorMsg={error_msg}")
                print(f"[DEBUG] 完整status_data keys: {list(status_data.keys())}")
                raise SQLExecutionError(error_code, error_msg)
            elif state == "TIMEOUT":
                raise DataPlatformError("TIMEOUT", "查询超时")
            elif state in ("PENDING", "RUNNING", "CLOSED"):
                time.sleep(poll_interval)
            else:
                # 未知状态，继续轮询
                time.sleep(poll_interval)
    
    def fetch_results(
        self,
        query_id: str,
        max_rows: int = 1000,
        close_after_fetch: bool = False
    ) -> List[Dict[str, Any]]:
        """
        批量获取查询结果
        
        Args:
            query_id: 查询ID（或nextQueryId）
            max_rows: 单次获取的最大行数，默认1000
            close_after_fetch: 获取完成后是否自动关闭查询，默认False
            
        Returns:
            查询结果列表，每个元素是一行数据的字典
            
        Raises:
            ConnectionError: 网络连接异常
            DataPlatformError: API返回错误
        """
        # 先获取状态，拿到nextQueryId（实际用于获取结果的ID）
        status_data = self.get_status(query_id)
        next_query_id = status_data.get("nextQueryId", query_id)
        
        url = f"{self.base_url}/olap/api/v2/statement/fetchResult"
        headers = self._get_headers()
        
        all_results = []
        offset = 0
        
        while True:
            # 注意：queryId 必须作为 URL 参数传递，不能放在 JSON body 中
            params = {
                "queryId": next_query_id,
                "maxRows": max_rows,
                "offset": offset
            }
            
            try:
                resp = self.session.post(
                    url,
                    params=params,  # queryId 作为 URL 参数
                    headers=headers,
                    timeout=60
                )
                resp.raise_for_status()
                data = resp.json()

                # 实际响应格式：{"meta": {"errCode": 0}, "data": {...}}
                meta = data.get("meta", {})
                if meta.get("errCode") != 0:
                    error_code = str(meta.get("errCode", "UNKNOWN"))
                    error_msg = meta.get("errMsg", "未知错误")
                    self._handle_error(error_code, error_msg)
                
                result_data = data.get("data", {})
                rows = result_data.get("rows", [])
                has_more = result_data.get("hasMore", False)
                
                # 将行数据转换为字典列表
                columns = result_data.get("columns", [])
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        row_dict[col.get("name", f"col_{i}")] = row[i] if i < len(row) else None
                    all_results.append(row_dict)
                
                if not has_more:
                    break
                    
                offset += len(rows)
                
            except requests.exceptions.RequestException as e:
                raise ConnectionError("CONNECTION", f"网络连接异常: {str(e)}")
        
        if close_after_fetch:
            self.close_query(query_id)
            
        return all_results
    
    def fetch_stream_result(self, query_id: str) -> List[Dict[str, Any]]:
        """
        一次性获取全部查询结果（流式接口）
        
        Args:
            query_id: 查询ID
            
        Returns:
            查询结果列表
            
        Raises:
            ConnectionError: 网络连接异常
            DataPlatformError: API返回错误
        """
        # 先获取状态，拿到nextQueryId
        status_data = self.get_status(query_id)
        next_query_id = status_data.get("nextQueryId", query_id)
        
        url = f"{self.base_url}/olap/api/v2/statement/fetchStreamResult"
        payload = {"queryId": next_query_id}
        
        try:
            resp = self.session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=120
            )
            resp.raise_for_status()
            data = resp.json()

            # 实际响应格式：{"meta": {"errCode": 0}, "data": {...}}
            meta = data.get("meta", {})
            if meta.get("errCode") == 0:
                result_data = data.get("data", {})
                rows = result_data.get("rows", [])
                columns = result_data.get("columns", [])
                
                # 转换为字典列表
                results = []
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        row_dict[col.get("name", f"col_{i}")] = row[i] if i < len(row) else None
                    results.append(row_dict)
                return results
            else:
                error_code = str(meta.get("errCode", "UNKNOWN"))
                error_msg = meta.get("errMsg", "未知错误")
                self._handle_error(error_code, error_msg)
                
        except requests.exceptions.RequestException as e:
            raise ConnectionError("CONNECTION", f"网络连接异常: {str(e)}")
    
    def close_query(self, query_id: str):
        """
        关闭查询，释放资源
        
        Args:
            query_id: 查询ID
            
        Raises:
            ConnectionError: 网络连接异常（非致命，仅记录日志）
        """
        url = f"{self.base_url}/olap/api/v2/statement/close"
        payload = {"queryId": query_id}
        
        try:
            resp = self.session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=10
            )
            resp.raise_for_status()
            # 检查响应是否有错误
            data = resp.json()
            meta = data.get("meta", {})
            if meta.get("errCode") != 0:
                print(f"警告：关闭查询返回错误（query_id={query_id}）：{meta.get('errMsg', '未知错误')}")
        except requests.exceptions.RequestException as e:
            # 关闭失败不抛出异常，只打印警告
            print(f"警告：关闭查询失败（query_id={query_id}）：{str(e)}")
    
    def describe_table(self, table_name: str) -> List[Dict[str, Any]]:
        """
        获取表结构（字段名、类型、注释等）
        
        使用 DESCRIBE table_name 获取字段信息
        
        Args:
            table_name: 完整表名（如 catalog.schema.table 或 database.table）
            
        Returns:
            字段信息列表，每个元素包含：
            - column_name: 字段名
            - data_type: 数据类型
            - comment: 字段注释（如果有）
            
        Raises:
            ConnectionError: 网络连接异常
            DataPlatformError: API返回错误
            
        Usage:
            client = DataPlatformClient(base_url, token, engine="Spark")
            columns = client.describe_table("iceberg_zjyprc_hadoop.meta.dm_table")
            for col in columns:
                print(f"{col['column_name']}: {col['data_type']}")
        """
        # 优先使用 Spark 引擎执行 DESCRIBE（Presto 可能不支持）
        original_engine = self.engine
        self.engine = "Spark"
        
        try:
            # 执行 DESCRIBE table_name（Spark 语法）
            # 注意：不能使用 execute_query，因为它对非 SELECT/WITH 语句不获取结果
            # 必须直接调用底层方法
            sql = f"DESCRIBE {table_name}"
            query_id = self.submit_query(sql)
            
            # 等待查询完成
            status_data = self.wait_for_completion(query_id, timeout=60)
            
            if status_data.get("state") in ("COMPLETED", "FINISHED"):
                # 获取查询结果
                results = self.fetch_results(query_id, max_rows=1000)
                
                columns = []
                for row in results:
                    col_name = row.get("col_name", row.get("column_name", ""))
                    data_type = row.get("data_type", row.get("type", ""))
                    comment = row.get("comment", row.get("col_comment", ""))
                    
                    # 跳过空行和分区信息行
                    if col_name and not col_name.startswith("#"):
                        columns.append({
                            "column_name": col_name,
                            "data_type": data_type,
                            "comment": comment,
                        })
                
                # 关闭查询
                try:
                    self.close_query(query_id)
                except Exception:
                    pass
                
                if columns:
                    print(f"[DEBUG] describe_table: 获取到 {len(columns)} 个字段")
                    return columns
            
            return []
            
        except Exception as e:
            print(f"[WARN] describe_table 失败: {e}")
            return []
        finally:
            # 恢复原始引擎配置
            self.engine = original_engine
    
    def execute_query(
        self,
        sql: str,
        timeout: Optional[int] = None,
        fetch_results: bool = True,
        max_rows: int = 1000
    ) -> Dict[str, Any]:
        """
        一站式执行SQL查询
        
        Args:
            sql: 要执行的SQL语句
            timeout: 超时时间（秒），默认使用初始化时的timeout
            fetch_results: 是否获取查询结果，默认True
            max_rows: 单次获取的最大行数，默认1000
            
        Returns:
            包含以下字段的字典：
            - success: 是否执行成功
            - query_id: 查询ID
            - status: 最终状态
            - results: 查询结果（如果fetch_results=True）
            - error: 错误信息（如果执行失败）
            
        Usage:
            client = DataPlatformClient(...)
            
            # 只执行不获取结果（用于DDL/DML）
            result = client.execute_query("CREATE TABLE ...", fetch_results=False)
            
            # 执行并获取结果（用于SELECT）
            result = client.execute_query("SELECT * FROM table LIMIT 10")
            if result["success"]:
                for row in result["results"]:
                    print(row)
        """
        result = {
            "success": False,
            "query_id": None,
            "status": None,
            "results": None,
            "error": None
        }
        
        try:
            # 1. 提交查询
            query_id = self.submit_query(sql)
            result["query_id"] = query_id
            
            # 2. 等待完成
            status_data = self.wait_for_completion(query_id, timeout)
            result["status"] = status_data.get("state")
            result["success"] = True
            
            # 3. 获取结果（如果需要）
            if fetch_results:
                # 判断是否是SELECT查询（简单判断）
                if sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("WITH"):
                    result["results"] = self.fetch_results(query_id, max_rows)
                else:
                    # 非SELECT查询不获取结果
                    result["results"] = []
            
            # 4. 关闭查询
            self.close_query(query_id)
            
        except SQLExecutionError as e:
            result["error"] = {
                "code": e.code,
                "message": e.message
            }
        except TimeoutError as e:
            result["error"] = {
                "code": "TIMEOUT",
                "message": str(e)
            }
        except (AuthenticationError, ConnectionError, DataPlatformError) as e:
            result["error"] = {
                "code": e.code if hasattr(e, 'code') else "ERROR",
                "message": str(e)
            }
        
        return result


def test_connection(base_url: str, token: str) -> bool:
    """
    测试数据平台连接
    
    Args:
        base_url: 数据平台API基础地址
        token: 认证token
        
    Returns:
        bool: 连接是否成功
    """
    try:
        client = DataPlatformClient(base_url, token)
        # 执行简单查询测试连接
        result = client.execute_query("SELECT 1", timeout=30, fetch_results=True)
        return result["success"]
    except Exception as e:
        print(f"连接测试失败：{str(e)}")
        return False


if __name__ == "__main__":
    # 简单测试（需要替换为实际的base_url和token）
    import sys
    
    if len(sys.argv) < 3:
        print("用法：python data_platform_api.py <base_url> <token> [sql]")
        print("示例：python data_platform_api.py https://proxy-service-http-cnbj1-dp.api.xiaomi.net your_token \"SELECT 1\"")
        sys.exit(1)
    
    base_url = sys.argv[1]
    token = sys.argv[2]
    sql = sys.argv[3] if len(sys.argv) > 3 else "SELECT 1"
    
    client = DataPlatformClient(base_url, token)
    
    print(f"执行SQL：{sql}")
    result = client.execute_query(sql, fetch_results=True)
    
    if result["success"]:
        print("✅ 执行成功")
        print(f"查询结果：{result['results']}")
    else:
        print("❌ 执行失败")
        print(f"错误：{result['error']}")
