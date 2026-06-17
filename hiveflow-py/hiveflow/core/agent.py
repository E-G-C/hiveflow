"""Universal Agent Class - Core of HiveFlow framework.

This module defines the universal agent that can be specialized at creation time
through configuration rather than code.
"""

import json
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from hiveflow.core.json_utils import parse_json_resilient
from hiveflow.plugins.llm import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    get_llm_registry,
)
from hiveflow.plugins.tools import ToolPlugin

if TYPE_CHECKING:
    from hiveflow.core.context_reducer import ContextReducer
    from hiveflow.core.cost import CostTracker
    from hiveflow.core.schema import AgentDefinition
    from hiveflow.plugins.skills.models import Skill

logger = structlog.get_logger()


class AgentBehaviorType(StrEnum):
    """Defines how an agent executes its task."""

    LLM_ONLY = "llm_only"  # Pure prompt -> LLM -> response
    TOOL_USER = "tool_user"  # Has access to external tools
    ORCHESTRATOR = "orchestrator"  # Can spawn sub-workflows
    HUMAN_GATE = "human_gate"  # Pauses for human input
    ACTION_EXECUTOR = "action_executor"  # Performs side effects with safety policies


class AgentResult:
    """Result of an agent execution step."""

    def __init__(
        self,
        agent_id: str,
        output: dict[str, Any],
        response: LLMResponse | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        latency_ms: float = 0,
    ) -> None:
        self.agent_id = agent_id
        self.output = output
        self.response = response
        self.tool_results = tool_results
        self.latency_ms = latency_ms


class Agent:
    """Universal agent class specialized through configuration.

    Instead of one class per role, this single class is specialized at creation
    time through configuration of system prompt, tools, behavior type, and model.
    """

    def __init__(
        self,
        agent_id: str,
        role: str,
        system_prompt: str,
        behavior_type: AgentBehaviorType,
        tools: list[ToolPlugin] | None = None,
        model: str = "$SMART_LLM",
        llm_provider: LLMProvider | None = None,
        llm_config: LLMConfig | None = None,
        max_tool_iterations: int = 10,
        context_budget: int | None = None,
        agent_definition: "AgentDefinition | None" = None,
        action_policy: str | None = None,
        output_type: str | None = None,
        context_recency_window: int = 0,
        context_reducer: "ContextReducer | None" = None,
        skills: "list[Skill] | None" = None,
    ) -> None:
        """Initialize agent with configuration.

        Args:
            agent_id: Unique identifier for this agent
            role: Human-readable role description
            system_prompt: Defines agent's identity and behavior
            behavior_type: How the agent executes (llm_only, tool_user, etc.)
            tools: Optional list of tool plugin instances
            model: Which LLM backs this agent (supports tier variables)
            llm_provider: LLM provider instance
            llm_config: Base LLM configuration
            max_tool_iterations: Max tool call loops before stopping
            context_budget: Max words for context passed to this agent.
                When set, _summarize_state() truncates assembled context
                to fit within this budget. None = no enforcement.
            agent_definition: Optional AgentDefinition for document scoping.
            action_policy: Safety policy for action_executor (\"auto\" or \"require_approval\").
            output_type: Expected output type (text, structured_data, side_effect, composite).
            context_recency_window: Sliding window size for prior agent summaries.
                When >0, only the N most recent agent summaries/outputs are
                included fully; older ones are collapsed into a single line.
                0 = include all (no windowing).
            context_reducer: Optional ContextReducer for intelligent context
                compression via LLM. When set and context_budget is exceeded,
                the reducer is invoked before mechanical truncation.
            skills: Optional list of Skill instances providing domain expertise.
                For llm_only agents, skill instructions are injected into the
                system prompt. For tool_user agents, skill metadata is injected
                and a SkillActivationTool enables on-demand loading.
        """
        self.agent_id = agent_id
        self.role = role
        self.system_prompt = system_prompt
        self.behavior_type = behavior_type
        self.tools = tools or []
        self.skills = skills or []
        self.model = model
        self.llm_provider = llm_provider or self._resolve_provider_from_model(model)
        self.llm_config = llm_config or LLMConfig()
        self.max_tool_iterations = max_tool_iterations
        self.context_budget = context_budget
        self.agent_definition = agent_definition
        self.action_policy = action_policy
        self.output_type = output_type
        self.context_recency_window = context_recency_window
        self.context_reducer = context_reducer

        # Wrap LLM provider with resilience layer if available
        if self.llm_provider is not None:
            self._wrap_with_resilience()

        # Build tool lookup by ID (and by llm_name for MCP tools)
        self._tool_map: dict[str, ToolPlugin] = {}
        for tool in self.tools:
            self._tool_map[tool.plugin_id] = tool
            llm_name = getattr(tool, "llm_name", None)
            if llm_name and llm_name != tool.plugin_id:
                self._tool_map[llm_name] = tool

    @staticmethod
    def _resolve_model_ref(model: str) -> str:
        """Resolve tier variables like ``$SMART_LLM`` to provider:model refs."""
        if model.startswith("$"):
            from hiveflow.core.config import get_config

            return get_config().resolve_model(model)
        return model

    def _resolve_provider_from_model(self, model: str) -> LLMProvider | None:
        """Resolve provider from a ``provider:model`` reference when possible."""
        resolved_model = self._resolve_model_ref(model)
        if ":" not in resolved_model:
            return None

        try:
            provider, _model_name = get_llm_registry().resolve_model(resolved_model)
        except (KeyError, ValueError):
            logger.debug(
                "Could not resolve provider for agent %s model %s",
                self.agent_id,
                resolved_model,
            )
            return None
        return provider

    def _wrap_with_resilience(self, cost_tracker: "CostTracker | None" = None) -> None:
        """Wrap llm_provider with ResilientLLMProvider if not already wrapped."""
        from hiveflow.core.resilient_provider import ResilientLLMProvider

        if isinstance(self.llm_provider, ResilientLLMProvider):
            return
        try:
            from hiveflow.core.config import get_config

            config = get_config()
            self.llm_provider = ResilientLLMProvider.from_config(
                self.llm_provider, config, cost_tracker=cost_tracker, agent_id=self.agent_id
            )
        except Exception:
            logger.debug("Could not wrap provider with resilience for agent %s", self.agent_id)

    def get_cost_tracker(self) -> Any:
        """Return the CostTracker from the resilient provider, if available."""
        from hiveflow.core.resilient_provider import ResilientLLMProvider

        if isinstance(self.llm_provider, ResilientLLMProvider):
            return self.llm_provider._cost_tracker
        return None

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute agent's task based on current state.

        Emits paired EXECUTOR_INVOKED/EXECUTOR_COMPLETED events for observability.

        Args:
            state: Current workflow state

        Returns:
            Updated state after agent execution
        """
        start_time = time.monotonic()

        # Emit EXECUTOR_INVOKED event (FR-022)
        stream_channel = state.get("_stream_channel")
        step_id = f"{self.agent_id}_{int(start_time * 1000)}"
        if stream_channel and hasattr(stream_channel, "publish"):
            from hiveflow.core.streaming import EventMetadata, StreamEvent, StreamEventType

            await stream_channel.publish(
                StreamEvent(
                    event_type=StreamEventType.EXECUTOR_INVOKED,
                    agent_id=self.agent_id,
                    step_id=step_id,
                    content=f"Agent {self.agent_id} executing ({self.behavior_type})",
                    data={"task": state.get("task", ""), "behavior_type": self.behavior_type},
                )
            )

        if self.behavior_type == AgentBehaviorType.LLM_ONLY:
            result = await self._execute_llm_only(state)
        elif self.behavior_type == AgentBehaviorType.TOOL_USER:
            result = await self._execute_tool_user(state)
        elif self.behavior_type == AgentBehaviorType.ORCHESTRATOR:
            result = await self._execute_orchestrator(state)
        elif self.behavior_type == AgentBehaviorType.HUMAN_GATE:
            result = await self._execute_human_gate(state)
        elif self.behavior_type == AgentBehaviorType.ACTION_EXECUTOR:
            result = await self._execute_action_executor(state)
        else:
            raise ValueError(f"Unknown behavior type: {self.behavior_type}")

        elapsed = (time.monotonic() - start_time) * 1000
        logger.info("Agent %s completed in %.0fms", self.agent_id, elapsed)

        # Emit EXECUTOR_COMPLETED event (FR-022)
        if stream_channel and hasattr(stream_channel, "publish"):
            from hiveflow.core.streaming import EventMetadata, StreamEvent, StreamEventType

            output_key = f"{self.agent_id}_output"
            await stream_channel.publish(
                StreamEvent(
                    event_type=StreamEventType.EXECUTOR_COMPLETED,
                    agent_id=self.agent_id,
                    step_id=step_id,
                    content=str(result.get(output_key, ""))[:500],
                    metadata=EventMetadata(latency_ms=elapsed),
                )
            )

        return result

    async def _execute_llm_only(self, state: dict[str, Any]) -> dict[str, Any]:
        """Pure LLM execution: prompt -> LLM -> response."""
        if not self.llm_provider:
            raise RuntimeError(f"Agent '{self.agent_id}' has no LLM provider configured")

        messages = self._build_messages(state)

        # Apply async LLM-based context reduction if available
        if self.context_reducer and self.context_budget and len(messages) > 1:
            messages = await self._apply_context_reduction(messages, state)

        config = self._build_config()
        response = await self.llm_provider.chat(messages, config)

        return {
            **state,
            f"{self.agent_id}_output": response.content,
            f"{self.agent_id}_usage": (
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                if response.usage
                else None
            ),
        }

    async def _execute_tool_user(self, state: dict[str, Any]) -> dict[str, Any]:
        """LLM with tool calling: iterative tool use loop."""
        if not self.llm_provider:
            raise RuntimeError(f"Agent '{self.agent_id}' has no LLM provider configured")

        # Inject state documents into tools that support it
        documents = state.get("documents", [])
        if documents:
            for tool in self.tools:
                if hasattr(tool, "set_documents"):
                    tool.set_documents(documents)

        messages = self._build_messages(state)

        # Apply async LLM-based context reduction if available
        if self.context_reducer and self.context_budget and len(messages) > 1:
            messages = await self._apply_context_reduction(messages, state)

        config = self._build_config()

        # Add tool specs to config
        if self.tools:
            config.tools = [tool.to_llm_tool_spec() for tool in self.tools]

        all_tool_results: list[dict[str, Any]] = []

        response = None
        for _ in range(self.max_tool_iterations):
            response = await self.llm_provider.chat(messages, config)

            # If no tool calls, we're done
            if not response.tool_calls:
                break

            # Process each tool call
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            for tool_call in response.tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name", "")
                tool_args_str = func.get("arguments", "{}")
                tool_call_id = tool_call.get("id", "")

                tool_args = parse_json_resilient(tool_args_str, default={}, expect_type=dict)

                tool = self._tool_map.get(tool_name)
                if tool:
                    try:
                        tool_result = await tool.execute(tool_args)
                        result_str = json.dumps(tool_result)
                    except Exception as e:
                        logger.exception(
                            "Tool %s failed in agent %s",
                            tool_name,
                            self.agent_id,
                        )
                        tool_result = {"error": str(e)}
                        result_str = json.dumps(tool_result)
                else:
                    tool_result = {"error": f"Unknown tool: {tool_name}"}
                    result_str = json.dumps(tool_result)

                all_tool_results.append(
                    {
                        "tool": tool_name,
                        "input": tool_args,
                        "output": tool_result,
                    }
                )

                messages.append(
                    LLMMessage(
                        role="tool",
                        content=result_str,
                        tool_call_id=tool_call_id,
                    )
                )

            # Continue loop to let LLM process tool results
        else:
            logger.warning(
                "Agent %s hit max tool iterations (%d)",
                self.agent_id,
                self.max_tool_iterations,
            )

        if response is None:
            raise RuntimeError(
                f"Agent '{self.agent_id}' produced no response "
                f"(max_tool_iterations={self.max_tool_iterations})"
            )

        return {
            **state,
            f"{self.agent_id}_output": response.content,
            f"{self.agent_id}_tool_results": all_tool_results,
            f"{self.agent_id}_usage": (
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                if response.usage
                else None
            ),
        }

    async def _execute_orchestrator(self, state: dict[str, Any]) -> dict[str, Any]:
        """Orchestrator execution: decomposes task into parallel sub-tasks.

        Uses LLM to analyze the task and break it into independent
        sub-tasks that can be processed in parallel by downstream
        worker agents. The sub-tasks are stored as ``parallel_items``
        in state so the next parallel_fan_out step can pick them up.
        """
        if not self.llm_provider:
            raise RuntimeError(f"Agent '{self.agent_id}' has no LLM provider configured")

        task = state.get("task", "")
        input_data = state.get("input_data", "")

        decomposition_prompt = (
            "Break the following task into independent sub-tasks that can be "
            "executed in parallel. Each sub-task should be self-contained and "
            "not depend on results from other sub-tasks.\n\n"
            "Respond with ONLY a JSON object in this exact format:\n"
            '{"sub_tasks": ["description of sub-task 1", "description of sub-task 2", ...]}\n\n'
            f"Task: {task}"
        )
        if input_data:
            decomposition_prompt += f"\n\nInput data:\n{input_data}"

        messages = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(role="user", content=decomposition_prompt),
        ]
        config = self._build_config()
        response = await self.llm_provider.chat(messages, config)

        # Parse sub-tasks from response
        sub_tasks = self._parse_sub_tasks(response.content)
        logger.info(
            "Orchestrator %s decomposed task into %d sub-tasks",
            self.agent_id,
            len(sub_tasks),
        )

        return {
            **state,
            f"{self.agent_id}_output": response.content,
            "parallel_items": sub_tasks,
            f"{self.agent_id}_usage": (
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                if response.usage
                else None
            ),
        }

    def _parse_sub_tasks(self, response: str) -> list[str]:
        """Parse sub-task list from LLM response.

        Attempts JSON parsing first, falls back to line-based extraction.

        Args:
            response: Raw LLM response text

        Returns:
            List of sub-task description strings
        """
        # Try JSON parsing first (with resilient parser)
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            data = parse_json_resilient(response[start:end], default=None, expect_type=dict)
            if data and isinstance(data.get("sub_tasks"), list):
                return [str(t) for t in data["sub_tasks"] if t]

        # Fallback: extract numbered/bulleted lines
        lines = response.strip().split("\n")
        tasks = []
        for line in lines:
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
                cleaned = line.lstrip("0123456789.-*) ").strip()
                if cleaned:
                    tasks.append(cleaned)

        return tasks if tasks else [response.strip()]

    async def _execute_human_gate(self, state: dict[str, Any]) -> dict[str, Any]:
        """Human gate: pauses for human input.

        Checks state for a human_input key. If present, includes it
        in the output. The workflow engine is responsible for actually
        pausing execution and collecting human input.
        """
        human_input = state.get("human_input")

        if human_input is not None:
            return {
                **state,
                f"{self.agent_id}_output": human_input,
                "human_approved": True,
            }

        # Signal that human input is needed
        return {
            **state,
            "awaiting_human_input": True,
            "human_prompt": f"Agent '{self.role}' requires your input.",
        }

    async def _execute_action_executor(self, state: dict[str, Any]) -> dict[str, Any]:
        """Action executor: performs side effects via tools with safety policies.

        Reuses the tool_user execution loop but adds a safety gate:
        - When action_policy='require_approval': pauses after LLM proposes
          tool calls, surfaces proposed actions for human approval.
        - When action_policy='dry_run': records proposed actions without
          executing any tools, returning a dry-run plan.
        - When action_policy='auto': executes tools immediately and records
          each as a structured audit entry in the workflow state.
        - When action_policy='confirm_on_error': executes tools immediately
          like 'auto', but pauses for confirmation when a tool call fails.
        """
        if not self.llm_provider:
            raise RuntimeError(f"Agent '{self.agent_id}' has no LLM provider configured")

        messages = self._build_messages(state)
        config = self._build_config()

        # Add tool specs to config
        if self.tools:
            config.tools = [tool.to_llm_tool_spec() for tool in self.tools]

        all_action_records: list[dict[str, Any]] = []

        response: LLMResponse | None = None
        for _ in range(self.max_tool_iterations):
            response = await self.llm_provider.chat(messages, config)

            # If no tool calls, we're done
            if not response.tool_calls:
                break

            # For require_approval: pause before executing any tools
            if self.action_policy == "require_approval":
                proposed_actions = []
                for tool_call in response.tool_calls:
                    func = tool_call.get("function", {})
                    tool_args_str = func.get("arguments", "{}")
                    tool_args = parse_json_resilient(tool_args_str, default={}, expect_type=dict)
                    proposed_actions.append(
                        {
                            "tool": func.get("name", ""),
                            "arguments": tool_args,
                            "tool_call_id": tool_call.get("id", ""),
                        }
                    )

                return {
                    **state,
                    "awaiting_action_approval": True,
                    f"{self.agent_id}_proposed_actions": proposed_actions,
                    f"{self.agent_id}_output": response.content or "",
                }

            # For dry_run: record proposed actions without executing tools
            if self.action_policy == "dry_run":
                dry_run_plan = []
                for tool_call in response.tool_calls:
                    func = tool_call.get("function", {})
                    tool_args_str = func.get("arguments", "{}")
                    tool_args = parse_json_resilient(tool_args_str, default={}, expect_type=dict)
                    dry_run_plan.append(
                        {
                            "tool": func.get("name", ""),
                            "arguments": tool_args,
                            "tool_call_id": tool_call.get("id", ""),
                        }
                    )
                    all_action_records.append(
                        {
                            "agent_id": self.agent_id,
                            "tool": func.get("name", ""),
                            "arguments": tool_args,
                            "result": None,
                            "status": "dry_run",
                            "policy": self.action_policy,
                            "approved_by": None,
                            "reversible": getattr(
                                self.agent_definition, "rollback_on_failure", False
                            )
                            if self.agent_definition
                            else False,
                            "rollback_action": getattr(
                                self.agent_definition, "rollback_action", None
                            )
                            if self.agent_definition
                            else None,
                            "workflow_run_id": state.get("workflow_run_id"),
                        }
                    )

                return {
                    **state,
                    f"{self.agent_id}_dry_run_plan": dry_run_plan,
                    f"{self.agent_id}_action_records": all_action_records,
                    f"{self.agent_id}_output": response.content or "",
                }

            # For auto and confirm_on_error: execute tools through ActionQueue for
            # concurrency control and timeout enforcement
            from hiveflow.core.action_queue import ActionQueue

            try:
                from hiveflow.core.config import get_config

                _cfg = get_config()
                _action_queue = ActionQueue(
                    max_concurrency=5,
                    timeout=float(_cfg.ACTION_TIMEOUT),
                    enable_rollback=_cfg.ENABLE_ROLLBACK,
                )
            except Exception:
                _action_queue = ActionQueue()

            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )

            for tool_call in response.tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name", "")
                tool_args_str = func.get("arguments", "{}")
                tool_call_id = tool_call.get("id", "")

                tool_args = parse_json_resilient(tool_args_str, default={}, expect_type=dict)

                tool = self._tool_map.get(tool_name)
                if tool:
                    action_result = await _action_queue.submit(
                        f"{self.agent_id}:{tool_name}",
                        tool.execute,
                        tool_args,
                    )
                    if action_result.status.value == "completed":
                        tool_result = action_result.result
                        result_str = json.dumps(tool_result)
                        status = "success"
                    else:
                        logger.warning(
                            "Action %s %s in agent %s: %s",
                            tool_name,
                            action_result.status.value,
                            self.agent_id,
                            action_result.error,
                        )
                        tool_result = {"error": str(action_result.error)}
                        result_str = json.dumps(tool_result)
                        status = "error"
                else:
                    tool_result = {"error": f"Unknown tool: {tool_name}"}
                    result_str = json.dumps(tool_result)
                    status = "error"

                all_action_records.append(
                    {
                        "agent_id": self.agent_id,
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": tool_result,
                        "status": status,
                        "policy": self.action_policy,
                        "approved_by": None,
                        "reversible": getattr(self.agent_definition, "rollback_on_failure", False)
                        if self.agent_definition
                        else False,
                        "rollback_action": getattr(self.agent_definition, "rollback_action", None)
                        if self.agent_definition
                        else None,
                        "workflow_run_id": state.get("workflow_run_id"),
                    }
                )

                # For confirm_on_error: pause on tool execution error
                if self.action_policy == "confirm_on_error" and status == "error":
                    return {
                        **state,
                        "awaiting_error_resolution": True,
                        f"{self.agent_id}_error_details": {
                            "tool": tool_name,
                            "arguments": tool_args,
                            "error": tool_result,
                        },
                        f"{self.agent_id}_action_records": all_action_records,
                        f"{self.agent_id}_output": response.content or "",
                    }

                messages.append(
                    LLMMessage(
                        role="tool",
                        content=result_str,
                        tool_call_id=tool_call_id,
                    )
                )
        else:
            logger.warning(
                "Agent %s hit max tool iterations (%d)",
                self.agent_id,
                self.max_tool_iterations,
            )

        if response is None:
            raise RuntimeError(
                f"Agent '{self.agent_id}' produced no response "
                f"(max_tool_iterations={self.max_tool_iterations})"
            )

        return {
            **state,
            f"{self.agent_id}_output": response.content,
            f"{self.agent_id}_action_records": all_action_records,
            f"{self.agent_id}_usage": (
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
                if response.usage
                else None
            ),
        }

    def _resolve_document_variables(self, prompt: str, state: dict[str, Any]) -> str:
        """Resolve document metadata template variables in a prompt string."""
        from string import Template

        docs = state.get("documents", [])
        doc_vars = {
            "document_count": str(len(docs)),
            "document_names": ", ".join(d.get("name", "") for d in docs if isinstance(d, dict)),
            "document_summary": state.get("document_summary", ""),
        }
        return Template(prompt).safe_substitute(**doc_vars)

    def _build_messages(self, state: dict[str, Any]) -> list[LLMMessage]:
        """Build message list from system prompt and state.

        Args:
            state: Current workflow state

        Returns:
            List of LLM messages
        """
        # Resolve document template variables in system prompt (FR-014)
        system_prompt = self._resolve_document_variables(self.system_prompt, state)

        # Inject skill instructions/metadata into system prompt
        if self.skills:
            skill_section = self._build_skill_section()
            if skill_section:
                system_prompt = system_prompt + "\n\n" + skill_section

        messages = [
            LLMMessage(role="system", content=system_prompt),
        ]

        # Build user message from relevant state
        state_summary = self._summarize_state(state)
        if state_summary:
            messages.append(LLMMessage(role="user", content=state_summary))

        return messages

    def _build_skill_section(self) -> str:
        """Build the skill instructions section for the system prompt.

        Uses progressive disclosure per agentskills.io spec:
        - For llm_only/orchestrator/human_gate: full instructions in <skill> tags.
        - For tool_user/action_executor: metadata-only <available_skills> XML
          (SkillActivationTool handles on-demand loading).
        """
        if not self.skills:
            return ""

        if self.behavior_type in (
            AgentBehaviorType.LLM_ONLY,
            AgentBehaviorType.ORCHESTRATOR,
            AgentBehaviorType.HUMAN_GATE,
        ):
            # Full instructions — no tool loop available for dynamic loading
            parts = []
            for skill in self.skills:
                parts.append(f'<skill name="{skill.name}">')
                parts.append(skill.instructions)
                parts.append("</skill>")
            return "\n\n".join(parts)
        else:
            # Metadata only — SkillActivationTool handles the rest
            lines = ["<available_skills>"]
            for skill in self.skills:
                lines.append("  <skill>")
                lines.append(f"    <name>{skill.name}</name>")
                lines.append(f"    <description>{skill.description}</description>")
                lines.append("  </skill>")
            lines.append("</available_skills>")
            lines.append(
                "\nUse the activate_skill tool to load full instructions "
                "for a skill when the current task matches its description."
            )
            return "\n".join(lines)

    def _summarize_state(self, state: dict[str, Any]) -> str:
        """Create a text summary of relevant state for the LLM.

        Prefers summaries over full outputs when available (summary propagation).
        Falls back to full output if no summary exists (backward compatibility).
        Uses outline for parallel results when available.
        Enforces context budget when configured.

        Args:
            state: Current workflow state

        Returns:
            State summary string, potentially truncated to context budget
        """
        parts = []

        # Include task if present (preprocessing-aware: FR-008, R6)
        if "task_instructions" in state:
            parts.append(f"Task: {state['task_instructions']}")
            if state.get("task_data_summary"):
                parts.append(f"\nData summary:\n{state['task_data_summary']}")
            # Include manifest chunk listing for planners
            manifest = state.get("task_data_manifest")
            if isinstance(manifest, dict) and manifest.get("chunks"):
                chunk_listing = "\n".join(
                    f"  - {c['chunk_id']} ({c['words']} words): {c.get('topic_hint', '')}"
                    for c in manifest["chunks"]
                )
                parts.append(f"\nData chunks:\n{chunk_listing}")
        elif "task" in state:
            parts.append(f"Task: {state['task']}")

        # Include current item for parallel fan-out workers
        if "current_item" in state:
            item = state["current_item"]
            # Chunk dict from task_data fan-out
            if isinstance(item, dict) and "chunk_id" in item and "content" in item:
                parts.append(
                    f"\nAssigned data chunk ({item['chunk_id']}, "
                    f"{item.get('words', '?')} words):\n{item['content']}"
                )
            else:
                parts.append(f"\nCurrent assignment:\n{item}")

            # Provide positional context so the worker knows where it fits
            # within the full set of parallel items.
            if "item_index" in state and "parallel_items" in state:
                items = state["parallel_items"]
                idx = state["item_index"]
                parts.append(f"\nItem {idx + 1} of {len(items)}.")
                listing = "\n".join(f"  {i + 1}. {item}" for i, item in enumerate(items))
                parts.append(f"\nAll items:\n{listing}")

        # Include outlines from parallel fan-out if available
        for key, value in state.items():
            if key.endswith("_outline") and isinstance(value, str):
                agent_name = key.replace("_outline", "")
                parts.append(f"\n--- Outline from {agent_name} ---\n{value}")

        # Include outputs from previous agents -- prefer summary over full output
        # Collect agent names from state keys in insertion order, preserving
        # the chronological sequence agents completed in.
        agent_entries: list[tuple[str, str, str]] = []  # (agent_name, label, content)
        seen_agents: set[str] = set()

        # First pass: identify which agents have summaries
        agents_with_summary: set[str] = set()
        for key in state:
            if key.endswith("_summary") and isinstance(state[key], str):
                agents_with_summary.add(key.replace("_summary", ""))

        # Second pass: collect in state insertion order, preferring summary
        for key, value in state.items():
            if not isinstance(value, str):
                continue
            if key.endswith("_summary"):
                agent_name = key.replace("_summary", "")
                if agent_name not in seen_agents:
                    seen_agents.add(agent_name)
                    agent_entries.append((agent_name, "Summary", value))
            elif key.endswith("_output"):
                agent_name = key.replace("_output", "")
                if agent_name not in seen_agents and agent_name not in agents_with_summary:
                    seen_agents.add(agent_name)
                    agent_entries.append((agent_name, "Output", value))

        # Filter expired entries based on context_ttl
        step_order: list[str] = state.get("_step_order", [])
        context_ttl_map: dict[str, int] = state.get("_context_ttl", {})
        if step_order and context_ttl_map:
            current_pos = len(step_order)  # Current agent is the next position
            filtered_entries: list[tuple[str, str, str]] = []
            for agent_name, label, content in agent_entries:
                ttl = context_ttl_map.get(agent_name)
                if ttl is not None:
                    agent_pos = step_order.index(agent_name) if agent_name in step_order else 0
                    distance = current_pos - agent_pos
                    if distance > ttl:
                        continue  # Expired
                filtered_entries.append((agent_name, label, content))
            agent_entries = filtered_entries

        # Redundancy detection: if consecutive summaries share >60% of
        # trigrams, keep only the more recent one with a back-reference.
        if len(agent_entries) >= 2:
            agent_entries = self._deduplicate_entries(agent_entries)

        # Apply sliding window: only include the N most recent agent entries
        # fully; older ones are collapsed into a single line.
        window = self.context_recency_window
        if window > 0 and len(agent_entries) > window:
            old_entries = agent_entries[:-window]
            recent_entries = agent_entries[-window:]
            old_names = ", ".join(e[0] for e in old_entries)
            parts.append(
                f"\n--- Prior context (summarized) ---\n"
                f"Earlier agents ({old_names}) have completed their work. "
                f"Their outputs informed the recent agents below."
            )
            for agent_name, label, content in recent_entries:
                parts.append(f"\n--- {label} from {agent_name} ---\n{content}")
        else:
            for agent_name, label, content in agent_entries:
                parts.append(f"\n--- {label} from {agent_name} ---\n{content}")

        # Include any explicit input data
        if "input_data" in state:
            parts.append(f"\nInput Data:\n{state['input_data']}")

        # Include document content if present in state
        if "documents" in state and isinstance(state["documents"], list):
            docs_to_show = state["documents"]

            # Apply per-agent scoping if agent_definition is set
            if self.agent_definition is not None:
                from hiveflow.core.documents import DocumentPipeline

                pipeline = DocumentPipeline()
                docs_to_show = pipeline.scope_for_agent(
                    docs_to_show,
                    self.agent_definition,
                    task=state.get("task", ""),
                    state=state,
                )

            doc_parts = []
            for doc in docs_to_show:
                if isinstance(doc, dict):
                    name = doc.get("name", "unknown")
                    chunks = doc.get("chunks", [])
                    if chunks:
                        content_pieces = [
                            c.get("content", "") for c in chunks if isinstance(c, dict)
                        ]
                        if content_pieces:
                            content = "\n".join(content_pieces)
                            doc_parts.append(f"### {name}\n{content}")
                    else:
                        # metadata_only mode: show metadata
                        meta_parts = []
                        for k in ("format", "size_bytes", "chunk_count", "total_tokens_estimate"):
                            if k in doc:
                                meta_parts.append(f"{k}={doc[k]}")
                        doc_parts.append(f"### {name} ({', '.join(meta_parts)})")
            if doc_parts:
                parts.append("\n--- Documents ---\n" + "\n\n".join(doc_parts))

        if "document_summary" in state and isinstance(state["document_summary"], str):
            parts.append(f"\nDocument summary: {state['document_summary']}")

        # Auto-inject unread messages for this agent (collaboration FR-017)
        messages_store = state.get("_messages", {})
        if messages_store:
            direct = messages_store.get(self.agent_id, [])
            broadcast = messages_store.get("_broadcast", [])
            unread = [
                m for m in (direct + broadcast) if isinstance(m, dict) and not m.get("read", False)
            ]
            if unread:
                msg_lines = []
                for m in unread:
                    sender = m.get("from_agent", "unknown")
                    subject = m.get("subject", "")
                    body = m.get("body", "")
                    header = f"From {sender}"
                    if subject:
                        header += f" — {subject}"
                    msg_lines.append(f"  {header}: {body}")
                parts.append("\n--- Messages ---\n" + "\n".join(msg_lines))

        result = "\n".join(parts) if parts else "No context available."

        # Enforce context budget if configured
        if self.context_budget is not None:
            result = self._enforce_context_budget(result)

        return result

    def _enforce_context_budget(self, text: str) -> str:
        """Truncate context text to fit within the word budget.

        Attempts section-aware truncation: keeps the task line and
        fits as many complete sections as possible within budget.
        If a section must be cut, it is truncated at the word level.

        Args:
            text: Assembled context text

        Returns:
            Text trimmed to fit within context_budget words
        """
        budget = self.context_budget  # type: ignore[assignment]
        words = text.split()
        if len(words) <= budget:
            return text

        # Split into sections by the "---" separator
        sections = text.split("\n---")

        # First section (task line) is always kept
        result_parts = [sections[0]]
        current_words = len(sections[0].split())

        for section in sections[1:]:
            section_text = "---" + section  # Restore separator
            section_words = len(section_text.split())
            if current_words + section_words <= budget:
                result_parts.append(section_text)
                current_words += section_words
            else:
                # Fit as much of this section as possible
                remaining = budget - current_words
                if remaining > 50:
                    truncated = " ".join(section_text.split()[:remaining])
                    result_parts.append(truncated + "\n[truncated to fit context budget]")
                break

        return "\n".join(result_parts)

    @staticmethod
    def _trigram_overlap(text_a: str, text_b: str) -> float:
        """Compute the trigram Jaccard overlap between two texts.

        Args:
            text_a: First text
            text_b: Second text

        Returns:
            Overlap ratio between 0.0 and 1.0
        """
        words_a = text_a.lower().split()
        words_b = text_b.lower().split()
        if len(words_a) < 3 or len(words_b) < 3:
            return 0.0
        trigrams_a = {(words_a[i], words_a[i + 1], words_a[i + 2]) for i in range(len(words_a) - 2)}
        trigrams_b = {(words_b[i], words_b[i + 1], words_b[i + 2]) for i in range(len(words_b) - 2)}
        if not trigrams_a or not trigrams_b:
            return 0.0
        intersection = trigrams_a & trigrams_b
        union = trigrams_a | trigrams_b
        return len(intersection) / len(union)

    @staticmethod
    def _deduplicate_entries(
        entries: list[tuple[str, str, str]],
        threshold: float = 0.6,
    ) -> list[tuple[str, str, str]]:
        """Remove highly redundant consecutive agent entries.

        When two entries share >threshold of their trigrams, the older
        entry is replaced with a short back-reference.

        Args:
            entries: List of (agent_name, label, content) tuples
            threshold: Trigram overlap threshold for dedup (0.0-1.0)

        Returns:
            Deduplicated entries list
        """
        if len(entries) < 2:
            return entries

        result: list[tuple[str, str, str]] = [entries[0]]
        for i in range(1, len(entries)):
            prev_name, _, prev_content = result[-1]
            curr_name, curr_label, curr_content = entries[i]
            overlap = Agent._trigram_overlap(prev_content, curr_content)
            if overlap > threshold:
                # Replace the older entry with a back-reference
                result[-1] = (
                    prev_name,
                    "Summary",
                    f"(superseded by {curr_name}'s output below)",
                )
            result.append((curr_name, curr_label, curr_content))
        return result

    async def _apply_context_reduction(
        self,
        messages: list[LLMMessage],
        state: dict[str, Any],
    ) -> list[LLMMessage]:
        """Apply LLM-based context reduction to the user message.

        Uses the ContextReducer to intelligently compress the user message
        content when it exceeds the context budget. Falls back gracefully
        if reduction fails.

        Args:
            messages: Built message list (system + user)
            state: Current workflow state (for task description)

        Returns:
            Messages with potentially reduced user content
        """
        if len(messages) < 2:
            return messages

        user_msg = messages[-1]
        if user_msg.role != "user":
            return messages

        budget = self.context_budget or 0
        if budget <= 0:
            return messages

        word_count = len(user_msg.content.split())
        if word_count <= budget:
            return messages

        try:
            task = state.get("task", "")
            reduced = await self.context_reducer.reduce(
                user_msg.content,
                budget,
                task=task,
            )
            return [
                *messages[:-1],
                LLMMessage(role="user", content=reduced),
            ]
        except Exception as e:
            logger.warning(
                "Context reduction failed for agent %s: %s",
                self.agent_id,
                e,
            )
            return messages

    def _build_config(self) -> LLMConfig:
        """Build LLM config with model from agent settings.

        Returns:
            LLMConfig instance
        """
        # Use llm_config.model if set, otherwise resolve tier/provider from self.model.
        model = self.llm_config.model or self._resolve_model_ref(self.model)
        if ":" in model:
            model = model.split(":", 1)[-1]

        config = LLMConfig(
            model=model,
            temperature=self.llm_config.temperature,
            max_tokens=self.llm_config.max_tokens,
            top_p=self.llm_config.top_p,
            stop=self.llm_config.stop,
            response_format=self.llm_config.response_format,
            extra=self.llm_config.extra,
        )
        return config

    @classmethod
    def from_definition(
        cls,
        definition: Any,
        llm_provider: LLMProvider | None = None,
        tools: list[ToolPlugin] | None = None,
        resolved_model: str | None = None,
        context_budget: int | None = None,
        context_reducer: Any | None = None,
        skills: list[Any] | None = None,
    ) -> "Agent":
        """Create an Agent from an AgentDefinition schema object.

        Args:
            definition: AgentDefinition instance
            llm_provider: LLM provider to use
            tools: Tool plugins available to this agent
            resolved_model: Resolved model string (provider:model)
            context_budget: Max words for context budget enforcement
            context_reducer: Optional ContextReducer instance for LLM-based
                context compression when context_budget is exceeded.
            skills: Optional list of Skill instances for domain expertise.

        Returns:
            Configured Agent instance
        """
        behavior_map = {
            "llm_only": AgentBehaviorType.LLM_ONLY,
            "tool_user": AgentBehaviorType.TOOL_USER,
            "orchestrator": AgentBehaviorType.ORCHESTRATOR,
            "human_gate": AgentBehaviorType.HUMAN_GATE,
            "action_executor": AgentBehaviorType.ACTION_EXECUTOR,
        }

        model = resolved_model or definition.model
        llm_config_kwargs: dict[str, Any] = {
            "model": model.split(":", 1)[-1] if ":" in model else model,
        }
        if getattr(definition, "max_tokens", None) is not None:
            llm_config_kwargs["max_tokens"] = definition.max_tokens
        llm_config = LLMConfig(**llm_config_kwargs)

        action_policy = getattr(definition, "action_policy", None)
        output_type = getattr(definition, "output_type", None)
        context_recency_window = getattr(definition, "context_recency_window", 0)
        # context_budget: prefer explicit kwarg, fall back to schema value
        resolved_budget = (
            context_budget
            if context_budget is not None
            else getattr(definition, "context_budget", None)
        )

        return cls(
            agent_id=definition.id,
            role=definition.role,
            system_prompt=definition.system_prompt,
            behavior_type=behavior_map.get(
                definition.behavior_type.value, AgentBehaviorType.LLM_ONLY
            ),
            tools=tools,
            model=model,
            llm_provider=llm_provider,
            llm_config=llm_config,
            context_budget=resolved_budget,
            agent_definition=definition,
            action_policy=action_policy,
            output_type=output_type,
            context_recency_window=context_recency_window,
            context_reducer=context_reducer,
            skills=skills,
        )
