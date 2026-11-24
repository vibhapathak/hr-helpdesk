from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (any provider supported by langchain's init_chat_model, "provider:model")
    llm_model: str = "openai:gpt-4o-mini"
    guard_model: str = ""  # defaults to llm_model; a smaller/cheaper model works fine
    llm_temperature: float = 0.0
    max_agent_steps: int = 6
    # Free-tier friendliness: client-side pacing per model (0 = off) and retries on HTTP 429
    llm_requests_per_minute: float = 0
    llm_max_retries: int = 5

    # RAG
    policies_dir: str = "/app/policies"
    qdrant_url: str = "http://qdrant:6333"  # ":memory:" for tests
    qdrant_collection: str = "hr_it_policies"
    embedding_backend: str = "fastembed"  # "fastembed" (local ONNX) or "hash" (offline tests only)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = "/models"
    rag_top_k: int = 4
    rag_min_score: float = 0.35

    # MCP
    mcp_server_url: str = "http://mcp-server:8001/mcp"

    # Guardrails
    use_llm_guard: bool = True
    pii_allowlist_emails: str = (
        "hr-helpdesk@acme-corp.example,it-helpdesk@acme-corp.example,"
        "security@acme-corp.example,phishing@acme-corp.example"
    )

    # Tickets: monday.com if both are set, otherwise a local mock (JSONL file)
    monday_api_token: str = ""
    monday_board_id: str = ""
    tickets_file: str = "/data/tickets/tickets.jsonl"

    @property
    def guard_model_name(self) -> str:
        return self.guard_model or self.llm_model

    @property
    def allowlisted_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.pii_allowlist_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
