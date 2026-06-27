from onep.memory.context import MemoryContextBuilder, MemoryContextRequest


class RecordingManager:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("source_id"):
            return [{
                "id": "local",
                "source_id": "greenfield:demo",
                "title": "Local decision",
                "content": "Use JWT",
                "score": 0.3,
            }]
        return [{
            "id": "global",
            "source_id": "greenfield:other",
            "title": "Global decision",
            "content": "Rotate keys",
            "score": 0.8,
        }]


def test_builder_uses_wide_local_and_strict_global_channels():
    manager = RecordingManager()
    builder = MemoryContextBuilder(manager_factory=lambda: manager)

    context = builder.build(MemoryContextRequest(
        query="authentication",
        stage_name="architect",
        project_name="demo",
        source_id="greenfield:demo",
    ))

    assert manager.calls == [
        {
            "query": "authentication",
            "top_k": 6,
            "source_id": "greenfield:demo",
            "exclude_source_id": None,
            "min_score": 0.15,
        },
        {
            "query": "authentication",
            "top_k": 3,
            "source_id": None,
            "exclude_source_id": "greenfield:demo",
            "min_score": 0.45,
        },
    ]
    assert "[当前项目]" in context
    assert "[跨项目]" in context


def test_builder_degrades_to_empty_context():
    def fail():
        raise RuntimeError("memory unavailable")

    builder = MemoryContextBuilder(manager_factory=fail)

    assert builder.build(MemoryContextRequest("q", "pm")) == ""
