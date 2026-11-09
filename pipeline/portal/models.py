import re
import uuid
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pipeline.portal.auth import Model
from pipeline.portal.remote import SENSITIVE


class ExternalCredential(Model):
    kind: Literal["bearer", "header"]
    secret: SecretStr
    header_name: str = "X-API-Key"

    @model_validator(mode="after")
    def valid_header(self):
        if not re.fullmatch(r"(?:X-[A-Za-z0-9-]{1,60}|Api-Key)", self.header_name, re.I):
            raise ValueError("Use a custom X- header or Api-Key for API-key credentials")
        raw = self.secret.get_secret_value()
        if not 8 <= len(raw) <= 4096 or any(ord(c) < 32 for c in raw):
            raise ValueError("External credentials are invalid")
        return self


class Pagination(Model):
    mode: Literal["none", "page"] = "none"
    page_parameter: str = Field(default="page", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,40}$")
    first_page: int = Field(default=1, ge=0, le=1000)
    max_pages: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def public_param(self):
        if SENSITIVE.search(self.page_parameter) or self.page_parameter.lower() == "key":
            raise ValueError("A pagination parameter cannot contain credentials")
        return self


class Connection(Model):
    url: str = Field(min_length=8, max_length=2048)
    name: str = Field(default="", max_length=200)
    schedule: Literal["manual", "daily", "weekly"] = "manual"
    format: Literal["csv", "xlsx", "json", "pdf"] = "json"
    records_path: str = Field(default="", max_length=200, pattern=r"^(?:[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)?$")
    parameters: dict[str, str | int | float] = Field(default_factory=dict, max_length=30)
    column_mapping: dict[str, str] = Field(default_factory=dict, max_length=200)
    pagination: Pagination = Field(default_factory=Pagination)
    credentials: ExternalCredential | None = None

    @model_validator(mode="after")
    def safe_parameters(self):
        if any(SENSITIVE.search(key) or key.lower() == "key" for key in self.parameters):
            raise ValueError("Use credential headers rather than credential parameters")
        names = list(self.column_mapping.values())
        if len(names) != len(set(names)) or any(not name.strip() or len(name) > 200 for name in names):
            raise ValueError("Column names must be non-empty and unique")
        return self

    def public_config(self):
        return self.model_dump(exclude={"credentials"})

    def secret_config(self):
        if not self.credentials:
            return None
        return {"kind": self.credentials.kind, "header_name": self.credentials.header_name,
                "secret": self.credentials.secret.get_secret_value()}


class Metadata(Model):
    organisation_id: uuid.UUID
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    topic: Literal["health", "economics", "agric", "education", "general"]
    licence: str = Field(min_length=3, max_length=2000)
    original_provider: str = Field(min_length=2, max_length=200)
    provenance: str = Field(min_length=3, max_length=2000)


class Submission(Metadata):
    access_method: Literal["api", "url"]
    connection: Connection

    @model_validator(mode="after")
    def contract(self):
        if self.access_method == "api" and (self.connection.format != "json" or not self.connection.name.strip()):
            raise ValueError("API connections require a friendly name and JSON responses")
        if self.access_method == "url" and self.connection.credentials:
            raise ValueError("Authenticated sources must use Connect an API")
        if self.connection.credentials:
            import json
            secret = self.connection.credentials.secret.get_secret_value()
            visible = [self.title, self.description, self.licence, self.original_provider, self.provenance,
                       json.dumps(self.connection.public_config())]
            if any(secret in value for value in visible):
                raise ValueError("External credentials must appear only in the credential field")
        return self


class TestConnection(Model):
    organisation_id: uuid.UUID
    connection: Connection
