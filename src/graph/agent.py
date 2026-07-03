"""Graph assembly per spec/agent.md.

**Topology choice (documented per code-generator instructions):** all Phase-2+
nodes (`plan_steps`, `check_result`, `advance_plan`) ARE registered and wired
here, matching spec/agent.md's Graph Assembly pseudocode verbatim, even though
they are unreachable in Phase 1 (classify_query is hardcoded to "simple", so
`after_classify` never routes to `plan_steps` and `after_execute_code` never
routes to `check_result` on the simple path). This keeps the compiled graph's
shape identical to the target architecture from day one, so Phase 2 only has
to swap node *bodies* (classify_query, plan_steps, check_result) rather than
also having to change graph wiring.
"""
from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import (
    load_context, classify_query, plan_steps, generate_code, execute_code,
    check_result, advance_plan, compose_answer, handle_error, finalize,
)
from graph.edges import (
    after_load_context, after_classify, after_generate_code,
    after_execute_code, after_check_result, after_advance_plan, after_compose_answer,
)


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    for name, fn in [
        ("load_context", load_context), ("classify_query", classify_query),
        ("plan_steps", plan_steps), ("generate_code", generate_code),
        ("execute_code", execute_code), ("check_result", check_result),
        ("advance_plan", advance_plan), ("compose_answer", compose_answer),
        ("handle_error", handle_error), ("finalize", finalize),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("load_context")
    g.add_conditional_edges("load_context", after_load_context,
        {"classify_query": "classify_query", "handle_error": "handle_error"})
    g.add_conditional_edges("classify_query", after_classify,
        {"plan_steps": "plan_steps", "generate_code": "generate_code"})
    g.add_edge("plan_steps", "generate_code")
    g.add_conditional_edges("generate_code", after_generate_code,
        {"execute_code": "execute_code", "handle_error": "handle_error"})
    g.add_conditional_edges("execute_code", after_execute_code,
        {"compose_answer": "compose_answer", "check_result": "check_result", "handle_error": "handle_error"})
    g.add_conditional_edges("check_result", after_check_result,
        {"generate_code": "generate_code", "advance_plan": "advance_plan", "compose_answer": "compose_answer"})
    g.add_conditional_edges("advance_plan", after_advance_plan,
        {"generate_code": "generate_code", "compose_answer": "compose_answer"})
    g.add_conditional_edges("compose_answer", after_compose_answer,
        {"finalize": "finalize", "handle_error": "handle_error"})
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)
    return g.compile()


agentic_ai = _build_graph()
