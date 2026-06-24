import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

from onep.config import (
    Config,
    LLMConfig,
    ProjectConfig,
    PipelineConfig,
    load_config,
    save_config,
    _config_dir,
    _config_path,
)


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.default_model == "deepseek/deepseek-chat"
    assert cfg.complex_model == "openai/gpt-5.5"


def test_config_default_values():
    cfg = Config()
    assert cfg.llm.default_model == "deepseek/deepseek-chat"
    assert cfg.pipeline.max_retries == 3
    assert cfg.pipeline.auto_approve is False


@mock.patch("onep.config._config_path")
@mock.patch("onep.config._config_dir")
def test_load_config_creates_default(mock_dir, mock_path):
    tmp = Path(tempfile.mkdtemp())
    mock_dir.return_value = tmp
    mock_path.return_value = tmp / "config.yaml"

    config = load_config()
    assert config.llm.default_model == "deepseek/deepseek-chat"
    assert (tmp / "config.yaml").exists()


@mock.patch("onep.config._config_path")
@mock.patch("onep.config._config_dir")
def test_load_config_reads_existing(mock_dir, mock_path):
    tmp = Path(tempfile.mkdtemp())
    mock_dir.return_value = tmp
    cfg_file = tmp / "config.yaml"
    cfg_file.write_text(yaml.dump({
        "llm": {"default_model": "openai/gpt-4o"},
        "pipeline": {"max_retries": 5},
    }))
    mock_path.return_value = cfg_file

    config = load_config()
    assert config.llm.default_model == "openai/gpt-4o"
    assert config.pipeline.max_retries == 5


@mock.patch("onep.config._config_path")
@mock.patch("onep.config._config_dir")
def test_save_config_persists(mock_dir, mock_path):
    tmp = Path(tempfile.mkdtemp())
    mock_dir.return_value = tmp
    cfg_file = tmp / "config.yaml"
    mock_path.return_value = cfg_file

    config = Config()
    config.pipeline.max_retries = 10
    save_config(config)

    reloaded = yaml.safe_load(cfg_file.read_text())
    assert reloaded["pipeline"]["max_retries"] == 10
