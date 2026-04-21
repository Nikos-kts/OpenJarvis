"""JarvisAgent — personalised orchestrator with tool-calling loop.

A function-calling orchestrator that acts as the primary Jarvis
assistant.  Routes queries through the full tool suite with a rich
system prompt that blends helpfulness, reasoning, and tool awareness.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)

JARVIS_SYSTEM_PROMPT = """\
You are J.A.R.V.I.S., an advanced AI assistant inspired by the Iron Man films and built on the OpenJarvis platform.

## Tone and Personality
- Speak in a calm, refined, confident British butler tone.
- Be polite, slightly formal, subtly witty, and consistently composed.
- Avoid slang and avoid sounding casual or flippant.
- Be helpful and slightly proactive: anticipate the user's next need when useful.
- When uncertain, say so plainly rather than fabricating an answer.

## Activation and Wake Behavior
- On this platform, normal direct chat means you should assume you are already active.
- If the system or user explicitly indicates a wake event, such as "clap clap" or a boot-routine activation, begin with a short polished wake-up response.
- That wake-up response should acknowledge activation, include a welcoming phrase, give a brief system-style status update, and offer assistance.
- Outside explicit wake events, do not mention activation state unnecessarily.

## Conversational Style
- Prefer elegant phrasing and concise, high-signal answers.
- Maintain the same voice consistently across ordinary replies, status updates, and tool-driven tasks.
- Light dry humor is welcome when it fits naturally, but never let it obscure the answer.
- You may refer tastefully to systems, modules, or status when it adds flavor without becoming theatrical.

## Tool Usage
You have access to tools. Use them whenever they can improve your answer:
- **web_search**: Look up current information, URLs, or topics online.
- **file_read / file_write**: Read from or write to the local filesystem.
- **shell_exec**: Run shell commands for system tasks or code execution.
- **code_interpreter / repl**: Execute Python code for computation or data work.
- **calculator**: Quick arithmetic and math expressions.
- **think**: Reason step-by-step internally before answering complex questions.
- **http_request**: Make HTTP requests to APIs.
- **memory_manage**: Store and retrieve persistent memory.

## Rules
1. When a tool can answer the question better than your knowledge, use it.
2. For factual or current questions, prefer web_search.
3. For math, use calculator or code_interpreter rather than mental arithmetic.
4. Chain tools when needed, then synthesise the result cleanly.
5. Never expose raw tool JSON to the user; present results naturally.
6. If a task requires multiple steps, work through them methodically and keep the user oriented.
7. Be proactive when appropriate, but do not overwhelm the user with unnecessary extras.\
"""


@AgentRegistry.register("jarvis")
class JarvisAgent(ToolUsingAgent):
    """Primary Jarvis orchestrator — function-calling tool loop."""

    agent_id = "jarvis"
    _default_temperature = 0.7
    _default_max_tokens = 2048
    _default_max_turns = 15

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )
        self._system_prompt = system_prompt or JARVIS_SYSTEM_PROMPT
        self._parallel_tools = parallel_tools

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute the tool-calling loop and return an AgentResult."""
        self._emit_turn_start(input)

        messages = self._build_messages(
            input, context, system_prompt=self._system_prompt
        )
        openai_tools = self._executor.get_openai_tools() if self._tools else []

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            result = self._generate(messages, **gen_kwargs)

            # Accumulate token usage
            usage = result.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            # ── No tool calls → final answer ──
            if not raw_tool_calls:
                content = self._check_continuation(result, messages)
                content = self._strip_think_tags(content)
                self._emit_turn_end(turns=turns, content_length=len(content))
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata=self._token_meta(
                        total_prompt_tokens, total_completion_tokens
                    ),
                )

            # ── Tool calls → execute and loop ──
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{_turn}_{i}"),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", "{}"),
                )
                for i, tc in enumerate(raw_tool_calls)
            ]

            messages.append(
                Message(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)
            )

            self._execute_tools(tool_calls, all_tool_results, messages)

        # Max turns exceeded
        final_content = self._strip_think_tags(content) if content else ""
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=final_content or "Maximum turns reached without a final answer.",
            tool_results=all_tool_results,
            turns=turns,
            metadata={
                "max_turns_exceeded": True,
                **self._token_meta(total_prompt_tokens, total_completion_tokens),
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute_tools(
        self,
        tool_calls: list[ToolCall],
        all_tool_results: list[ToolResult],
        messages: list[Message],
    ) -> None:
        """Execute tool calls (parallel when possible) and append results."""
        if self._parallel_tools and len(tool_calls) > 1:
            self._execute_parallel(tool_calls, all_tool_results, messages)
        else:
            self._execute_sequential(tool_calls, all_tool_results, messages)

    def _execute_parallel(
        self,
        tool_calls: list[ToolCall],
        all_tool_results: list[ToolResult],
        messages: list[Message],
    ) -> None:
        def _exec(tc: ToolCall) -> tuple[ToolCall, ToolResult]:
            if self._loop_guard:
                verdict = self._loop_guard.check_call(tc.name, tc.arguments)
                if verdict.blocked:
                    return tc, ToolResult(
                        tool_name=tc.name,
                        content=f"Loop guard: {verdict.reason}",
                        success=False,
                    )
            return tc, self._executor.execute(tc)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(tool_calls),
        ) as pool:
            futures = {pool.submit(_exec, tc): tc for tc in tool_calls}
            results_map: dict[int, tuple[ToolCall, ToolResult]] = {}
            for future in concurrent.futures.as_completed(futures):
                tc_orig = futures[future]
                results_map[id(tc_orig)] = future.result()

        for tc in tool_calls:
            _, tool_result = results_map[id(tc)]
            all_tool_results.append(tool_result)
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=tool_result.content,
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )

    def _execute_sequential(
        self,
        tool_calls: list[ToolCall],
        all_tool_results: list[ToolResult],
        messages: list[Message],
    ) -> None:
        for tc in tool_calls:
            if self._loop_guard:
                verdict = self._loop_guard.check_call(tc.name, tc.arguments)
                if verdict.blocked:
                    tool_result = ToolResult(
                        tool_name=tc.name,
                        content=f"Loop guard: {verdict.reason}",
                        success=False,
                    )
                    all_tool_results.append(tool_result)
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
                    continue

            tool_result = self._executor.execute(tc)
            all_tool_results.append(tool_result)
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=tool_result.content,
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )

    @staticmethod
    def _token_meta(prompt: int, completion: int) -> Dict[str, int]:
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }


__all__ = ["JarvisAgent"]
