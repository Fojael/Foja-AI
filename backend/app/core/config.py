from pathlib import Path
from typing import List
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory for backend and data paths
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    # Application Info
    APP_NAME: str = "Foja AI"
    PROJECT_NAME: str = "Foja AI"
    APP_VERSION: str = "0.1.0"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "Personal AI Desktop Assistant for Windows 11"
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    # CORS settings
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Database Configuration (SQLite default with aiosqlite, PostgreSQL-ready)
    DATABASE_URL: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'foja.db').resolve().as_posix()}"

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def resolve_sqlite_path(cls, v: str) -> str:
        """
        Ensure SQLite database paths always resolve to a deterministic absolute path,
        regardless of the working directory from which uvicorn or python is executed.
        """
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if v.startswith(prefix):
                raw_path = v[len(prefix):]
                if raw_path == ":memory:":
                    return v
                p = Path(raw_path)
                if not p.is_absolute():
                    clean_name = p.name
                    resolved = (DATA_DIR / clean_name).resolve()
                    return f"{prefix}{resolved.as_posix()}"
                else:
                    return f"{prefix}{p.resolve().as_posix()}"
        return v

    # Local AI Configuration (Ollama)
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    DEFAULT_OLLAMA_MODEL: str = "llama3.2:1b"
    OLLAMA_MODEL: str = "llama3.2:1b"

    # API & Client Timeouts
    API_TIMEOUT: float = 120.0
    OLLAMA_TIMEOUT_SECONDS: float = 120.0

    # Generation parameters
    MAX_PREDICT_TOKENS: int = 1024
    TEMPERATURE: float = 0.7

    # Memory Retrieval Configuration (Phase 2.4.3 & 2.4.3.2)
    MEMORY_RETRIEVAL_ENABLED: bool = True
    MEMORY_RETRIEVAL_MAX_RESULTS: int = 3
    MEMORY_RETRIEVAL_MAX_GLOBAL_RESULTS: int = 1
    MEMORY_RETRIEVAL_MIN_RELEVANCE: float = 0.2
    MEMORY_RETRIEVAL_RELEVANCE_WEIGHT: float = 0.75
    MEMORY_RETRIEVAL_IMPORTANCE_WEIGHT: float = 0.25
    MEMORY_RETRIEVAL_MAX_CONTEXT_CHARS: int = 1500
    MEMORY_RETRIEVAL_CANDIDATE_LIMIT: int = 50

    @field_validator("MEMORY_RETRIEVAL_MAX_RESULTS")
    @classmethod
    def validate_max_results(cls, v: int) -> int:
        if v < 1 or v > 20:
            raise ValueError("MEMORY_RETRIEVAL_MAX_RESULTS must be between 1 and 20.")
        return v

    @field_validator("MEMORY_RETRIEVAL_MAX_GLOBAL_RESULTS")
    @classmethod
    def validate_max_global_results(cls, v: int) -> int:
        if v < 0 or v > 10:
            raise ValueError("MEMORY_RETRIEVAL_MAX_GLOBAL_RESULTS must be between 0 and 10.")
        return v

    @field_validator("MEMORY_RETRIEVAL_MIN_RELEVANCE")
    @classmethod
    def validate_min_relevance(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("MEMORY_RETRIEVAL_MIN_RELEVANCE must be between 0.0 and 1.0.")
        return v

    @field_validator("MEMORY_RETRIEVAL_RELEVANCE_WEIGHT", "MEMORY_RETRIEVAL_IMPORTANCE_WEIGHT")
    @classmethod
    def validate_weights(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("Weights must be between 0.0 and 1.0.")
        return v

    @model_validator(mode="after")
    def validate_retrieval_weights_sum(self):
        rel_w = self.MEMORY_RETRIEVAL_RELEVANCE_WEIGHT
        imp_w = self.MEMORY_RETRIEVAL_IMPORTANCE_WEIGHT
        if abs((rel_w + imp_w) - 1.0) >= 1e-4:
            raise ValueError(
                f"MEMORY_RETRIEVAL_RELEVANCE_WEIGHT ({rel_w}) and "
                f"MEMORY_RETRIEVAL_IMPORTANCE_WEIGHT ({imp_w}) must sum to 1.0 (got {rel_w + imp_w})."
            )
        return self

    @field_validator("MEMORY_RETRIEVAL_MAX_CONTEXT_CHARS")
    @classmethod
    def validate_context_chars(cls, v: int) -> int:
        if v < 100 or v > 10000:
            raise ValueError("MEMORY_RETRIEVAL_MAX_CONTEXT_CHARS must be between 100 and 10000.")
        return v

    @field_validator("MEMORY_RETRIEVAL_CANDIDATE_LIMIT")
    @classmethod
    def validate_candidate_limit(cls, v: int) -> int:
        if v < 1 or v > 500:
            raise ValueError("MEMORY_RETRIEVAL_CANDIDATE_LIMIT must be between 1 and 500.")
        return v

    # Memory Extraction Configuration (Phase 2.4.4 & 2.4.4.2)
    MEMORY_EXTRACTION_ENABLED: bool = False
    MEMORY_EXTRACTION_MAX_CANDIDATES: int = 3
    MEMORY_EXTRACTION_MAX_MESSAGES: int = 10
    MEMORY_EXTRACTION_MAX_CONTENT_LENGTH: int = 500
    MEMORY_EXTRACTION_SHUTDOWN_TIMEOUT_SECONDS: float = 5.0

    @field_validator("MEMORY_EXTRACTION_SHUTDOWN_TIMEOUT_SECONDS")
    @classmethod
    def validate_shutdown_timeout(cls, v: float) -> float:
        if v < 0.5 or v > 60.0:
            raise ValueError("MEMORY_EXTRACTION_SHUTDOWN_TIMEOUT_SECONDS must be between 0.5 and 60.0 seconds.")
        return v

    @field_validator("MEMORY_EXTRACTION_MAX_CANDIDATES")
    @classmethod
    def validate_max_candidates(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("MEMORY_EXTRACTION_MAX_CANDIDATES must be between 1 and 10.")
        return v

    @field_validator("MEMORY_EXTRACTION_MAX_MESSAGES")
    @classmethod
    def validate_max_messages(cls, v: int) -> int:
        if v < 2 or v > 50:
            raise ValueError("MEMORY_EXTRACTION_MAX_MESSAGES must be between 2 and 50.")
        return v

    @field_validator("MEMORY_EXTRACTION_MAX_CONTENT_LENGTH")
    @classmethod
    def validate_max_content_length(cls, v: int) -> int:
        if v < 50 or v > 2000:
            raise ValueError("MEMORY_EXTRACTION_MAX_CONTENT_LENGTH must be between 50 and 2000.")
        return v

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
