from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from src.core.prompt_manager import prompt_manager

router = APIRouter()

class PromptUpdateRequest(BaseModel):
    content: str
    group: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None

class PromptResponse(BaseModel):
    key: str
    group: str
    role: Optional[str] = None
    content: str
    version: int
    description: Optional[str]
    updated_at: Optional[str]

@router.get("", response_model=List[PromptResponse])
async def list_prompts():
    """List all available prompts."""
    return prompt_manager.list_all()

@router.post("/{key}", response_model=PromptResponse)
async def update_prompt(key: str, request: PromptUpdateRequest):
    """Update or create a prompt."""
    try:
        config = prompt_manager.set(
            key=key, 
            content=request.content, 
            group=request.group if request.group else "general",
            role=request.role,
            description=request.description
        )
        return config.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/system/refresh")
async def refresh_prompts():
    """Force refresh prompt cache from database."""
    prompt_manager.refresh()
    return {"status": "ok", "message": "Prompt cache refreshed"}
