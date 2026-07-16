import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

# ── 运行模式（一套源码，双模式）─────────────────────────────────────────────
# APP_ENV 取值：development（本地开发，连云 MySQL）/ production（docker 部署，连本机 docker MySQL）。
# 默认 production，保证 docker 容器即使未显式设置也走生产配置。
# 本地开发请显式设置：APP_ENV=development uvicorn app.main:app --reload --port 8000
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()

# 仅加载「模式专属」env 文件：backend/.env.{APP_ENV}（本文件位于 app/config/config.py，
# 故 backend/ 为上两级目录 parents[2]）。override=False 保证「真实进程环境变量 /
# docker 注入值」优先于文件，优先级：进程 env > .env.{APP_ENV} 文件 > 下方默认值。
_ENV_FILE = Path(__file__).resolve().parents[2] / f".env.{APP_ENV}"
if _ENV_FILE.exists():
    load_dotenv(dotenv_path=_ENV_FILE, override=False)
# 兜底：加载当前工作目录下的 .env（若存在），不覆盖已加载值。
load_dotenv(override=False)


class Settings(BaseModel):
    # 当前运行模式（development / production），供日志、健康检查等使用。
    APP_ENV: str = APP_ENV
    # 数据库默认指向「本机 docker MySQL」（deploy/docker-compose.yml 中的 mysql 服务，
    # host 网络模式下监听宿主机 127.0.0.1:3306），部署时无需 backend/.env 即可连库。
    # 说明：PyMySQL 1.1.1 未安装 cryptography，只能使用 mysql_native_password 认证，
    # 故直接用 root（已改为 mysql_native_password）。如改用 app_cdp，需先执行
    # deploy/sql_init/00_init_user.sql 创建该账号。
    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "root")
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
