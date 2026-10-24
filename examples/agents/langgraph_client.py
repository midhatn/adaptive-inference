"""One-node LangGraph example. Requires langgraph and langchain-openai.

Set ADAPTIVE_MODEL to an existing served ID. This script makes one real call
only when executed; importing it does not construct a client or send a request.
"""
import os


def build_graph(model_id: str, *, background: bool = False, generation_options=None,
                gateway_base_url="http://127.0.0.1:18100/v1", api_key_env=None):
    from adaptive_inference.client_routing import gateway_client_options
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, MessagesState, StateGraph

    if not model_id or model_id == "YOUR_EXISTING_MODEL_ID":
        raise ValueError("Supply an existing served model ID")
    options = dict(generation_options or {})
    transport = {"client", "async_client", "http_client", "http_async_client",
                 "openai_api_base", "openai_api_key"}
    if set(options) & (transport | {"model", "base_url", "api_key", "use_responses_api", "max_retries"}):
        raise ValueError("Generation options cannot override the selected client route")
    route = gateway_client_options(base_url=gateway_base_url,
                                   background=background, api_key_env=api_key_env)
    llm = ChatOpenAI(model=model_id, **route,
                     use_responses_api=False, max_retries=0, **options)

    def respond(state: MessagesState):
        return {"messages": [llm.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile()


if __name__ == "__main__":
    graph = build_graph(os.environ["ADAPTIVE_MODEL"])
    result = graph.invoke({"messages": [("user", "Say hello in one sentence.")]})
    print(result["messages"][-1].content)
