from collections.abc import Callable

from graph.state import AnalysisState


def route_after(next_node: str) -> Callable[[AnalysisState], str]:
    """Return a router that goes to ``handle_error`` on error, else ``next_node``."""

    def _route(state: AnalysisState) -> str:
        return "handle_error" if state.get("error") else next_node

    return _route
