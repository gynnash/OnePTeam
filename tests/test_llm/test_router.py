from unittest import mock

from onep.llm.router import resolve_model, TaskComplexity


@mock.patch("onep.llm.router.load_config")
def test_complex_stage_gets_gpt(mock_load):
    from onep.config import Config, LLMConfig
    mock_load.return_value = Config(
        llm=LLMConfig(
            default_model="deepseek/deepseek-chat",
            complex_model="openai/gpt-5.5",
            complex_provider="openai",
            default_provider="deepseek",
        )
    )
    model, provider = resolve_model("architect")
    assert model == "openai/gpt-5.5"
    assert provider == "openai"


@mock.patch("onep.llm.router.load_config")
def test_standard_stage_gets_deepseek(mock_load):
    from onep.config import Config, LLMConfig
    mock_load.return_value = Config(
        llm=LLMConfig(
            default_model="deepseek/deepseek-chat",
            complex_model="openai/gpt-5.5",
            complex_provider="openai",
            default_provider="deepseek",
        )
    )
    model, provider = resolve_model("developer")
    assert model == "deepseek/deepseek-chat"
    assert provider == "deepseek"
