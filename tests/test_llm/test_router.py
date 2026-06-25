import os
from unittest import mock

from onep.llm.router import resolve_model, get_api_key, get_api_base, TaskComplexity


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


@mock.patch("onep.llm.router.load_config")
def test_get_api_key_from_env(mock_load):
    """Env var takes priority over config file."""
    from onep.config import Config, LLMConfig
    mock_load.return_value = Config(
        llm=LLMConfig(models={"deepseek": {"api_key": "from-config"}})
    )
    with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "from-env"}):
        assert get_api_key("deepseek") == "from-env"


@mock.patch("onep.llm.router.load_config")
def test_get_api_key_fallback_to_config(mock_load):
    """Config file used when no env var."""
    from onep.config import Config, LLMConfig
    mock_load.return_value = Config(
        llm=LLMConfig(models={"deepseek": {"api_key": "from-config"}})
    )
    with mock.patch.dict(os.environ, clear=True):
        assert get_api_key("deepseek") == "from-config"


@mock.patch("onep.llm.router.load_config")
def test_get_api_base_from_env(mock_load):
    from onep.config import Config, LLMConfig
    mock_load.return_value = Config(
        llm=LLMConfig(models={"openai": {"api_base": "https://config.openai.com"}})
    )
    with mock.patch.dict(os.environ, {"OPENAI_API_BASE": "https://env.openai.com"}):
        assert get_api_base("openai") == "https://env.openai.com"
