from config.settings import get_settings
from graph.state import AgentState


def after_load_context(state: AgentState) -> str:
    return "handle_error" if state.get("error") else "classify_query"


def after_classify(state: AgentState) -> str:
    if state.get("reasoning_mode") == "planned":
        return "plan_steps"
    return "generate_code"


def after_generate_code(state: AgentState) -> str:
    return "handle_error" if state.get("error") else "execute_code"


def after_execute_code(state: AgentState) -> str:
    reasoning_mode = state.get("reasoning_mode")
    if state.get("error"):
        # Phase 1 (simple path): no retry loop, straight to handle_error.
        # Phase 2+ (iterative/planned): a failed execution is fed to check_result
        # as feedback to react to instead of being immediately fatal.
        if reasoning_mode == "simple":
            return "handle_error"
        return "check_result"
    if reasoning_mode == "simple":
        return "compose_answer"
    return "check_result"


# --------------------------------------------------------------------------- #
# Phase 2+ edges — present for topology completeness; unreachable in Phase 1
# since classify_query is hardcoded to "simple" (see spec/agent.md).
# --------------------------------------------------------------------------- #

def after_check_result(state: AgentState) -> str:
    settings = get_settings()
    iteration_count = int(state.get("iteration_count") or 0)
    step_count = int(state.get("step_count") or 0)
    decision = state.get("check_decision")

    if decision == "refine" and iteration_count < settings.max_iterations and step_count < settings.max_total_steps:
        return "generate_code"

    if decision == "accept" and state.get("reasoning_mode") == "planned":
        plan_steps = state.get("plan_steps") or []
        current_step_index = int(state.get("current_step_index") or 0)
        if current_step_index + 1 < len(plan_steps) and step_count < settings.max_total_steps:
            return "advance_plan"

    return "compose_answer"


def after_advance_plan(state: AgentState) -> str:
    plan_steps = state.get("plan_steps") or []
    current_step_index = int(state.get("current_step_index") or 0)
    if current_step_index < len(plan_steps):
        return "generate_code"
    return "compose_answer"


def after_compose_answer(state: AgentState) -> str:
    return "handle_error" if state.get("error") else "finalize"
