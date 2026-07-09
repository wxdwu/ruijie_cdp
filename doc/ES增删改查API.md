# ElasticSearch 通用增删改查 API

> 路径前缀：`/api/admin/es`
> 与 ES 同步模块（`es_sync`）同属 ES 模块，统一通过该前缀暴露管理接口。
> `index` 参数可直接传索引别名，例如 `cdp_customer_360`、`cdp_contact_360` 等。

---

## 1. 批量新增（Create）

`POST /api/admin/es/{index}/batch-create`

批量写入文档，**默认每 5000 条发起一次 bulk 写入**，可通过 `batch_size` 修改（范围 1~50000）。

### 请求体

```json
{
  "docs": [
    { "id": "1001", "customer_name": "示例客户", "industry": "企业" },
    { "id": "1002", "customer_name": "另一个客户" }
  ],
  "batch_size": 5000
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `docs` | array | 文档列表，每个文档建议含 `id` 字段，作为 ES 文档 `_id`；缺省则自动生成 uuid |
| `batch_size` | int | 每批写入条数，默认 5000，范围 1~50000 |

### 响应

```json
{ "status": "ok", "index": "cdp_customer_360", "created": 2 }
```

---

## 2. 按 id 查询（Read - 单条）

`GET /api/admin/es/{index}/{doc_id}`

### 响应

```json
{ "index": "cdp_customer_360", "id": "1001", "doc": { "customer_name": "示例客户" } }
```

文档不存在返回 `404`。

---

## 3. 按 DSL 检索（Read - 搜索）

`POST /api/admin/es/{index}/search`

请求体为完整 ES 查询 DSL（可含 `query` / `sort` / `aggs` / `size` / `from` 等）。

### 请求体

```json
{
  "query": {
    "bool": {
      "must": [{ "match": { "customer_name": "客户" } }]
    }
  },
  "size": 20,
  "from": 0
}
```

### 响应

```json
{
  "total": 35,
  "hits": [
    { "id": "1001", "customer_name": "示例客户" }
  ]
}
```

---

## 4. 按 id 局部更新（Update）

`PUT /api/admin/es/{index}/{doc_id}`

请求体为待更新的字段（字段级 merge，不影响未提及字段）。

### 请求体

```json
{ "industry": "金融", "intent_level": "高" }
```

### 响应

```json
{ "status": "ok", "index": "cdp_customer_360", "id": "1001", "updated": true }
```

---

## 5. 批量更新（Update - 批量）

`POST /api/admin/es/{index}/batch-update`

每个更新项**必须含 `id` 字段**（作为 `_id`），其余为待更新字段；写入采用 `doc_as_upsert`。

### 请求体

```json
{
  "docs": [
    { "id": "1001", "industry": "金融" },
    { "id": "1002", "indent_level": "高" }
  ],
  "batch_size": 5000
}
```

### 响应

```json
{ "status": "ok", "index": "cdp_customer_360", "updated": 2 }
```

---

## 6. 按 id 删除（Delete - 单条）

`DELETE /api/admin/es/{index}/{doc_id}`

### 响应

```json
{ "status": "ok", "index": "cdp_customer_360", "id": "1001", "deleted": true }
```

文档不存在时 `deleted` 为 `false`。

---

## 7. 批量删除（Delete - 批量）

`POST /api/admin/es/{index}/batch-delete`

按 id 列表批量删除，`batch_size` 可配。

### 请求体

```json
{
  "ids": ["1001", "1002"],
  "batch_size": 5000
}
```

### 响应

```json
{ "status": "ok", "index": "cdp_customer_360", "deleted": 2 }
```

---

## 8. 按查询删除（Delete - by query）

`POST /api/admin/es/{index}/delete-by-query`

请求体为 ES 查询 DSL，匹配到的文档被删除。

### 请求体

```json
{
  "query": { "term": { "intent_level": "无" } }
}
```

### 响应

```json
{ "status": "ok", "index": "cdp_customer_360", "deleted": 12 }
```

---

## 调用示例（curl）

```bash
# 批量新增
curl -X POST "http://localhost:8000/api/admin/es/cdp_customer_360/batch-create" \
  -H "Content-Type: application/json" \
  -d '{"docs":[{"id":"9001","customer_name":"测试客户"}],"batch_size":5000}'

# 按 id 查询
curl "http://localhost:8000/api/admin/es/cdp_customer_360/9001"

# 检索（客户名含“客户”）
curl -X POST "http://localhost:8000/api/admin/es/cdp_customer_360/search" \
  -H "Content-Type: application/json" \
  -d '{"query":{"match":{"customer_name":"客户"}},"size":10}'

# 局部更新
curl -X PUT "http://localhost:8000/api/admin/es/cdp_customer_360/9001" \
  -H "Content-Type: application/json" \
  -d '{"industry":"金融"}'

# 删除
curl -X DELETE "http://localhost:8000/api/admin/es/cdp_customer_360/9001"
```

---

## 说明

- 所有写接口的 `index` 建议传**别名**（如 `cdp_customer_360`）；别名通过全量同步（`POST /api/admin/es/full`）建立。
- 批量接口（`batch-create` / `batch-update` / `batch-delete`）内部按 `batch_size` 分批 bulk，避免单次请求体过大。
- 服务端对 bulk 失败仅记录日志、不中断（best-effort），响应中的计数为成功条数。
- 全文检索依赖 `ik_max_word` 中文分词器；若该集群未安装 IK 插件，可在 `backend/.env` 将 `ES_ANALYZER` 改为 `standard` 降级。
