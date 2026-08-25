"""OS-backed credential storage for configurable article models."""

from __future__ import annotations

from onep.domain import Problem


SERVICE_NAME = "OnePTeam.ArticleModels"


class KeyringCredentialStore:
    def set(self, reference: str, secret: str) -> None:
        if not reference or not secret:
            raise Problem("credential_required", "Article model credential is required")
        try:
            import keyring

            keyring.set_password(SERVICE_NAME, reference, secret)
        except Exception as exc:
            raise Problem(
                "credential_store_unavailable",
                "Operating-system credential storage is unavailable",
                str(exc),
                actionable=True,
                suggested_actions=("configure_keyring", "retry"),
            ) from exc

    def get(self, reference: str) -> str:
        if not reference:
            return ""
        try:
            import keyring

            return str(keyring.get_password(SERVICE_NAME, reference) or "")
        except Exception as exc:
            raise Problem(
                "credential_store_unavailable",
                "Operating-system credential storage is unavailable",
                str(exc),
            ) from exc

    def delete(self, reference: str) -> None:
        if not reference:
            return
        try:
            import keyring

            keyring.delete_password(SERVICE_NAME, reference)
        except Exception:
            return


class MemoryCredentialStore:
    """In-memory implementation for tests and embedded callers."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, reference: str, secret: str) -> None:
        self.values[reference] = secret

    def get(self, reference: str) -> str:
        return self.values.get(reference, "")

    def delete(self, reference: str) -> None:
        self.values.pop(reference, None)

