"""HiveFlow - A reusable, generic multi-agent framework.

HiveFlow allows any multi-step collaborative workflow to be assembled from
universal agent definitions specialized at creation time.
"""

from hiveflow.core.agent import Agent, AgentBehaviorType, AgentResult
from hiveflow.core.checkpoint import (
    CheckpointError,
    CheckpointStorage,
    FileCheckpointStorage,
    WorkflowCheckpoint,
)
from hiveflow.core.citations import Citation, CitationTracker
from hiveflow.core.compression import ContextCompressor
from hiveflow.core.config import HiveFlowConfig, LLMTier, get_config, reset_config, set_config
from hiveflow.core.cost import CostTracker, UsageRecord, WorkflowCostReport
from hiveflow.core.fallback import FallbackChain, LLMFallbackExhaustedError, RetryProvider
from hiveflow.core.hiveflow import HiveFlow
from hiveflow.core.json_utils import extract_json_from_response, parse_json_resilient
from hiveflow.core.layout import LayoutTemplate, RenderedSection, list_layouts, load_layout
from hiveflow.core.output_types import (
    CitationsConfig,
    OutputOptions,
    OutputTypeDefinition,
    OutputTypeId,
    OutputTypeRegistry,
    PromptTemplateSet,
    route_output,
)
from hiveflow.core.prompts import PromptLibrary, PromptTemplate, get_default_library
from hiveflow.core.registry import BasePlugin, PluginRegistry
from hiveflow.core.research import (
    BranchResult,
    DeepResearchConfig,
    DeepResearcher,
    ResearchProgress,
)
from hiveflow.core.result_payload import ActionRecord, PayloadSection, ResultPayload
from hiveflow.core.schema import (
    AgentDefinition,
    CitationConfig,
    ModelRequirements,
    ScoringWeights,
    SourceCurationConfig,
    StateSchema,
    TeamConfiguration,
    VectorStoreConfig,
    WorkflowGraph,
    WorkflowStepDefinition,
    WorkflowStepType,
)
from hiveflow.core.session import ApprovalRequest, WorkflowSession
from hiveflow.core.source_curation import SourceCurationPipeline, SourceScore
from hiveflow.core.source_mode import (
    SourceMode,
    SourceModeRouter,
    SourceOptions,
)
from hiveflow.core.state import WorkflowState
from hiveflow.core.streaming import StreamChannel, StreamConsumer, StreamEvent, StreamEventType
from hiveflow.core.summarizer import SummaryGenerator
from hiveflow.core.teams import (
    ArchetypeLibrary,
    CapabilityGap,
    TeamGenerationResult,
    TeamGenerator,
    TeamTemplateLibrary,
)
from hiveflow.core.tone import ToneCatalog, ToneDefinition, inject_tone, should_inject_tone
from hiveflow.core.workflow import (
    WorkflowEngine,
    WorkflowResult,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.plugins.llm import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMProviderRegistry,
    LLMResponse,
    TokenUsage,
)
from hiveflow.plugins.skills import (
    Skill,
    SkillActivationTool,
    SkillLoader,
    SkillMetadata,
    SkillRegistry,
    get_skill_registry,
    reset_skill_registry,
)
from hiveflow.plugins.tools import ToolPlugin, ToolRegistry
from hiveflow.plugins.vector_stores import CollectionManager, VectorStorePlugin, VectorStoreRegistry
from hiveflow.plugins.vector_stores.memory_store import MemoryVectorStore

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "AgentBehaviorType",
    "AgentDefinition",
    "AgentResult",
    "ApprovalRequest",
    "ArchetypeLibrary",
    "BasePlugin",
    "BranchResult",
    "CapabilityGap",
    "CheckpointError",
    "CheckpointStorage",
    "Citation",
    "CitationConfig",
    "CitationsConfig",
    "CitationTracker",
    "CollectionManager",
    "ContextCompressor",
    "CostTracker",
    "DeepResearchConfig",
    "DeepResearcher",
    "FallbackChain",
    "FileCheckpointStorage",
    "HiveFlow",
    "HiveFlowConfig",
    "LLMConfig",
    "LLMFallbackExhaustedError",
    "LLMMessage",
    "LLMProvider",
    "LLMProviderRegistry",
    "LLMResponse",
    "LLMTier",
    "MemoryVectorStore",
    "ModelRequirements",
    "OutputOptions",
    "OutputTypeDefinition",
    "OutputTypeId",
    "OutputTypeRegistry",
    "PluginRegistry",
    "PromptLibrary",
    "PromptTemplate",
    "PromptTemplateSet",
    "ResearchProgress",
    "RetryProvider",
    "ScoringWeights",
    "Skill",
    "SkillActivationTool",
    "SkillLoader",
    "SkillMetadata",
    "SkillRegistry",
    "SourceCurationConfig",
    "SourceCurationPipeline",
    "SourceMode",
    "SourceModeRouter",
    "SourceOptions",
    "SourceScore",
    "StateSchema",
    "StreamChannel",
    "StreamConsumer",
    "StreamEvent",
    "StreamEventType",
    "SummaryGenerator",
    "TeamConfiguration",
    "TeamGenerationResult",
    "TeamGenerator",
    "TeamTemplateLibrary",
    "TokenUsage",
    "ToneCatalog",
    "ToneDefinition",
    "inject_tone",
    "should_inject_tone",
    "ToolPlugin",
    "ToolRegistry",
    "UsageRecord",
    "VectorStoreConfig",
    "VectorStorePlugin",
    "VectorStoreRegistry",
    "WorkflowCheckpoint",
    "WorkflowCostReport",
    "WorkflowEngine",
    "WorkflowGraph",
    "WorkflowResult",
    "WorkflowSession",
    "WorkflowState",
    "WorkflowStatus",
    "WorkflowStep",
    "WorkflowStepDefinition",
    "WorkflowStepType",
    "extract_json_from_response",
    "get_config",
    "get_default_library",
    "get_skill_registry",
    "parse_json_resilient",
    "reset_config",
    "reset_skill_registry",
    "set_config",
]
