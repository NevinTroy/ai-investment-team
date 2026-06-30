"""LangGraph workflow for the investment committee.

Wires analyst agents (market, founder, product, competitive intelligence) in
parallel from the start node. The investment memo agent runs separately in
``committee.main`` after all analysts complete so it can consume consolidated outputs.
"""

from langgraph.graph import END, StateGraph

from src.graph.state import AgentState

from committee.agents.competitive_intelligence import competitive_intelligence_agent
from committee.agents.founder_analyzer import founder_analyzer_agent
from committee.agents.market_analyzer import market_analyzer_agent
from committee.agents.product_analyst import product_analyst_agent

# Registry of committee analyst agents: key -> (node_name, agent_func).
# Add future agents here and they will automatically join the workflow.
COMMITTEE_AGENTS = {
    "market_analyzer": ("market_analyzer_agent", market_analyzer_agent),
    "founder_analyzer": ("founder_analyzer_agent", founder_analyzer_agent),
    "product_analyst": ("product_analyst_agent", product_analyst_agent),
    "competitive_intelligence": ("competitive_intelligence_agent", competitive_intelligence_agent),
}


def _start(state: AgentState):
    """Entry node; passes state through to the analyst agents."""
    return state


def create_workflow(selected_agents: list[str] | None = None) -> StateGraph:
    """Build the committee workflow.

    Args:
        selected_agents: Optional subset of agent keys to run. Defaults to all.
    """
    if selected_agents is None:
        selected_agents = list(COMMITTEE_AGENTS.keys())

    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", _start)

    for key in selected_agents:
        node_name, node_func = COMMITTEE_AGENTS[key]
        workflow.add_node(node_name, node_func)
        workflow.add_edge("start_node", node_name)
        workflow.add_edge(node_name, END)

    workflow.set_entry_point("start_node")
    return workflow


def build_committee(selected_agents: list[str] | None = None):
    """Compile and return a runnable committee graph."""
    return create_workflow(selected_agents).compile()
