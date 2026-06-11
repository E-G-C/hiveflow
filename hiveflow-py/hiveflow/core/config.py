"""Configuration System - Layered configuration management.

Supports defaults -> config file -> environment variables -> team config overrides.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger()


class LLMTier(StrEnum):
    """Three-tier LLM model selection."""

    FAST = "FAST_LLM"  # Quick, cheap operations
    SMART = "SMART_LLM"  # Primary reasoning
    STRATEGIC = "STRATEGIC_LLM"  # Complex planning


class HiveFlowConfig(BaseSettings):
    """Main configuration class for HiveFlow framework.

    Configuration is layered:
    1. Defaults (defined here)
    2. Config file (JSON/YAML)
    3. Environment variables (HIVEFLOW_ prefix)
    4. Team config overrides (runtime)
    """

    # LLM Configuration
    FAST_LLM: str = "openai:gpt-4o-mini"
    SMART_LLM: str = "openai:gpt-4o"
    STRATEGIC_LLM: str = "openai:o3-mini"
    LLM_TEMPERATURE: float = 0.7
    MAX_TOKENS: int = 16000

    # Embedding Configuration
    EMBEDDING_PROVIDER: str = (
        "huggingface"  # huggingface (local transformer), local (numpy hashing), openai (API)
    )
    EMBEDDING_MODEL: str = (
        ""  # Provider-specific; empty = provider default (all-MiniLM-L6-v2 for huggingface)
    )

    # Retrieval Configuration
    RETRIEVERS: str = "tavily"  # Comma-separated list
    MAX_SEARCH_RESULTS_PER_QUERY: int = 10

    # Scraping Configuration
    SCRAPER: str = "beautifulsoup"
    MAX_SCRAPER_WORKERS: int = 15
    SCRAPER_RATE_LIMIT_DELAY: float = 0.1

    # Context Configuration
    SIMILARITY_THRESHOLD: float = 0.35
    BROWSE_CHUNK_MAX_LENGTH: int = 1000
    CHUNK_OVERLAP: int = 200
    TOTAL_WORDS: int = 8000

    # Context Management Strategy
    MAX_CONTEXT_PER_TASK: int = 4000  # Max context tokens passed to a sub-task worker
    MAX_SUMMARY_LENGTH: int = 200  # Max tokens for a sub-task summary
    MAX_OUTLINE_LENGTH: int = 1000  # Max tokens for cross-cutting outline
    ENABLE_SUMMARY_PROPAGATION: bool = True  # Toggle summary propagation on/off
    SUMMARY_THRESHOLD: int | None = None  # Min words before summarization activates (None = legacy)
    CONTEXT_RECENCY_WINDOW: int = (
        0  # Sliding window: only include N most recent agent summaries (0 = no limit)
    )

    # Output Configuration
    REPORT_FORMAT: str = "apa"
    LANGUAGE: str = "english"
    TONE: str = "objective"
    PUBLISH_FORMATS: str = ""  # Empty = all discovered publishers; comma-separated to restrict
    OUTPUT_DIR: str = "./output"

    # Deep Research Configuration
    DEEP_RESEARCH_BREADTH: int = 3
    DEEP_RESEARCH_DEPTH: int = 2
    DEEP_RESEARCH_CONCURRENCY: int = 4

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Cost Tracking
    ENABLE_COST_TRACKING: bool = True

    # Source Mode Configuration
    SOURCE_MODE: str = "web"  # web, local, hybrid, cloud, mcp, custom
    DOC_PATH: str | None = None  # Path to local documents when SOURCE_MODE includes local

    # Actions Configuration
    DEFAULT_ACTION_POLICY: str = "deny"  # deny, allow, dry_run
    ENABLE_ROLLBACK: bool = False
    ACTION_TIMEOUT: int = 30  # seconds

    # MCP Configuration
    MCP_STRATEGY: str = "disabled"  # disabled, fast, deep
    MCP_SERVERS: list[dict[str, Any]] = []
    MCP_AUTO_TOOL_SELECTION: bool = True

    # API Configuration
    CORS_ORIGINS: str = "*"  # Comma-separated allowed origins, or "*" for dev
    CORS_ALLOW_CREDENTIALS: bool = False  # Must be False when CORS_ORIGINS is "*"
    API_KEY: str = ""  # Empty = no auth required
    API_KEY_HEADER: str = "X-API-Key"
    API_RATE_LIMIT_RPM: int = 0  # Per-IP requests per minute (0 = disabled)
    MAX_UPLOAD_SIZE_MB: int = 50  # Max upload file size in megabytes

    # Collaboration Defaults
    COLLABORATION_ENABLED: bool = False
    COLLABORATION_MAX_DELEGATION_DEPTH: int = 3
    COLLABORATION_MAX_SPAWNED_AGENTS: int = 10
    COLLABORATION_DELEGATION_TIMEOUT: int = 300  # seconds
    COLLABORATION_BUDGET_POLICY: str = "inherit_parent"  # inherit_parent, fixed, unlimited

    # Task Preprocessing
    TASK_PREPROCESS_DISABLED: bool = False
    TASK_PREPROCESS_THRESHOLD_OVERRIDE: int = 0  # 0 = auto-compute from model
    TASK_CONTEXT_RATIO: float = 0.15  # Fraction of context window for threshold
    TASK_PIPELINE_FACTOR: float = 0.3  # Per-agent context multiplier
    TASK_CHUNK_CONTEXT_RATIO: float = 0.10  # Fraction of context window per chunk
    TASK_CHUNK_OVERLAP_RATIO: float = 0.10  # Overlap as fraction of chunk size
    TASK_TOKENS_PER_WORD: float = 1.35  # Token-to-word conversion ratio

    model_config = SettingsConfigDict(env_prefix="HIVEFLOW_", case_sensitive=False)

    def resolve_model(self, model_ref: str) -> str:
        """Resolve model reference to actual model string.

        Supports tier variables like $SMART_LLM or direct model refs like openai:gpt-4o.

        Args:
            model_ref: Model reference string

        Returns:
            Resolved model string in format provider:model
        """
        if model_ref.startswith("$"):
            # Resolve tier variable
            tier_var = model_ref[1:]  # Remove $
            return getattr(self, tier_var, self.SMART_LLM)
        return model_ref

    def get_retrievers(self) -> list[str]:
        """Parse comma-separated retriever list.

        Returns:
            List of retriever IDs
        """
        return [r.strip() for r in self.RETRIEVERS.split(",")]

    def get_publish_formats(self) -> list[str]:
        """Parse comma-separated publish format list.

        Returns an empty list when PUBLISH_FORMATS is blank, which signals
        callers to use all discovered publisher plugins.

        Returns:
            List of format IDs (empty means 'all available')
        """
        stripped = self.PUBLISH_FORMATS.strip()
        if not stripped:
            return []
        return [f.strip() for f in stripped.split(",") if f.strip()]

    def apply_overrides(self, overrides: dict[str, Any]) -> "HiveFlowConfig":
        """Create a new config with overrides applied.

        This implements the team config override layer. Values from the
        overrides dict are applied on top of the current config.

        Args:
            overrides: Dictionary of config key -> value overrides

        Returns:
            New HiveFlowConfig with overrides applied
        """
        current = self.model_dump()
        current.update({k.upper(): v for k, v in overrides.items()})
        return HiveFlowConfig(**current)

    @classmethod
    def from_file(cls, path: str | Path) -> "HiveFlowConfig":
        """Load config from a JSON or YAML file.

        Environment variables still override file values (pydantic-settings behavior).

        Args:
            path: Path to JSON or YAML config file

        Returns:
            HiveFlowConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If file format is unsupported
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")

        suffix = file_path.suffix.lower()

        if suffix == ".json":
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        elif suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore[import-untyped]
            except ImportError as exc:
                raise ImportError(
                    "PyYAML required for YAML config. Install with: uv add pyyaml"
                ) from exc
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            raise ValueError(f"Unsupported config file format: {suffix}")

        # Normalize keys to uppercase
        normalized = {k.upper(): v for k, v in data.items()}
        return cls(**normalized)


# Global config instance
_config: HiveFlowConfig | None = None


def get_config() -> HiveFlowConfig:
    """Get or create global config instance.

    Returns:
        HiveFlowConfig instance
    """
    global _config  # noqa: PLW0603
    if _config is None:
        _config = HiveFlowConfig()
    return _config


def set_config(config: HiveFlowConfig) -> None:
    """Set the global config instance.

    Args:
        config: HiveFlowConfig instance to use globally
    """
    global _config  # noqa: PLW0603
    _config = config


def reset_config() -> None:
    """Reset global config (mainly for testing)."""
    global _config  # noqa: PLW0603
    _config = None
