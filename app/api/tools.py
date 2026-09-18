"""Merchant tool registry; execution remains behind the tools worker."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from urllib.parse import urlparse
from app.api.deps import TenantScope, tenant
from app.core.database import get_db
from app.models.orchestration import ToolDefinition

router = APIRouter(prefix="/tools", tags=["tools"])
class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)
    endpoint: str = Field(min_length=8, max_length=2048)
    method: str = Field(default="GET", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    input_schema: dict = Field(default_factory=dict)
    enabled: bool = True
def out(row): return {key: getattr(row, key) for key in ("id", "name", "description", "endpoint", "method", "input_schema", "enabled")}
@router.get("")
async def list_tools(scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    return [out(row) for row in (await db.execute(select(ToolDefinition).where(ToolDefinition.merchant_id == scope.merchant_id).order_by(ToolDefinition.id))).scalars()]
@router.post("", status_code=201)
async def create_tool(body: ToolInput, scope: TenantScope = Depends(tenant), db=Depends(get_db)):
    parsed = urlparse(body.endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(422, "tool endpoint must be an HTTPS URL without embedded credentials")
    row = ToolDefinition(merchant_id=scope.merchant_id, **body.model_dump()); db.add(row); await db.commit(); await db.refresh(row); return out(row)
