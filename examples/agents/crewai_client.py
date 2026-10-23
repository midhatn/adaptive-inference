"""CrewAI LLM factory using its documented custom OpenAI-compatible route.

Requires CrewAI with custom_openai support. No task or network call on import.
"""


def build_llm(model_id: str, *, background: bool = False, generation_options=None):
    from crewai import LLM

    if not model_id or model_id == "YOUR_EXISTING_MODEL_ID":
        raise ValueError("Supply an existing served model ID")
    options = dict(generation_options or {})
    if set(options) & {"model", "custom_openai", "base_url", "api_key", "max_retries"}:
        raise ValueError("Generation options cannot override the selected client route")
    suffix = "/background/v1" if background else "/v1"
    return LLM(model=model_id, custom_openai=True,
               base_url="http://127.0.0.1:18100" + suffix,
               api_key="local", max_retries=0, **options)


# Use build_llm(existing_model_id) for the interactive agent; use
# build_llm(existing_model_id, background=True) for a host-designated worker.
# Pass it as llm= to an existing crewai.Agent. No caps or model capabilities
# are guessed here; preserve the caller's verified quality configuration.
