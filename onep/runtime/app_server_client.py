"""Small synchronous JSON-RPC client for ``codex app-server`` over stdio."""

from __future__ import annotations

from collections import deque
import json
from queue import Empty, Queue
import subprocess
from threading import Lock, Thread
from typing import Any, Callable


class AppServerProtocolError(RuntimeError):
    pass


class AppServerClosedError(AppServerProtocolError):
    pass


class AppServerNotificationTimeout(AppServerProtocolError):
    pass


ServerRequestHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


class AppServerClient:
    """Own one app-server process and multiplex responses, requests, and events."""

    def __init__(
        self,
        codex_bin: str = "codex",
        *,
        request_timeout_seconds: float = 30,
        process_factory: Callable[..., Any] | None = None,
        server_request_handler: ServerRequestHandler | None = None,
    ):
        self.codex_bin = codex_bin
        self.request_timeout_seconds = max(1.0, request_timeout_seconds)
        self._process_factory = process_factory or subprocess.Popen
        self._server_request_handler = server_request_handler
        self._process: Any | None = None
        self._pending: dict[int, Queue] = {}
        self._pending_lock = Lock()
        self._write_lock = Lock()
        self._notifications: Queue = Queue()
        self._next_id = 1
        self._stderr: deque[str] = deque(maxlen=50)
        self._closed = False

    def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = self._process_factory(
                [self.codex_bin, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise AppServerProtocolError(
                f"Unable to start Codex app-server: {exc}"
            ) from exc
        if self._process.stdin is None or self._process.stdout is None:
            raise AppServerProtocolError("Codex app-server stdio is unavailable")
        Thread(target=self._read_stdout, daemon=True).start()
        if self._process.stderr is not None:
            Thread(target=self._read_stderr, daemon=True).start()
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "onepteam",
                    "title": "OnePTeam",
                    "version": "0.2.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self.notify("initialized", {})

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if self._process is None and method != "initialize":
            self.start()
        request_id = self._allocate_id()
        response_queue: Queue = Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_queue
        try:
            self._send({"method": method, "id": request_id, "params": params or {}})
            try:
                response = response_queue.get(
                    timeout=timeout_seconds or self.request_timeout_seconds
                )
            except Empty as exc:
                raise AppServerProtocolError(
                    f"Codex app-server request timed out: {method}"
                ) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if isinstance(response, BaseException):
            raise response
        if response.get("error") is not None:
            error = response["error"]
            detail = error.get("message") if isinstance(error, dict) else error
            raise AppServerProtocolError(f"{method} failed: {detail}")
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"method": method, "params": params or {}})

    def next_notification(self, timeout_seconds: float) -> dict[str, Any]:
        try:
            value = self._notifications.get(timeout=max(0.01, timeout_seconds))
        except Empty as exc:
            raise AppServerNotificationTimeout(
                "Timed out waiting for a Codex app-server event"
            ) from exc
        if isinstance(value, BaseException):
            raise value
        return value

    def set_server_request_handler(
        self, handler: ServerRequestHandler | None
    ) -> None:
        self._server_request_handler = handler

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return tuple(self._stderr)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self._fail_pending(AppServerClosedError("Codex app-server closed"))

    def _allocate_id(self) -> int:
        with self._pending_lock:
            value = self._next_id
            self._next_id += 1
            return value

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or self._closed:
            raise AppServerClosedError("Codex app-server is not running")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            try:
                process.stdin.write(payload + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise AppServerClosedError(
                    "Codex app-server input stream closed"
                ) from exc

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    self._dispatch(message)
        finally:
            detail = "Codex app-server output stream closed"
            if self._stderr:
                detail += f": {self._stderr[-1]}"
            error = AppServerClosedError(detail)
            self._fail_pending(error)
            self._notifications.put(error)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            value = line.strip()
            if value:
                self._stderr.append(value[:2000])

    def _dispatch(self, message: dict[str, Any]) -> None:
        identifier = message.get("id")
        method = message.get("method")
        if identifier is not None and method:
            self._respond_to_server_request(identifier, str(method), message)
            return
        if identifier is not None:
            with self._pending_lock:
                pending = self._pending.get(identifier)
            if pending is not None:
                try:
                    pending.put_nowait(message)
                except Exception:
                    pass
            return
        if method:
            self._notifications.put(message)

    def _respond_to_server_request(
        self, identifier: Any, method: str, message: dict[str, Any]
    ) -> None:
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        try:
            if self._server_request_handler is None:
                raise AppServerProtocolError(
                    f"Unsupported server request: {method}"
                )
            result = self._server_request_handler(method, params)
            self._send({"id": identifier, "result": result})
        except Exception as exc:
            self._send(
                {
                    "id": identifier,
                    "error": {"code": -32601, "message": str(exc)},
                }
            )

    def _fail_pending(self, error: BaseException) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
        for response_queue in pending:
            try:
                response_queue.put_nowait(error)
            except Exception:
                pass
