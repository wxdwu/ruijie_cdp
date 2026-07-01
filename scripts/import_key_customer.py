"""
重要客户数据导入脚本
功能：读取 Excel 文件并将数据导入到数据库
依赖：pandas, sqlalchemy, openpyxl
"""

import pandas as pd
import sqlalchemy
from sqlalchemy import create_engine
import os

# ============================================================
# 配置部分
# ============================================================

# Excel 文件路径
EXCEL_FILE_PATH = r"E:\DevTools\ruijie_workspace\ruijie-cdp\data\重要客户.xlsx"

# 数据库配置（请根据实际情况修改）
DB_CONFIG = {
    'db_type': 'mysql',      # 数据库类型：postgresql, mysql, sqlite 等
    'host': '192.168.159.22',
    'port': '33307',
    'database': 'app_cdp',
    'username': 'app_cdp',
    'password': '123456'
}


# 目标表名
TABLE_NAME = 'ods_key_customer'

# ============================================================
# 字段映射：Excel 列名 -> 数据库字段名
# ============================================================

COLUMN_MAPPING = {
    '分类': 'category',
    '重客名称': 'key_customer_name',
    '重客编码': 'key_customer_code',
    '名称': 'customer_name',
    '工号': 'employee_id',
    '重客新老客户': 'customer_type_old_new',
    '25年重客新老客户': 'customer_type_25_old_new',
    '客户行业整理': 'industry_category',
    '客户名': 'associated_customer_name',
    '重客关联客户编码-整理': 'associated_customer_code',
    '三级部门名称': 'department_level3',
    '三级部门名称1': 'department_level3_alt',
    '售前重客专家': 'pre_sales_expert',
    '属性': 'attribute',
    '重客': 'is_key_customer',
    '重客销量统计分类': 'sales_volume_category',
    '是否有效': 'is_valid',
    '2026-净销售额万': 'net_sales_2026',
    '2025-25年同期净销售额': 'net_sales_2025_same_period',
    '2025-净销售额万': 'net_sales_2025',
    '2024-净销售额万': 'net_sales_2024',
    '2023-净销售额万': 'net_sales_2023',
    '2022-净销售额万': 'net_sales_2022',
    '漏斗内金额万': 'funnel_inner_amount',
    '确保金额（万）': 'confirmed_amount',
    '优势金额（万）': 'advantage_amount',
    '可能+金额（万）': 'possible_amount',
    '漏斗外金额万（不含线索）': 'funnel_outer_amount',
    '2025年Q1-净销售额万': 'net_sales_2025_q1',
    '2025年Q2-净销售额万': 'net_sales_2025_q2',
    '2025年Q3-净销售额万': 'net_sales_2025_q3',
    '2025年Q4-净销售额万': 'net_sales_2025_q4',
    '2026年Q1-净销售额万': 'net_sales_2026_q1',
    '2026年Q2-净销售额万': 'net_sales_2026_q2',
    '2026年Q2-漏斗内金额万': 'funnel_inner_2026_q2',
    '2026年Q2-漏斗外金额万（不含线索）': 'funnel_outer_2026_q2',
    '2026年Q3-漏斗内金额万': 'funnel_inner_2026_q3',
    '2026年Q3-漏斗外金额万（不含线索）': 'funnel_outer_2026_q3',
    '2026年Q4-漏斗内金额万': 'funnel_inner_2026_q4',
    '2026年Q4-漏斗外金额万（不含线索）': 'funnel_outer_2026_q4',
    '业务机会数-线索阶段': 'opportunity_count_lead_stage'
}

# ============================================================
# 函数定义
# ============================================================

def create_db_engine():
    """
    创建数据库引擎
    """
    db_type = DB_CONFIG['db_type']
    
    # 根据数据库类型构建连接字符串
    if db_type == 'mysql':
        # MySQL 连接字符串格式 (使用 pymysql 驱动)
        connection_string = (
            f"mysql+pymysql://{DB_CONFIG['username']}:{DB_CONFIG['password']}"
            f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
        )
    elif db_type == 'postgresql':
        # PostgreSQL 连接字符串格式
        connection_string = (
            f"postgresql://{DB_CONFIG['username']}:{DB_CONFIG['password']}"
            f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
        )
    else:
        # 其他数据库类型
        connection_string = (
            f"{db_type}://{DB_CONFIG['username']}:{DB_CONFIG['password']}"
            f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
        )
    
    engine = create_engine(connection_string)
    return engine


def read_excel(file_path):
    """
    读取 Excel 文件
    """
    print(f"正在读取 Excel 文件: {file_path}")
    
    try:
        # 读取 Excel 文件
        df = pd.read_excel(file_path)
        print(f"成功读取 Excel 文件，共 {len(df)} 行数据")
        print(f"\nExcel 列名：")
        for col in df.columns:
            print(f"  - {col}")
        return df
    except Exception as e:
        print(f"读取 Excel 文件失败: {e}")
        return None


def transform_data(df):
    """
    转换数据：重命名列名，处理数据类型
    """
    print("\n开始转换数据...")
    
    # 重命名列名
    df_transformed = df.rename(columns=COLUMN_MAPPING)
    
    # 处理缺失值（可选）
    # df_transformed = df_transformed.fillna(0)  # 数值型填充 0
    # df_transformed = df_transformed.fillna('')  # 字符串型填充空字符串
    
    print(f"数据转换完成")
    print(f"转换后的列名：")
    for col in df_transformed.columns:
        print(f"  - {col}")
    
    return df_transformed


def import_to_database(df, engine):
    """
    将数据导入数据库
    """
    print(f"\n开始导入数据到表: {TABLE_NAME}")
    
    try:
        # 导入数据到数据库
        df.to_sql(
            name=TABLE_NAME,
            con=engine,
            if_exists='append',  # 'append': 追加, 'replace': 替换, 'fail': 失败
            index=False,          # 不导入索引列
            chunksize=1000       # 分批导入，每批 1000 行
        )
        
        print(f"数据导入成功！共导入 {len(df)} 行数据")
        return True
    except Exception as e:
        print(f"数据导入失败: {e}")
        return False


def main():
    """
    主函数
    """
    print("=" * 60)
    print("重要客户数据导入脚本")
    print("=" * 60)
    
    # 1. 检查 Excel 文件是否存在
    if not os.path.exists(EXCEL_FILE_PATH):
        print(f"错误：Excel 文件不存在: {EXCEL_FILE_PATH}")
        return
    
    # 2. 读取 Excel 文件
    df = read_excel(EXCEL_FILE_PATH)
    if df is None:
        return
    
    # 3. 转换数据
    df_transformed = transform_data(df)
    
    # 4. 创建数据库引擎
    print("\n创建数据库连接...")
    engine = create_db_engine()
    
    # 5. 导入数据到数据库
    success = import_to_database(df_transformed, engine)
    
    if success:
        print("\n" + "=" * 60)
        print("数据导入完成！")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("数据导入失败，请检查错误信息")
        print("=" * 60)


if __name__ == "__main__":
    # 使用前请先修改 DB_CONFIG 配置
    print("提示：请先修改脚本中的 DB_CONFIG 数据库配置")
    print("提示：请先运行 create_key_customer_table_mysql.sql 创建表")
    print("")
    
    # 取消下面的注释以运行脚本
    main()
