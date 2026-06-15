"""Test embedding API"""
import httpx

api_key = "sk-vnvBVyYf2aHG092nCH52ANOOGlp75taZxSL6xD6wENAP0h7o"
base_url = "https://uniapi.ruijie.com.cn/v1"

resp = httpx.post(
    f"{base_url}/embeddings",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={"model": "text-embedding-3-small", "input": ["阿里巴巴", "腾讯", "字节跳动"], "encoding_format": "float"},
    timeout=30
)

if resp.status_code == 200:
    data = resp.json()
    for item in data["data"]:
        print(f"idx={item['index']}: dim={len(item['embedding'])}, values={item['embedding'][:3]}...")
    print("API OK!")
else:
    print(f"Error {resp.status_code}: {resp.text[:200]}")