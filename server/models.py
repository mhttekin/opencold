"""Pydantic request/response models for the OpenCold HTTP API.

Credentials (LLM api_key, SMTP password) arrive per request and are never
persisted — this service holds no disk config of its own.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── /v1/run request ──────────────────────────────────────────────────────────


class ProviderIn(BaseModel):
    type: Literal["anthropic", "openai", "proxy"] = "anthropic"
    api_key: str
    model: str
    base_url: Optional[str] = None
    max_tokens: Optional[int] = None


class IdentityIn(BaseModel):
    name: str = ""
    email: str = ""


class ProfileIn(BaseModel):
    company: str = ""
    role: str = ""
    bio: str = ""
    pitch: str = ""


class CampaignIn(BaseModel):
    title: str = ""
    description: str = ""
    pitch: str = ""


class RunOptions(BaseModel):
    workers: int = 5
    delay: float = 0.5
    template: Optional[str] = None
    system_prompt: Optional[str] = None
    max_tokens: Optional[int] = None
    do_resolve_websites: bool = True
    do_enrich: bool = True
    do_verify: bool = True
    drop_invalid: bool = False


class RunRequest(BaseModel):
    leads: list[dict[str, str]] = Field(default_factory=list)
    campaign: CampaignIn = Field(default_factory=CampaignIn)
    identity: IdentityIn = Field(default_factory=IdentityIn)
    profile: ProfileIn = Field(default_factory=ProfileIn)
    provider: ProviderIn
    options: RunOptions = Field(default_factory=RunOptions)


# ── /v1/run responses ────────────────────────────────────────────────────────


class JobAccepted(BaseModel):
    job_id: str


class Progress(BaseModel):
    current: Optional[int] = None
    total: Optional[int] = None
    message: Optional[str] = None


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    phase: Optional[str] = None
    progress: Optional[Progress] = None
    # Result rows carry the input columns plus generated_subject / generated_email
    # / quality_warnings, so they are returned as free-form dicts.
    results: Optional[list[dict]] = None
    error: Optional[str] = None


# ── /v1/send ─────────────────────────────────────────────────────────────────


class SmtpIn(BaseModel):
    host: str
    port: int
    username: str
    password: str
    sender_email: str
    sender_name: str = ""
    use_tls: bool = True


class SendItem(BaseModel):
    email: str
    name: str = ""
    subject: str
    body: str


class SendRequest(BaseModel):
    smtp: SmtpIn
    items: list[SendItem]


class SendResult(BaseModel):
    email: str
    sent: bool
    error: Optional[str] = None


class SendResponse(BaseModel):
    results: list[SendResult]
    sent: int
    failed: int
