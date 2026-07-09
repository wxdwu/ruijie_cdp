import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

# 显式加载 backend/.env（位于本文件所在目录的上一级），不依赖启动时的 cwd。
# 这样无论 `cd backend && uvicorn` 还是从其他目录启动，都能稳定读到后端配置。
# 随后再用 load_dotenv() 兜底加载当前工作目录的 .env（可覆盖同名变量）。
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
if _BACKEND_ENV.exists():
    load_dotenv(dotenv_path=_BACKEND_ENV, override=False)
load_dotenv()


class Settings(BaseModel):
    DB_HOST: str = os.getenv("DB_HOST", "192.168.159.22")
    DB_PORT: int = int(os.getenv("DB_PORT", "33307"))
    DB_USER: str = os.getenv("DB_USER", "app_cdp")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "123456")
    DB_NAME: str = os.getenv("DB_NAME", "app_cdp")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    # Embedding API 独立配置（DeepSeek 不支持 /embeddings，需单独配置）
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "")

    # ElasticSearch 连接配置（DWS 数据检索 / 分析）
    ES_HOST: str = os.getenv("ES_HOST", "")
    ES_PORT: int = int(os.getenv("ES_PORT", "9200"))
    ES_USER: str = os.getenv("ES_USER", "elastic")
    ES_PASSWORD: str = os.getenv("ES_PASSWORD", "")
    ES_SCHEME: str = os.getenv("ES_SCHEME", "https")
    ES_INDEX_PREFIX: str = os.getenv("ES_INDEX_PREFIX", "cdp_")
    ES_VERIFY_CERTS: bool = os.getenv("ES_VERIFY_CERTS", "false").lower() == "true"
    ES_ANALYZER: str = os.getenv("ES_ANALYZER", "ik_max_word")

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


settings = Settings()
