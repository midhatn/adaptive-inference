"""AutoGen client factory. Supply verified ModelInfo, not inferred capabilities.

Requires autogen-ext[openai]. The example does not execute an agent or a call.
"""


def build_client(model_id: str, model_info: dict, *, background: bool = False, generation_options=None,
                gateway_base_url="http://127.0.0.1:18100/v1", api_key_env=None):
    from adaptive_inference.client_routing import gateway_client_options, generation_options_for_route
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    if not model_id or model_id == "YOUR_EXISTING_MODEL_ID":
        raise ValueError("Supply an existing served model ID")
    required = {"vision", "function_calling", "json_output", "family", "structured_output"}
    if not required <= model_info.keys():
        raise ValueError("Supply the backend's verified AutoGen ModelInfo capabilities")
    options = generation_options_for_route(generation_options)
    route = gateway_client_options(base_url=gateway_base_url,
                                   background=background, api_key_env=api_key_env)
    return OpenAIChatCompletionClient(
        model=model_id, model_info=dict(model_info), max_retries=0, **route, **options,
    )


# Pass the returned client to an existing AutoGen agent. Close it with
# await client.close() in the application's finally block.
