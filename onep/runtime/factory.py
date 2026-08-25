"""Construct the single supported Codex App Server engineering runtime."""

from onep.runtime.codex_app_server import CodexAppServerRuntime


def build_codex_runtime(execution_config):
    return CodexAppServerRuntime(execution_config)
