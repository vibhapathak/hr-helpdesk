"""LangGraph helpdesk agent.

    START -> input_guard --(blocked / out of scope)--> END
                 |
                 v
              agent  <-->  tools   (search_policies [RAG], MCP Postgres tools, create_ticket)
                 |
                 v
            output_guard -> END     (citations footer, PII redaction, prompt-leak check)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .config import Settings, get_settings
from .guardrails import (
    CANARY, REFUSAL_INJECTION, REFUSAL_LEAK, REFUSAL_OUT_OF_SCOPE, GuardDecision,
    build_guard_messages, detect_injection_heuristic, leaks_system_prompt, redact_pii,
    sanitize_tool_output,
)
from .prompts import AGENT_SYSTEM_PROMPT
from .rag import PolicyStore, load_policy_chunks, make_embedder
from .tickets import create_ticket as create_ticket_impl

log = logging.getLogger(__name__)
MAX_INPUT_CHARS = 2000
HISTORY_TURNS = 4
_RETRY_HINT = re.compile(r"retry(?:Delay)?\W+(?:in\s+)?(\d+(?:\.\d+)?)s", re.I)


class LLMUnavailableError(RuntimeError):
    """Raised when the model provider keeps rate-limiting us or the daily quota is used up."""


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return "RateLimit" in text or "429" in text or "RESOURCE_EXHAUSTED" in text


async def invoke_with_retry(runnable: Any, messages: Any, max_retries: int) -> Any:
    """ainvoke with back-off on rate limits. Uses the provider's 'retry in Ns' hint when present.
    A daily-quota error is not retried (waiting seconds won't help)."""
    for attempt in range(max_retries + 1):
        try:
            return await runnable.ainvoke(messages)
        except Exception as exc:
            if not _is_rate_limit(exc):
                raise
            msg = str(exc)
            if re.search(r"per[_ ]?day|PerDay", msg, re.I):
                raise LLMUnavailableError("Daily model quota exhausted (resets at midnight Pacific time).") from exc
            if attempt == max_retries:
                raise LLMUnavailableError("Model provider is rate-limiting requests.") from exc
            hint = _RETRY_HINT.search(msg)
            delay = float(hint.group(1)) + 1 if hint else min(60.0, 8.0 * 2 ** attempt)
            log.warning("Rate limited (attempt %d/%d), sleeping %.0fs", attempt + 1, max_retries, delay)
            await asyncio.sleep(delay)


# ----------------------------------------------------------------------------- local tool schemas
# Executed inside `tools_node` (they need per-turn state: citation numbering, ticket de-dup).
@tool
def search_policies(query: str) -> str:
    """Semantic search over Acme Corp's HR and IT policy documents (leave, holidays, parental leave,
    hybrid/remote work, allowances, passwords, MFA, VPN, phishing, software, data handling, laptops,
    equipment, refresh cycle, repairs, lost devices). Returns numbered excerpts to cite as [n]."""
    raise NotImplementedError  # handled by the graph


@tool
def create_ticket(summary: str, details: str, category: Literal["hr", "it"],
                  priority: Literal["low", "medium", "high"] = "medium",
                  requester_employee_id: str | None = None) -> str:
    """Escalate an in-scope HR/IT question that the policies and database cannot answer to the
    human helpdesk team. Call at most once per question. Returns the ticket ID."""
    raise NotImplementedError  # handled by the graph


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    status: str
    guard: dict[str, Any]
    sources: list[dict[str, Any]]
    cited_sources: list[dict[str, Any]]
    tickets: list[dict[str, Any]]
    tools_used: list[str]
    redactions: dict[str, int]
    steps: int
    answer: str


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _history_window(messages: list[AnyMessage], turns: int = HISTORY_TURNS) -> list[AnyMessage]:
    """Last `turns` user turns, always starting at a HumanMessage (never orphan tool messages)."""
    human_idx = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    start = human_idx[-turns] if len(human_idx) >= turns else 0
    return messages[start:]


class HelpdeskAgent:
    def __init__(self, settings: Settings, llm: BaseChatModel, guard_llm: Any, store: PolicyStore,
                 mcp_tools: list[BaseTool]):
        self.settings = settings
        self.store = store
        self.mcp_tools = {t.name: t for t in mcp_tools}
        self.llm = llm
        self.llm_with_tools = llm.bind_tools([search_policies, create_ticket, *mcp_tools])
        self.guard_llm = guard_llm
        self.graph = self._build_graph()

    # ------------------------------------------------------------------ construction
    @classmethod
    async def create(cls, settings: Settings | None = None, *, llm: BaseChatModel | None = None,
                     guard_llm: Any = None, store: PolicyStore | None = None,
                     mcp_tools: list[BaseTool] | None = None) -> "HelpdeskAgent":
        settings = settings or get_settings()
        limiters: dict[str, InMemoryRateLimiter] = {}  # one per model: free-tier quotas are per model

        def model_kwargs(name: str) -> dict:
            if settings.llm_requests_per_minute <= 0:
                return {}
            if name not in limiters:
                limiters[name] = InMemoryRateLimiter(
                    requests_per_second=settings.llm_requests_per_minute / 60, max_bucket_size=1)
            return {"rate_limiter": limiters[name]}

        if llm is None:
            llm = init_chat_model(settings.llm_model, temperature=settings.llm_temperature,
                                  **model_kwargs(settings.llm_model))
        if guard_llm is None and settings.use_llm_guard:
            guard_llm = init_chat_model(settings.guard_model_name, temperature=0,
                                        **model_kwargs(settings.guard_model_name)).with_structured_output(GuardDecision)
        if store is None:
            store = await asyncio.to_thread(cls._build_store, settings)
        if mcp_tools is None:
            mcp_tools = await cls._load_mcp_tools(settings)
        return cls(settings, llm, guard_llm, store, mcp_tools)

    @staticmethod
    def _build_store(settings: Settings) -> PolicyStore:
        embedder = make_embedder(settings.embedding_backend, settings.embedding_model, settings.embedding_cache_dir)
        chunks = load_policy_chunks(settings.policies_dir)
        for attempt in range(30):
            try:
                store = PolicyStore(settings.qdrant_url, settings.qdrant_collection, embedder)
                store.ingest(chunks)
                return store
            except Exception as exc:  # qdrant container may still be starting
                log.warning("Qdrant not ready (%s), retry %d/30", exc, attempt + 1)
                time.sleep(2)
        raise RuntimeError("Could not connect to Qdrant")

    @staticmethod
    async def _load_mcp_tools(settings: Settings) -> list[BaseTool]:
        client = MultiServerMCPClient(
            {"hr_it_db": {"url": settings.mcp_server_url, "transport": "streamable_http"}})
        for attempt in range(30):
            try:
                tools = await client.get_tools()
                log.info("Loaded MCP tools: %s", [t.name for t in tools])
                return tools
            except Exception as exc:
                log.warning("MCP server not ready (%s), retry %d/30", type(exc).__name__, attempt + 1)
                await asyncio.sleep(2)
        raise RuntimeError("Could not connect to the MCP server")

    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("input_guard", self.input_guard)
        g.add_node("agent", self.agent_node)
        g.add_node("tools", self.tools_node)
        g.add_node("output_guard", self.output_guard)
        g.add_edge(START, "input_guard")
        g.add_conditional_edges("input_guard", lambda s: END if s.get("status") else "agent")
        g.add_conditional_edges(
            "agent", lambda s: "tools" if getattr(s["messages"][-1], "tool_calls", None) else "output_guard")
        g.add_edge("tools", "agent")
        g.add_edge("output_guard", END)
        return g.compile(checkpointer=MemorySaver())

    # ------------------------------------------------------------------ nodes
    async def input_guard(self, state: AgentState) -> dict:
        text = (state.get("user_input") or "").strip()
        fresh = {"sources": [], "cited_sources": [], "tickets": [], "tools_used": [], "redactions": {},
                 "steps": 0, "status": "", "answer": "", "guard": {}}

        if not text:
            return {**fresh, "status": "out_of_scope", "answer": REFUSAL_OUT_OF_SCOPE}
        if len(text) > MAX_INPUT_CHARS:
            return {**fresh, "status": "blocked_injection", "answer": REFUSAL_INJECTION,
                    "guard": {"layer": "length", "reason": f"input longer than {MAX_INPUT_CHARS} chars"}}

        verdict = detect_injection_heuristic(text)
        if verdict.is_injection:
            log.warning("Heuristic injection block: %s", verdict.matched_rules)
            return {**fresh, "status": "blocked_injection", "answer": REFUSAL_INJECTION,
                    "guard": {"layer": "heuristic", "rules": verdict.matched_rules}}

        guard: dict[str, Any] = {"layer": "passed"}
        if self.guard_llm is not None:
            try:
                decision: GuardDecision = await invoke_with_retry(
                    self.guard_llm, build_guard_messages(text, self._recent_context(state)),
                    self.settings.llm_max_retries)
            except Exception as exc:  # fail closed: no unchecked input reaches the agent
                log.exception("Guard LLM failed")
                return {**fresh, "status": "error", "guard": {"layer": "llm", "error": str(exc)},
                        "answer": "Sorry, I couldn't process that request right now. Please try again."}
            guard = {"layer": "llm", "category": decision.category, "reason": decision.reason}
            if decision.is_prompt_injection:
                return {**fresh, "status": "blocked_injection", "answer": REFUSAL_INJECTION, "guard": guard}
            if decision.category == "out_of_scope":
                return {**fresh, "status": "out_of_scope", "answer": REFUSAL_OUT_OF_SCOPE, "guard": guard}

        return {**fresh, "guard": guard, "messages": [HumanMessage(content=text)]}

    @staticmethod
    def _recent_context(state: AgentState) -> str:
        lines = []
        for m in state.get("messages", [])[-6:]:
            if isinstance(m, HumanMessage):
                lines.append("user: " + content_to_text(m.content)[:300])
            elif isinstance(m, AIMessage) and not m.tool_calls:
                lines.append("assistant: " + content_to_text(m.content)[:300])
        return "\n".join(lines[-4:])

    async def agent_node(self, state: AgentState) -> dict:
        steps = state.get("steps", 0)
        system = SystemMessage(AGENT_SYSTEM_PROMPT.format(canary=CANARY, today=dt.date.today().isoformat()))
        history = _history_window(state["messages"])
        if steps >= self.settings.max_agent_steps - 1:  # last step: force a final answer, no more tools
            note = SystemMessage("Tool budget exhausted. Answer now using only the information gathered.")
            response = await invoke_with_retry(self.llm, [system, *history, note], self.settings.llm_max_retries)
        else:
            response = await invoke_with_retry(self.llm_with_tools, [system, *history], self.settings.llm_max_retries)
        return {"messages": [response], "steps": steps + 1}

    async def tools_node(self, state: AgentState) -> dict:
        call_msg: AIMessage = state["messages"][-1]
        sources = list(state.get("sources", []))
        tickets = list(state.get("tickets", []))
        tools_used = list(state.get("tools_used", []))
        results: list[ToolMessage] = []

        for call in call_msg.tool_calls:
            name, args = call["name"], call.get("args", {}) or {}
            tools_used.append(name)
            try:
                if name == "search_policies":
                    content = await self._run_search(str(args.get("query", "")), sources)
                elif name == "create_ticket":
                    content = await self._run_create_ticket(args, state, tickets)
                elif name in self.mcp_tools:
                    msg = await self.mcp_tools[name].ainvoke(
                        {"name": name, "args": args, "id": call["id"], "type": "tool_call"})
                    content = content_to_text(getattr(msg, "content", msg))
                else:
                    content = f"Unknown tool: {name}"
            except Exception as exc:
                log.exception("Tool %s failed", name)
                content = f"Tool error: {exc}"
            content, flagged = sanitize_tool_output(content)
            if flagged:
                log.warning("Indirect injection withheld from tool %s", name)
            results.append(ToolMessage(content=content, tool_call_id=call["id"], name=name))

        return {"messages": results, "sources": sources, "tickets": tickets, "tools_used": tools_used}

    async def _run_search(self, query: str, sources: list[dict]) -> str:
        hits = await asyncio.to_thread(self.store.search, query, self.settings.rag_top_k, self.settings.rag_min_score)
        if not hits:
            return "NO_RELEVANT_POLICY_FOUND: no policy excerpt matched this query."
        blocks = []
        for h in hits:
            entry = next((s for s in sources if s["citation"] == h.chunk.citation), None)
            if entry is None:
                entry = {"n": len(sources) + 1, "citation": h.chunk.citation, "doc_file": h.chunk.doc_file,
                         "section": h.chunk.section, "score": round(h.score, 3)}
                sources.append(entry)
            blocks.append(f"[{entry['n']}] {h.chunk.citation} (relevance {h.score:.2f})\n{h.chunk.text}")
        return "\n\n".join(blocks)

    async def _run_create_ticket(self, args: dict, state: AgentState, tickets: list[dict]) -> str:
        if tickets:
            return json.dumps({"ticket_id": tickets[0]["ticket_id"], "note": "already created for this question"})
        ticket = await asyncio.to_thread(
            create_ticket_impl, self.settings,
            summary=str(args.get("summary", "Helpdesk escalation"))[:200],
            details=str(args.get("details", ""))[:2000],
            category=args.get("category", "hr") if args.get("category") in ("hr", "it") else "hr",
            priority=args.get("priority", "medium") if args.get("priority") in ("low", "medium", "high") else "medium",
            requester_employee_id=args.get("requester_employee_id"),
            user_question=state.get("user_input", ""),
        )
        tickets.append(ticket)
        return json.dumps({"ticket_id": ticket["ticket_id"], "status": "open", "backend": ticket["backend"]})

    async def output_guard(self, state: AgentState) -> dict:
        last = state["messages"][-1]
        text = content_to_text(last.content).strip()
        status = "ticket_created" if state.get("tickets") else "answered"
        cited: list[dict] = []

        if leaks_system_prompt(text):
            text, status = REFUSAL_LEAK, "leak_blocked"
        else:
            sources = state.get("sources", [])
            text = re.sub(r"【(\d{1,2})】", r"[\1]", text)       # some models cite with CJK brackets
            numbers = {int(n) for n in re.findall(r"\[(\d{1,2})\]", text)}
            cited = [s for s in sources if s["n"] in numbers]
            if not cited and sources and not state.get("tickets"):
                cited = sorted(sources, key=lambda s: -s["score"])[:1]  # uncited answer: show best match
            if cited:
                text = text.rstrip() + "\n\nSources:\n" + "\n".join(f"[{s['n']}] {s['citation']}" for s in cited)
            for t in state.get("tickets", []):
                if t["ticket_id"] not in text:
                    text += f"\n\nTicket created: {t['ticket_id']}"

        red = redact_pii(text, self.settings.allowlisted_emails)
        return {"messages": [AIMessage(content=red.text, id=last.id)], "answer": red.text, "status": status,
                "redactions": red.counts, "cited_sources": cited}

    # ------------------------------------------------------------------ public API
    async def ask(self, message: str, session_id: str = "default") -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            state = await self.graph.ainvoke({"user_input": message}, {"configurable": {"thread_id": session_id}})
        except LLMUnavailableError as exc:
            log.error("LLM unavailable: %s", exc)
            return {"answer": f"Sorry, the assistant is temporarily unavailable ({exc}) Please try again shortly.",
                    "status": "error", "guard": {}, "sources": [], "tickets": [], "tools_used": [],
                    "redactions": {}, "latency_ms": int((time.perf_counter() - t0) * 1000)}
        return {
            "answer": state.get("answer", ""),
            "status": state.get("status", ""),
            "guard": state.get("guard", {}),
            "sources": state.get("cited_sources", []),
            "tickets": [{"ticket_id": t["ticket_id"], "backend": t["backend"]} for t in state.get("tickets", [])],
            "tools_used": state.get("tools_used", []),
            "redactions": state.get("redactions", {}),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }
