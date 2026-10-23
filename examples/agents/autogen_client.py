"""AutoGen client factory. Supply verified ModelInfo, not inferred capabilities.

Requires autogen-ext[openai]. The example does not execute an agent or a call.
"""


def build_client(model_id: str, model_info: dict, *, background: bool = False, generation_options=None):
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    if not model_id or model_id == "YOUR_EXISTING_MODEL_ID":
        raise ValueError("Supply an existing served model ID")
    required = {"vision", "function_calling", "json_output", "family", "structured_output"}
    if not required <= model_info.keys():
        raise ValueError("Supply the backend's verified AutoGen ModelInfo capabilities")
    options = dict(generation_options or {})
    if set(options) & {"model", "model_info", "api_key", "max_retries", "base_url"}:
        raise ValueError("Generation options cannot override the selected client route")
    suffix = "/background/v1" if background else "/v1"
    return OpenAIChatCompletionClient(
        model=model_id, model_info=dict(model_info), api_key="local", max_retries=0,
        base_url="http://127.0.0.1:18100" + suffix, **options,
    )


# Pass the returned client to an existing AutoGen agent. Close it with
# await client.close() in the application's finally block.
