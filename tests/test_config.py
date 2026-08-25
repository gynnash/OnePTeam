from unittest import mock

import yaml

from onep.config import (
    Config,
    ExecutionConfig,
    LLMConfig,
    ProjectConfig,
    load_config,
    save_config,
)


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.default_model == "deepseek/deepseek-chat"
    assert cfg.complex_model == "openai/gpt-5.5"


def test_config_default_values():
    cfg = Config()
    assert cfg.llm.default_model == "deepseek/deepseek-chat"
    assert cfg.execution.codex_model == "gpt-5.6-terra"
    assert cfg.execution.codex_approval_policy == "on-request"


def test_load_config_creates_default(tmp_path):
    with mock.patch("onep.config._config_dir", return_value=tmp_path):
        config = load_config()
    assert config.llm.default_model == "deepseek/deepseek-chat"
    assert (tmp_path / "config.yaml").exists()


def test_load_config_reads_existing(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.dump({
            "llm": {"default_model": "openai/gpt-4o"},
            "pipeline": {"max_retries": 5},
        })
    )
    with mock.patch("onep.config._config_dir", return_value=tmp_path):
        config = load_config()
    assert config.llm.default_model == "openai/gpt-4o"
    assert not hasattr(config, "pipeline")


def test_save_config_persists(tmp_path):
    with mock.patch("onep.config._config_dir", return_value=tmp_path):
        config = Config()
        save_config(config)

    reloaded = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert set(reloaded) == {"execution", "llm", "project"}


def test_save_load_round_trip(tmp_path):
    with mock.patch("onep.config._config_dir", return_value=tmp_path):
        original = Config(
            llm=LLMConfig(
                default_model="custom-model",
                default_provider="custom-provider",
                complex_model="custom-complex",
                complex_provider="custom-complex-provider",
                models={
                    "custom": {
                        "api_key": "sk-test",
                        "api_base": "https://custom.test/v1",
                    }
                },
            ),
            project=ProjectConfig(root_dir="/tmp/test-project"),
            execution=ExecutionConfig(
                codex_model="gpt-test",
                codex_auth_mode="existing",
                codex_approval_policy="on-request",
            ),
        )
        save_config(original)
        reloaded = load_config()

    assert reloaded.llm.default_model == original.llm.default_model
    assert reloaded.llm.default_provider == original.llm.default_provider
    assert reloaded.llm.complex_model == original.llm.complex_model
    assert reloaded.llm.complex_provider == original.llm.complex_provider
    assert reloaded.llm.models == original.llm.models
    assert reloaded.project.root_dir == original.project.root_dir
    assert reloaded.execution == original.execution
