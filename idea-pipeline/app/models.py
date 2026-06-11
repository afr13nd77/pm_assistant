from typing import Literal

from pydantic import BaseModel, model_validator


class PipelineRunRequest(BaseModel):
    text: str | None = None
    file_path: str | None = None
    start_from: Literal["analyst", "pm", "decomposer"] = "analyst"
    notify_chat_id: str | None = None
    domain: str = "general"

    @model_validator(mode="after")
    def validate_input(self) -> "PipelineRunRequest":
        if self.text is not None and self.file_path is not None:
            raise ValueError("Provide either text or file_path, not both")
        if self.text is None and self.file_path is None:
            raise ValueError("Either text or file_path must be provided")
        if self.text is not None:
            stripped = self.text.strip()
            if not stripped:
                raise ValueError("text must not be empty or whitespace only")
            if len(self.text) < 10 or len(self.text) > 5000:
                raise ValueError("Text length must be 10-5000 chars")
        if self.file_path is not None:
            if ".." in self.file_path:
                raise ValueError("file_path must not contain '..'")
            if not self.file_path.endswith(".md"):
                raise ValueError("file_path must end with .md")
        return self


class PipelineRunResponse(BaseModel):
    pipeline_id: str
    status: str
    vault_dir: str
    message: str


class PipelineStatusResponse(BaseModel):
    pipeline_id: str
    status: str
    slug: str
    vault_dir: str
    created_at: str
    updated_at: str
    artifacts: list[str]
    error: str | None = None
    failed_stage: str | None = None


class PipelineResumeRequest(BaseModel):
    start_from: Literal["analyst", "pm", "decomposer"]


class PipelineListItem(BaseModel):
    pipeline_id: str
    slug: str
    status: str
    created_at: str
    artifacts_count: int


class PipelineListResponse(BaseModel):
    runs: list[PipelineListItem]
    total: int


class HealthResponse(BaseModel):
    status: str
    version: str
    vault_accessible: bool
    claude_api_configured: bool


class ErrorResponse(BaseModel):
    error: str
    detail: str
