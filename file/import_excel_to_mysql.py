import pandas as pd
import pymysql
from sqlalchemy import create_engine, text
import numpy as np
import re

DB_CONFIG = {
    'host': '192.168.159.22',
    'port': 33307,
    'user': 'app_cdp',
    'password': '123456',
    'database': 'app_cdp',
    'charset': 'utf8mb4'
}

TABLE_MAP = [
    {
        'file': 'CRM业务机会数据明细6.5.xlsx',
        'table': 'ods_crm_opportunity_day',
        'comment': 'CRM业务机会数据日表'
    },
    {
        'file': '企业彩光ICP客户-CRM联系人明细5.25.xlsx',
        'table': 'ods_crm_contact_day',
        'comment': '企业彩光ICP客户-CRM联系人明细日表'
    },
    {
        'file': '企业彩光ICP客户-致趣联系人明细5.25.xlsx',
        'table': 'ods_zhique_contact_day',
        'comment': '企业彩光ICP客户-致趣联系人明细日表'
    },
    {
        'file': '营销线索明细表6.5.xlsx',
        'table': 'ods_marketing_lead_day',
        'comment': '营销线索明细日表'
    },
]

def clean_phone(val):
    """Clean phone number: strip spaces, keep digits only"""
    if pd.isna(val):
        return None
    # If it's a float like 13233412980.0
    if isinstance(val, (float, int, np.integer, np.floating)):
        return str(int(val))
    # If it's a string with spaces
    s = str(val).strip()
    s = re.sub(r'\s+', '', s)
    return s if s else None

engine = create_engine(
    f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}?charset=utf8mb4",
    pool_pre_ping=True
)

for item in TABLE_MAP:
    filepath = item['file']
    table_name = item['table']
    table_comment = item['comment']

    print(f"\n{'='*80}")
    print(f"Processing: {filepath} -> {table_name}")
    print(f"{'='*80}")

    # Read Excel
    print("  Reading Excel...")
    df = pd.read_excel(filepath)
    df.columns = [c.strip() for c in df.columns]
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")

    # Clean phone-like columns
    phone_like_cols = ['系统手机', '手机号', '联系电话']
    for col in df.columns:
        if col in phone_like_cols:
            df[col] = df[col].apply(clean_phone)

    # Clean ID-like columns (large ints stored as float)
    id_like_cols = ['业务机会编码_new', '线索编号', 'CRM编号']
    for col in df.columns:
        if col in id_like_cols:
            df[col] = df[col].apply(lambda x: str(int(x)) if pd.notna(x) and isinstance(x, (float, int, np.integer, np.floating)) else (str(x).strip() if pd.notna(x) else None))

    # Drop table
    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
        conn.commit()
        print("  Table dropped.")
    finally:
        cursor.close()
        conn.close()

    # Import data via pandas to_sql in batches
    print("  Importing data...")
    batch_size = 1000
    total_rows = len(df)
    total_batches = (total_rows + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, total_rows)
        batch_df = df.iloc[start_idx:end_idx]

        if_exists = 'replace' if batch_idx == 0 else 'append'

        batch_df.to_sql(
            name=table_name,
            con=engine,
            if_exists=if_exists,
            index=False,
            chunksize=500,
            method='multi'
        )

        if (batch_idx + 1) % 5 == 0 or batch_idx == total_batches - 1:
            print(f"    Batch {batch_idx + 1}/{total_batches} ({end_idx}/{total_rows} rows)")

    print(f"  Done! {total_rows} rows imported into `{table_name}`")

# Add table comments
print("\n=== Adding table comments... ===")
conn = engine.raw_connection()
cursor = conn.cursor()
for item in TABLE_MAP:
    table_name = item['table']
    comment = item['comment']
    cursor.execute(f"ALTER TABLE `{table_name}` COMMENT '{comment}';")
    print(f"  Comment added to `{table_name}`")
conn.commit()
cursor.close()
conn.close()

engine.dispose()
print("\n=== All tables created and data imported successfully! ===")
