# app/config 子包入口。
# 原 app/config.py 已迁移为 app/config/config.py，这里重新导出 settings / Settings，
# 使既有 `from app.config import settings` 引用无需改动。
from app.config.config import Settings, settings

__all__ = ["Settings", "settings"]
