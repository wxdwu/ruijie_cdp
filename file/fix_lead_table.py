import pandas as pd
import pymysql
from sqlalchemy import create_engine, text
import re

DB_CONFIG = {
    'host': '192.168.159.22',
    'port': 33307,
    'user': 'app_cdp',
    'password': '123456',
    'database': 'app_cdp',
    'charset': 'utf8mb4'
}

LEAD_FIELDS = [
    ('线索编号', 'lead_code', 'varchar(128)', '线索编号'),
    ('线索获得日期', 'lead_obtain_date', 'date', '线索获得日期'),
    ('线索来源类型', 'lead_source_type', 'varchar(128)', '线索来源类型'),
    ('线索来源细分', 'lead_source_detail', 'varchar(255)', '线索来源细分'),
    ('线索三级来源', 'lead_source_level3', 'varchar(255)', '线索三级来源'),
    ('有效线索反馈结果', 'valid_lead_feedback', 'varchar(128)', '有效线索反馈结果'),
    ('业务机会转化', 'opp_conversion', 'varchar(128)', '业务机会转化状态'),
    ('CRM编号', 'crm_code', 'varchar(128)', 'CRM编号'),
    ('是否进入漏斗(只用于报表展示)', 'is_funnel_report', 'varchar(32)', '是否进入漏斗(报表)'),
    ('预测类别(*)', 'forecast_type', 'varchar(64)', '预测类别'),
    ('业务机会预估金额(万)', 'expect_opp_amount_10k', 'decimal(20,4)', '业务机会预估金额(万元)'),
    ('实际下单金额(万)', 'actual_order_amount_10k', 'decimal(20,4)', '实际下单金额(万元)'),
    ('取消/丢单', 'is_cancel_lost', 'varchar(32)', '是否取消/丢单'),
    ('丢单/取消原因说明（新）', 'cancel_reason', 'text', '丢单/取消原因'),
    ('业务机会客户名', 'opp_customer_name', 'varchar(500)', '业务机会客户名'),
    ('业务机会所有人名称', 'opp_owner_name', 'varchar(128)', '业务机会所有人'),
    ('CRM编号重复标识', 'crm_dup_flag', 'varchar(64)', 'CRM编号重复标识'),
    ('无效原因', 'invalid_reason', 'varchar(1000)', '无效原因'),
    ('线索关闭原因', 'lead_close_reason', 'varchar(1000)', '线索关闭原因'),
    ('线索作用', 'lead_function', 'varchar(128)', '线索作用'),
    ('省份', 'province', 'varchar(64)', '省份'),
    ('线索当前负责人', 'current_owner_name', 'varchar(128)', '线索当前负责人'),
    ('行业', 'industry', 'varchar(128)', '行业'),
    ('产品线', 'product_line', 'varchar(255)', '产品线'),
    ('重客', 'is_key_customer', 'varchar(32)', '是否重点客户'),
    ('客户单位', 'customer_company', 'varchar(500)', '客户单位'),
    ('客户姓名', 'customer_name', 'varchar(255)', '客户姓名'),
    ('联系电话', 'contact_phone', 'varchar(64)', '联系电话'),
    ('邮箱', 'email', 'varchar(255)', '邮箱'),
    ('最终公司名称', 'final_company_name', 'varchar(500)', '最终公司名称'),
    ('内销负责人', 'domestic_sales_owner', 'varchar(128)', '内销负责人'),
    ('内销反馈时长', 'domestic_feedback_hours', 'int', '内销反馈时长(小时)'),
    ('最新修改日期', 'last_modify_date', 'date', '最新修改日期'),
    ('线索录入人', 'lead_creator', 'varchar(128)', '线索录入人'),
    ('备注', 'remark', 'text', '备注'),
    ('未来窗来源类型', 'future_window_source_type', 'varchar(128)', '未来窗来源类型'),
    ('活动申请编号', 'activity_apply_code', 'varchar(128)', '活动申请编号'),
    ('是否彩光项目', 'is_colorlight_project', 'tinyint', '是否彩光项目'),
    ('是否无线项目', 'is_wireless_project', 'tinyint', '是否无线项目'),
    ('是否EDN项目', 'is_edn_project', 'tinyint', '是否EDN项目'),
    ('是否云桌面项目', 'is_cloud_desktop_project', 'tinyint', '是否云桌面项目'),
]

engine = create_engine(
    f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}?charset=utf8mb4",
    pool_pre_ping=True
)

table_name = 'ods_marketing_lead_day'
table_comment = '营销线索明细日表'
filepath = '营销线索明细表6.5.xlsx'

def clean_string(val, max_len=255):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s[:max_len] if s else None

def clean_phone(val):
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, (float, int)):
        return str(int(val))[:64]
    s = str(val).strip()
    s = re.sub(r'\s+', '', s)
    return s[:64] if s else None

def clean_date(val):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    if s in ['nan', 'NaN', '']:
        return None
    return s

def clean_int(val):
    if pd.isna(val) or val is None:
        return None
    try:
        return int(val)
    except:
        return None

def clean_decimal(val):
    if pd.isna(val) or val is None:
        return None
    try:
        return float(val)
    except:
        return None

def clean_tinyint(val):
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    if s in ['是', 'Y', 'y', '1']:
        return 1
    elif s in ['否', 'N', 'n', '0']:
        return 0
    try:
        return int(val)
    except:
        return None

print(f"Processing: {filepath} -> {table_name}")
print("  Reading Excel...")
df = pd.read_excel(filepath)
df.columns = [c.strip() for c in df.columns]
print(f"  Rows: {len(df)}")

# Build new_df
new_df = pd.DataFrame()
for cn_name, en_name, dtype, comment in LEAD_FIELDS:
    if cn_name in df.columns:
        col_data = df[cn_name].copy()
        if 'tinyint' in dtype:
            col_data = col_data.apply(clean_tinyint)
        elif 'int' in dtype and 'tinyint' not in dtype:
            col_data = col_data.apply(clean_int)
        elif 'decimal' in dtype:
            col_data = col_data.apply(clean_decimal)
        elif 'date' in dtype:
            col_data = col_data.apply(clean_date)
        elif en_name in ['contact_phone']:
            col_data = col_data.apply(clean_phone)
        elif en_name in ['remark', 'cancel_reason']:
            col_data = col_data.apply(lambda x: clean_string(x, 65535))
        elif en_name in ['customer_company', 'final_company_name', 'opp_customer_name']:
            col_data = col_data.apply(lambda x: clean_string(x, 500))
        else:
            col_data = col_data.apply(lambda x: clean_string(x, 255))
        new_df[en_name] = col_data
    else:
        print(f"    WARNING: Column '{cn_name}' not found!")
        new_df[en_name] = None

# Drop old table
conn = engine.raw_connection()
cursor = conn.cursor()
cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
conn.commit()
cursor.close()
conn.close()
print("  Old table dropped.")

# Create table
col_defs = []
for cn_name, en_name, dtype, comment in LEAD_FIELDS:
    col_defs.append(f"  `{en_name}` {dtype} DEFAULT NULL COMMENT '{comment}'")

create_sql = f"""CREATE TABLE `{table_name}` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
{',\n'.join(col_defs)},
  `etl_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT 'ETL加载时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='{table_comment}';"""

conn = engine.raw_connection()
cursor = conn.cursor()
cursor.execute(create_sql)
conn.commit()
cursor.close()
conn.close()
print("  Table created.")

# Import
print("  Importing data...")
batch_size = 500
total_rows = len(new_df)
total_batches = (total_rows + batch_size - 1) // batch_size

for batch_idx in range(total_batches):
    start_idx = batch_idx * batch_size
    end_idx = min(start_idx + batch_size, total_rows)
    batch_df = new_df.iloc[start_idx:end_idx]

    batch_df.to_sql(
        name=table_name,
        con=engine,
        if_exists='append',
        index=False,
        chunksize=100,
        method='multi'
    )

    if (batch_idx + 1) % 5 == 0 or batch_idx == total_batches - 1:
        print(f"    Batch {batch_idx + 1}/{total_batches} ({end_idx}/{total_rows})")

print(f"  Done! {total_rows} rows imported.")
engine.dispose()
print("\n=== ALL 4 TABLES IMPORTED SUCCESSFULLY! ===")
