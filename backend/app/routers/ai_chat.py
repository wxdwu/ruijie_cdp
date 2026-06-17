"""
AI Chat router - 集成 AI 服务

Provides endpoints for:
- POST /api/ai/parse - Parse natural language to extract entities
- POST /api/ai/chat - Return AI response + customer list results
- POST /api/ai/chat/export - Export chat query results

已集成完整的 AI 对话功能（使用 DeepSeek-chat 模型）：
1. 用户输入预处理
2. 意图识别（预处理和意图识别共调用一次模型）
3. 核心业务处理（根据用户问答获取，生成SQL查询）
4. SQL结果输出转化（将SQL结果喂给大模型分析）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.ai_service import process_chat, export_query_results

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models (保持兼容性)
# ─────────────────────────────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    query: Optional[str] = None
    text: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None

    def get_query(self) -> str:
        return self.query or self.text or ""


class ChatRequest(BaseModel):
    query: Optional[str] = None
    text: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None

    def get_query(self) -> str:
        return self.query or self.text or ""


class ChatExportRequest(BaseModel):
    query: str
    entities: Dict[str, Any]
    structured_query: Optional[Dict[str, Any]] = None  # 新增：结构化查询


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/parse")
def parse_natural_language(
    request: ParseRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Parse natural language query and extract entities."""
    q = request.get_query()
    if not q:
        return {"query": "", "entities": {}}
    
    # 使用 AI 服务进行意图识别
    from app.services.ai_service import recognize_intent
    result = recognize_intent(q, request.history)
    
    return {
        "query": q,
        "entities": result.get("structured_query", {}),
        "intent": result.get("intent", "other"),
    }


@router.post("/chat")
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Process chat query and return AI response + customer results.
    
    使用完整的 AI 对话流程：
    1. 用户输入预处理
    2. 意图识别
    3. 根据意图处理（业务查询/简单问题/其他问题）
    4. 返回结果和 AI 分析
    """
    q = request.get_query()
    if not q:
        return {
            "query": "",
            "entities": {},
            "response": "请输入查询内容",
            "customers": {"total": 0, "items": [], "page": 1, "page_size": 50},
        }
    
    # 使用 AI 服务处理完整对话流程
    result = process_chat(q, request.history, db)
    
    # 保持返回格式兼容性
    return {
        "query": result["query"],
        "entities": result.get("structured_query", {}),
        "response": result["response"],
        "customers": result["customers"],
        "intent": result.get("intent", "other"),
        "preprocessed_query": result.get("preprocessed_query", ""),
    }


@router.post("/chat/export")
def export_chat_results(
    request: ChatExportRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Export chat query results to Excel.
    
    支持两种导出方式：
    1. 使用 entities（兼容旧版）
    2. 使用 structured_query（新版）
    """
    # 优先使用 structured_query
    structured_query = request.structured_query or request.entities
    
    if not structured_query:
        raise HTTPException(
            status_code=400,
            detail="Missing entities or structured_query",
        )
    
    try:
        # 使用 AI 服务导出功能（openpyxl 在 ai_service.export_query_results 中导入）
        excel_bytes = export_query_results(structured_query, db)
        
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="ai_chat_export.xlsx"',
            },
        )
    except Exception as e:
        logger.error("导出失败: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"导出失败: {str(e)}",
        )
