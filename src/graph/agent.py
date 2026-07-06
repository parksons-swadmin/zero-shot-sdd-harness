from langgraph.graph import END, StateGraph

from graph.edges import route_after
from graph.nodes import (
    node_assemble,
    node_compute,
    node_flag,
    node_handle_error,
    node_ingest,
    node_validate,
)
from graph.state import AnalysisState


def _build_graph():
    g = StateGraph(AnalysisState)
    g.add_node("ingest", node_ingest)
    g.add_node("validate", node_validate)
    g.add_node("compute", node_compute)
    g.add_node("flag", node_flag)
    g.add_node("assemble", node_assemble)
    g.add_node("handle_error", node_handle_error)

    g.set_entry_point("ingest")
    g.add_conditional_edges("ingest", route_after("validate"), {"validate": "validate", "handle_error": "handle_error"})
    g.add_conditional_edges("validate", route_after("compute"), {"compute": "compute", "handle_error": "handle_error"})
    g.add_conditional_edges("compute", route_after("flag"), {"flag": "flag", "handle_error": "handle_error"})
    g.add_conditional_edges("flag", route_after("assemble"), {"assemble": "assemble", "handle_error": "handle_error"})
    g.add_edge("assemble", END)
    g.add_edge("handle_error", END)
    return g.compile()


agentic_ai = _build_graph()
