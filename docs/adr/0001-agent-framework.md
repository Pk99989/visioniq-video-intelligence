# ADR 0001 — Agent framework: hand-rolled dispatcher, not LangGraph

Date: 2026-11-06
Status: Accepted

## Context

The v1.0.0 master prompt asks for a "LangGraph-based agent" with 8 tools.
The pre-upgrade agent was a hand-rolled intent dispatcher in
`backend/app/services/agent.py` (keyword routing, single tool per
question, state in the conversations/messages tables). Phase 5 adds
multi-step planning (up to 3 tools per question) and 3 more tools.

## Decision

Keep the hand-rolled dispatcher, extended with a deterministic
multi-step planner (`_plan` + `_answer_single`), and do NOT adopt
LangGraph.

## Reasons

1. **The tools are deterministic functions, not LLM calls.** Routing
   is a keyword match over the question; execution is a function call
   with typed arguments. LangGraph's value is orchestrating LLM
   tool-calling loops and conditional LLM edges — neither exists here.
2. **State already persists.** Conversational memory lives in the
   conversations/messages tables and is passed back as prior turns.
   LangGraph's checkpointing would duplicate that storage.
3. **Determinism is a feature, not a limitation.** The same question
   must return the same tool plan every time (it is tested as such in
   `tests/test_agent.py`). An LLM planner could route the same
   question differently on different runs and could route a question
   to a tool that leaks another user's data; the keyword planner
   cannot.
4. **Dependency risk.** LangGraph would add a fast-moving dependency
   (plus langchain-core) to a codebase that otherwise has a small,
   pinned dependency set, for a graph that would have 3 nodes
   (plan → execute → synthesise) — the same shape the planner
   already implements in ~40 lines.
5. **The multi-step behaviour is implemented and tested directly:**
   `_plan` returns up to 3 tools in a fixed order, `answer_question`
   runs them and merges validated citations.

## Consequences

- No `langgraph` / `langchain` dependency in requirements.txt.
- The agent's tool registry (`agent.TOOLS`, 8 tools) is the single
  source of truth, shared by the HTTP chat endpoint and the MCP
  server (`mcp_server/server.py` delegates to `agent.run_tool`).
- If a future tool needs free-form LLM planning (e.g. an LLM that
  decides which tools to call and in what order, or a tool that
  calls other tools based on intermediate results), revisit this
  ADR — that is the point at which a graph framework earns its keep.

## Alternatives considered

- **LangGraph with the same 8 tools:** rejected for the reasons
  above; would have been adopted if the planner needed LLM
  judgement (it does not — every routing decision is a keyword).
- **LangChain agents:** rejected — same reasons, plus LangChain's
  agent loop calls the LLM per step, which would put an LLM call
  (and its cost/latency/failure modes) on the critical path of
  every question, including ones the deterministic planner answers
  from the database alone.
