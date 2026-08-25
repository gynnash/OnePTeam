import json
from queue import Queue
from threading import Event

from onep.runtime.app_server_client import AppServerClient


class QueueStream:
    def __init__(self):
        self.values = Queue()

    def __iter__(self):
        return self

    def __next__(self):
        value = self.values.get(timeout=2)
        if value is None:
            raise StopIteration
        return value

    def put_json(self, value):
        self.values.put(json.dumps(value) + "\n")


class ScriptedInput:
    def __init__(self, process):
        self.process = process

    def write(self, value):
        for line in value.splitlines():
            if line:
                self.process.receive(json.loads(line))

    def flush(self):
        return None

    def close(self):
        return None


class ScriptedProcess:
    def __init__(self):
        self.stdout = QueueStream()
        self.stderr = []
        self.stdin = ScriptedInput(self)
        self.messages = []
        self.server_response = Event()
        self.returncode = None

    def receive(self, message):
        self.messages.append(message)
        method = message.get("method")
        identifier = message.get("id")
        if method == "initialize":
            self.stdout.put_json({"id": identifier, "result": {"platformOs": "macos"}})
        elif method == "account/read":
            self.stdout.put_json(
                {
                    "id": identifier,
                    "result": {"account": {"type": "chatgpt"}},
                }
            )
        elif identifier == 900:
            self.server_response.set()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.stdout.values.put(None)

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.terminate()


def test_stdio_client_initializes_routes_requests_and_answers_server_requests():
    process = ScriptedProcess()
    client = AppServerClient(
        process_factory=lambda *_args, **_kwargs: process,
        server_request_handler=lambda method, _params: {
            "decision": "decline",
            "method": method,
        },
    )

    client.start()
    account = client.request("account/read", {"refreshToken": False})
    process.stdout.put_json(
        {
            "id": 900,
            "method": "item/commandExecution/requestApproval",
            "params": {"reason": "outside policy"},
        }
    )

    assert process.server_response.wait(timeout=2)
    client.close()

    assert account["account"]["type"] == "chatgpt"
    assert process.messages[0]["method"] == "initialize"
    assert process.messages[1] == {"method": "initialized", "params": {}}
    assert process.messages[-1] == {
        "id": 900,
        "result": {
            "decision": "decline",
            "method": "item/commandExecution/requestApproval",
        },
    }
