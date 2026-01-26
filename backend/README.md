# 后端

## 安装（uv）
```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install -e .
```

## 运行
```bash
uvicorn app.main:app --reload --port 8000
```

## OpenAPI（Swagger）
- Swagger UI：`http://localhost:8000/docs` 或 `http://localhost:8000/api/docs`
- OpenAPI JSON：`http://localhost:8000/api/openapi.json`

导出 OpenAPI schema 到文件：
```bash
python scripts/export_openapi.py --out openapi.json
```

## 环境变量
复制 `.env.example` 到 `.env`，然后设置你的 OpenAI key。

## RAG 存储
向量数据默认持久化到 `.rag_store`。如需修改位置，设置 `RAG_PERSIST_DIR`；
删除该目录会触发用种子数据重新构建。
