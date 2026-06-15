"""
Run full company name dedup and insert into review queue.
"""
from sqlalchemy import create_engine, text
from app.config import settings
import json, numpy as np, httpx

eng = create_engine('mysql+pymysql://app_cdp:123456@192.168.159.22:33307/app_cdp?charset=utf8mb4')

with eng.connect() as conn:
    rows = conn.execute(text('SELECT customer_name FROM tmp_icp_customers')).fetchall()
names = [r[0] for r in rows]
print(f'ICP customers: {len(names)}')

# Embeddings
api_key, base_url = settings.LLM_API_KEY, settings.LLM_BASE_URL
vecs = []
for i in range(0, len(names), 100):
    batch = names[i:i+100]
    resp = httpx.post(f'{base_url}/embeddings',
        headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'},
        json={'model':'text-embedding-3-small','input':batch,'encoding_format':'float'},timeout=30)
    for item in resp.json()['data']:
        vecs.append(np.array(item['embedding'], dtype=np.float32))
    print(f'  embed batch {i//100+1}/{(len(names)-1)//100+1}')

# Cosine similarity
mat = np.array(vecs)
mat = mat / np.linalg.norm(mat, axis=1, keepdims=True)
sims = mat @ mat.T

# Find pairs
seen = set()
pairs = []
for i in range(len(names)):
    idxs = np.argsort(sims[i])[::-1][1:6]
    for j in idxs:
        if (j,i) in seen or sims[i][j] <= 0.85:
            continue
        seen.add((i,j))
        pairs.append((i, j, float(sims[i][j])))
print(f'Candidate pairs: {len(pairs)}')

# Scoring
def normalize(n):
    import re
    n = n.strip().lower()
    for suf in ['有限公司','股份有限公司','有限责任公司','集团','控股','科技','技术','实业']:
        n = n.replace(suf, '')
    n = re.sub(r'[（()）\s]', '', n)
    return n

def lev(s, t):
    if len(s) < len(t): s, t = t, s
    if not t: return len(s)
    prev = list(range(len(t)+1))
    for i, c1 in enumerate(s):
        curr = [i+1]
        for j, c2 in enumerate(t):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def rule_score(a, b):
    na, nb = normalize(a), normalize(b)
    if na == nb: return 1.0
    if na in nb or nb in na: return 0.9
    d = lev(na, nb)
    return max(0, 1 - d / max(len(na), len(nb), 1))

with eng.connect() as conn:
    conn.execute(text('TRUNCATE TABLE dws_review_queue'))
    inserted = 0
    for i, j, sim in pairs:
        a, b = names[i], names[j]
        rs = rule_score(a, b)

        # Evidence: shared mobiles
        ma = set(r[0] for r in conn.execute(text(
            'SELECT mobile FROM dws_contact_mapping WHERE customer_name=:n AND mobile IS NOT NULL'), {'n': a}).fetchall())
        mb = set(r[0] for r in conn.execute(text(
            'SELECT mobile FROM dws_contact_mapping WHERE customer_name=:n AND mobile IS NOT NULL'), {'n': b}).fetchall())
        shared = len(ma & mb)
        es = min(1.0, shared * 0.3)

        # LLM proxy fallback
        llm = rs * 0.5 + es * 0.5
        final = rs * 0.3 + es * 0.3 + llm * 0.4

        if final > 0.85:
            status = 'auto_merged'
        elif final > 0.6:
            status = 'pending'
        else:
            continue

        ev = json.dumps({'rule_score': round(rs, 2), 'evidence_score': round(es, 2),
                         'llm_score': round(llm, 2), 'embedding_sim': round(sim, 4),
                         'shared_mobiles': shared})

        conn.execute(text(
            'INSERT INTO dws_review_queue (review_type,candidate_a,candidate_b,match_score,evidence,status)'
            ' VALUES (:t,:a,:b,:s,:e,:st)'
        ), {'t': 'company_merge', 'a': a, 'b': b, 's': round(final, 2), 'e': ev, 'st': status})
        inserted += 1

    conn.commit()
    print(f'\nInserted: {inserted} review items')

    stats = conn.execute(text('SELECT status,COUNT(*) FROM dws_review_queue GROUP BY status')).fetchall()
    for s, c in stats:
        print(f'  {s}: {c}')