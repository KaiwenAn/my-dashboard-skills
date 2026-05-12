# -*- coding: utf-8 -*-
"""临时脚本：获取表结构"""
import sys
sys.path.insert(0, r'C:\Users\Kai\WorkBuddy\20260427134240')
from data_platform_api import DataPlatformClient

client = DataPlatformClient(
    base_url='https://proxy-service-http-cnbj1-dp.api.xiaomi.net',
    token='62f6e3737750485ba1b7fdb0e6a65b15',
    engine='Spark'
)

# 用 SELECT * LIMIT 1 来获取字段信息
sql = "SELECT * FROM iceberg_zjyprc_hadoop.meta.dwd_user_module_page_view LIMIT 1"
result = client.execute_query(sql, fetch_results=True, timeout=120)

print("=" * 100)
print(f"查询: {sql}")
print("=" * 100)

if result.get("success"):
    results = result.get("results", [])
    print(f"{'序号':<5} {'字段名':<30} {'值示例'}")
    print("-" * 100)
    for i, row_dict in enumerate(results[:1]):  # 只显示第一行
        for col_name, value in row_dict.items():
            print(f"{i+1:<5} {col_name:<30} {str(value)[:50]}")
    print(f"\n列数: {len(results[0]) if results else 0}")
else:
    print(f"查询失败: {result.get('error', 'Unknown error')}")
    print(f"错误详情: {result}")
