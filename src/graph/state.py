from typing import TypedDict


class AgentState(TypedDict, total=False):
    # Identity
    run_id: str
    session_id: str
    dataset_ids: list[str]

    # Input
    question: str
    conversation_history: list[dict]        # [{role, content}] — prior-turn Messages for the session, loaded by load_context (see spec/agent.md)
    profiles: list[dict]                     # DatasetProfile summaries — schema/aggregate ONLY, never raw rows

    # Reasoning control
    reasoning_mode: str                      # "simple" | "iterative" | "planned" — set by classify_query
    plan_steps: list[str]                    # Phase 2+ — set by plan_steps, len <= AGENT_MAX_PLAN_STEPS
    current_step_index: int                  # Phase 2+
    iteration_count: int                     # refine-loop counter, capped at AGENT_MAX_ITERATIONS
    step_count: int                          # total nodes executed this run, capped at AGENT_MAX_TOTAL_STEPS
    step_label: str                          # Phase 3 — human-readable current step for UI progress

    # Pipeline data (populated progressively by nodes)
    generated_code: str
    execution_result: dict                   # ExecutionResult — capped, structured, never raw rows
    accumulated_summaries: list[dict]        # one ExecutionResult per completed step
    check_decision: str                      # Phase 2+ — "accept" | "refine"
    check_feedback: str | None               # Phase 2+

    # Output
    answer_text: str
    key_numbers: list[dict]                  # [{label, value}]
    table_data: dict | None                  # Phase 3
    chart_spec: dict | None                  # Phase 3
    export_path: str | None                  # Phase 3
    export_meta: dict | None                 # Phase 3a — {temp_path,row_count,column_count} from sandbox, promoted in finalize
    follow_up_questions: list[str]           # Phase 3
    anomaly_flags: list[dict]                # Phase 3b — [{type, column, severity, message}]
    cost_records: list[dict]                 # one per LLM call this run

    # Persistence handles set by finalize()
    message_id: str
    query_result_id: str

    # Control
    error: str | None
    status: str                              # "completed" | "failed" | "partial"
