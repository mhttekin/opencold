"""Company candidate and contact records used by discovery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CandidateCompany:
    company: str
    website: str
    discovery_source_url: str
    discovery_reason: str
    discovery_channel: str = ""


@dataclass
class Contact:
    name: str = ""
    role: str = ""
    email: str = ""
    contact_type: str = ""
    confidence: int = 0
    source_url: str = ""
