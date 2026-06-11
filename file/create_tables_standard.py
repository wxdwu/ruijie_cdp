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

# ===================== 表1: CRM业务机会数据 =====================
OPP_FIELDS = [
    ('客户名', 'customer_name', 'varchar(255)', '客户名称'),
    ('业务机会名称', 'opp_name', 'varchar(500)', '业务机会名称'),
    ('业务机会编码_new', 'opp_code', 'varchar(64)', '业务机会编码'),
    ('创建日期', 'create_date', 'date', '创建日期'),
    ('是否进入漏斗', 'is_funnel', 'varchar(16)', '是否进入漏斗'),
    ('预测类别(*)', 'forecast_type', 'varchar(32)', '预测类别'),
    ('金额(万)', 'amount_10k', 'decimal(20,4)', '金额(万元)'),
    ('预计开标日期', 'expect_bid_date', 'date', '预计开标日期'),
    ('预计下单日期', 'expect_order_date', 'date', '预计下单日期'),
    ('赢率', 'win_rate', 'decimal(5,2)', '赢率(%)'),
    ('业务机会实际下单金额（元）(万)', 'actual_order_amount_10k', 'decimal(20,4)', '实际下单金额(万元)'),
    ('取消/丢单', 'is_cancel_lost', 'varchar(16)', '是否取消/丢单'),
    ('丢单/取消原因说明（新）', 'cancel_reason', 'text', '丢单/取消原因'),
    ('行业归属-新', 'industry', 'varchar(64)', '行业归属'),
    ('业务机会所有人名称', 'owner_name', 'varchar(64)', '业务机会所有人'),
    ('大区', 'region', 'varchar(64)', '大区'),
    ('区域', 'area', 'varchar(64)', '区域'),
    ('丢单/取消日期', 'cancel_date', 'date', '丢单/取消日期'),
    ('客户进入阶段', 'customer_stage', 'varchar(64)', '客户进入阶段'),
    ('产品类别', 'product_category', 'varchar(128)', '产品类别'),
    ('是否彩光项目', 'is_colorlight_project', 'tinyint', '是否彩光项目'),
    ('是否无线项目', 'is_wireless_project', 'tinyint', '是否无线项目'),
    ('是否EDN项目', 'is_edn_project', 'tinyint', '是否EDN项目'),
    ('是否云桌面项目', 'is_cloud_desktop_project', 'tinyint', '是否云桌面项目'),
    ('业务类型', 'business_type', 'varchar(64)', '业务类型'),
    ('商机来源', 'opp_source', 'varchar(128)', '商机来源'),
    ('市场活动', 'marketing_activity', 'varchar(255)', '市场活动'),
    ('数据来源', 'data_source', 'varchar(64)', '数据来源'),
    ('项目报备服务商名称', 'report_provider_name', 'varchar(255)', '项目报备服务商名称'),
    ('最新活动记录时间-转化', 'last_activity_time', 'datetime', '最新活动记录时间'),
    ('赢率.1', 'win_rate_1', 'decimal(5,2)', '赢率2(%)'),
    ('是否活动中', 'is_active', 'tinyint', '是否活动中'),
    ('订单创建日期', 'order_create_date', 'date', '订单创建日期'),
    ('订单-产品线名称', 'order_product_line', 'varchar(128)', '订单产品线名称'),
    ('订单金额(万)', 'order_amount_10k', 'decimal(20,4)', '订单金额(万元)'),
]

# ===================== 表2: CRM联系人明细 =====================
CRM_CONTACT_FIELDS = [
    ('联系人', 'contact_name', 'varchar(64)', '联系人姓名'),
    ('客户名称', 'customer_name', 'varchar(255)', '客户名称'),
    ('系统手机', 'mobile', 'varchar(32)', '手机号'),
    ('电子邮件', 'email', 'varchar(128)', '电子邮件'),
    ('部门', 'department', 'varchar(128)', '部门'),
    ('职务', 'position', 'varchar(128)', '职务'),
    ('采购角色', 'purchase_role', 'varchar(64)', '采购角色'),
    ('行业归属1', 'industry', 'varchar(64)', '行业归属'),
    ('细分市场', 'market_segment', 'varchar(128)', '细分市场'),
    ('锐捷区域1', 'ruijie_region', 'varchar(128)', '锐捷区域'),
    ('属性', 'attribute', 'varchar(32)', '属性'),
    ('销售姓名', 'sales_name', 'varchar(64)', '销售姓名'),
    ('最新拜访时间', 'last_visit_time', 'datetime', '最新拜访时间'),
    ('未拜访天数', 'not_visit_days', 'int', '未拜访天数'),
    ('必跟客户-汇总', 'must_follow_tags', 'varchar(1000)', '必跟客户标签汇总'),
]

# ===================== 表3: 致趣联系人明细 =====================
ZHIQUE_CONTACT_FIELDS = [
    ('关联公司', 'related_company', 'varchar(255)', '关联公司名称'),
    ('行业-汇总', 'industry', 'varchar(64)', '行业'),
    ('锐捷区域', 'ruijie_region', 'varchar(64)', '锐捷区域'),
    ('属性', 'attribute', 'varchar(32)', '属性'),
    ('新老客户', 'is_new_customer', 'varchar(32)', '新老客户标识'),
    ('姓名', 'contact_name', 'varchar(64)', '联系人姓名'),
    ('手机号', 'mobile', 'varchar(32)', '手机号'),
    ('邮箱', 'email', 'varchar(128)', '邮箱'),
    ('部门', 'department', 'varchar(128)', '部门'),
    ('职务', 'position', 'varchar(128)', '职务'),
    ('线上可触达方式', 'online_reach_method', 'varchar(64)', '线上可触达方式'),
    ('必跟客户-汇总', 'must_follow_tags', 'varchar(1000)', '必跟客户标签汇总'),
]

# ===================== 表4: 营销线索明细 =====================
LEAD_FIELDS = [
    ('线索编号', 'lead_code', 'varchar(64)', '线索编号'),
    ('线索获得日期', 'lead_obtain_date', 'date', '线索获得日期'),
    ('线索来源类型', 'lead_source_type', 'varchar(64)', '线索来源类型'),
    ('线索来源细分', 'lead_source_detail', 'varchar(128)', '线索来源细分'),
    ('线索三级来源', 'lead_source_level3', 'varchar(128)', '线索三级来源'),
    ('有效线索反馈结果', 'valid_lead_feedback', 'varchar(64)', '有效线索反馈结果'),
    ('业务机会转化', 'opp_conversion', 'varchar(64)', '业务机会转化状态'),
    ('CRM编号', 'crm_code', 'varchar(64)', 'CRM编号'),
    ('是否进入漏斗(只用于报表展示)', 'is_funnel_report', 'varchar(16)', '是否进入漏斗(报表)'),
    ('预测类别(*)', 'forecast_type', 'varchar(32)', '预测类别'),
    ('业务机会预估金额(万)', 'expect_opp_amount_10k', 'decimal(20,4)', '业务机会预估金额(万元)'),
    ('实际下单金额(万)', 'actual_order_amount_10k', 'decimal(20,4)', '实际下单金额(万元)'),
    ('取消/丢单', 'is_cancel_lost', 'varchar(16)', '是否取消/丢单'),
    ('丢单/取消原因说明（新）', 'cancel_reason', 'text', '丢单/取消原因'),
    ('业务机会客户名', 'opp_customer_name', 'varchar(255)', '业务机会客户名'),
    ('业务机会所有人名称', 'opp_owner_name', 'varchar(64)', '业务机会所有人'),
    ('CRM编号重复标识', 'crm_dup_flag', 'varchar(32)', 'CRM编号重复标识'),
    ('无效原因', 'invalid_reason', 'varchar(255)', '无效原因'),
    ('线索关闭原因', 'lead_close_reason', 'varchar(255)', '线索关闭原因'),
    ('线索作用', 'lead_function', 'varchar(64)', '线索作用'),
    ('省份', 'province', 'varchar(32)', '省份'),
    ('线索当前负责人', 'current_owner_name', 'varchar(64)', '线索当前负责人'),
    ('行业', 'industry', 'varchar(64)', '行业'),
    ('产品线', 'product_line', 'varchar(128)', '产品线'),
    ('重客', 'is_key_customer', 'varchar(16)', '是否重点客户'),
    ('客户单位', 'customer_company', 'varchar(255)', '客户单位'),
    ('客户姓名', 'customer_name', 'varchar(64)', '客户姓名'),
    ('联系电话', 'contact_phone', 'varchar(32)', '联系电话'),
    ('邮箱', 'email', 'varchar(128)', '邮箱'),
    ('最终公司名称', 'final_company_name', 'varchar(255)', '最终公司名称'),
    ('内销负责人', 'domestic_sales_owner', 'varchar(64)', '内销负责人'),
    ('内销反馈时长', 'domestic_feedback_hours', 'int', '内销反馈时长(小时)'),
    ('最新修改日期', 'last_modify_date', 'date', '最新修改日期'),
    ('线索录入人', 'lead_creator', 'varchar(64)', '线索录入人'),
    ('备注', 'remark', 'text', '备注'),
    ('未来窗来源类型', 'future_window_source_type', 'varchar(64)', '未来窗来源类型'),
    ('活动申请编号', 'activity_apply_code', 'varchar(64)', '活动申请编号'),
    ('是否彩光项目', 'is_colorlight_project', 'tinyint', '是否彩光项目'),
    ('是否无线项目', 'is_wireless_project', 'tinyint', '是否无线项目'),
    ('是否EDN项目', 'is_edn_project', 'tinyint', '是否EDN项目'),
    ('是否云桌面项目', 'is_cloud_desktop_project', 'tinyint', '是否云桌面项目'),
]

TABLES_CONFIG = [
    ('CRM业务机会数据明细6.5.xlsx', 'ods_crm_opportunity_day', 'CRM业务机会数据日表', OPP_FIELDS),
    ('企业彩光ICP客户-CRM联系人明细5.25.xlsx', 'ods_crm_contact_day', '企业彩光ICP客户-CRM联系人明细日表', CRM_CONTACT_FIELDS),
    ('企业彩光ICP客户-致趣联系人明细5.25.xlsx', 'ods_zhique_contact_day', '企业彩光ICP客户-致趣联系人明细日表', ZHIQUE_CONTACT_FIELDS),
    ('营销线索明细表6.5.xlsx', 'ods_marketing_lead_day', '营销线索明细日表', LEAD_FIELDS),
]

engine = create_engine(
    f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}?charset=utf8mb4",
    pool_pre_ping=True
)

def clean_string(val):
    """Clean string values"""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s if s else None

def clean_phone(val):
    """Clean phone number"""
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, (float, int)):
        return str(int(val))
    s = str(val).strip()
    s = re.sub(r'\s+', '', s)
    return s if s else None

def clean_date(val):
    """Clean date field"""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    if s in ['nan', 'NaN', '']:
        return None
    return s

def clean_int(val):
    """Clean int field"""
    if pd.isna(val) or val is None:
        return None
    try:
        return int(val)
    except:
        return None

def clean_decimal(val):
    """Clean decimal field"""
    if pd.isna(val) or val is None:
        return None
    try:
        return float(val)
    except:
        return None

def clean_tinyint(val):
    """Clean tinyint field"""
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

for filepath, table_name, table_comment, fields in TABLES_CONFIG:
    print(f"\n{'='*80}")
    print(f"Processing: {filepath} -> {table_name}")
    print(f"{'='*80}")

    # Read Excel
    print("  Reading Excel...")
    df = pd.read_excel(filepath)
    df.columns = [c.strip() for c in df.columns]
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")

    # Build field mapping
    cn_to_en = {f[0]: f[1] for f in fields}
    field_types = {f[1]: f[2] for f in fields}

    # Create new dataframe with English column names
    new_df = pd.DataFrame()
    for cn_name, en_name, dtype, comment in fields:
        if cn_name in df.columns:
            col_data = df[cn_name].copy()

            # Apply type conversion
            if 'tinyint' in dtype:
                col_data = col_data.apply(clean_tinyint)
            elif 'int' in dtype and 'tinyint' not in dtype:
                col_data = col_data.apply(clean_int)
            elif 'decimal' in dtype or 'double' in dtype or 'float' in dtype:
                col_data = col_data.apply(clean_decimal)
            elif 'date' in dtype or 'datetime' in dtype:
                col_data = col_data.apply(clean_date)
            elif en_name in ['mobile', 'contact_phone']:
                col_data = col_data.apply(clean_phone)
            else:
                col_data = col_data.apply(clean_string)

            new_df[en_name] = col_data
        else:
            print(f"    WARNING: Column '{cn_name}' not found in Excel!")
            new_df[en_name] = None

    # Drop existing table
    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
        conn.commit()
        print("  Old table dropped.")
    finally:
        cursor.close()
        conn.close()

    # Build CREATE TABLE SQL
    col_defs = []
    for cn_name, en_name, dtype, comment in fields:
        col_defs.append(f"  `{en_name}` {dtype} DEFAULT NULL COMMENT '{comment}'")

    create_sql = f"""CREATE TABLE `{table_name}` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
{',\n'.join(col_defs)},
  `etl_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT 'ETL加载时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='{table_comment}';"""

    # Create table
    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(create_sql)
        conn.commit()
        print("  Table created with proper schema.")
    finally:
        cursor.close()
        conn.close()

    # Import data
    print("  Importing data...")
    batch_size = 1000
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
            chunksize=200,
            method='multi'
        )

        if (batch_idx + 1) % 5 == 0 or batch_idx == total_batches - 1:
            print(f"    Batch {batch_idx + 1}/{total_batches} ({end_idx}/{total_rows} rows)")

    print(f"  Done! {total_rows} rows imported into `{table_name}`")

engine.dispose()
print("\n=== ALL 4 TABLES IMPORTED SUCCESSFULLY! ===")
print("\n现在数据库中有以下新表：")
for _, table_name, table_comment, _ in TABLES_CONFIG:
    print(f"  - {table_name}: {table_comment}")
