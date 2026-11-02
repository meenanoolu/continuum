from src.agent import AgentRun, ToolAgent
from src.models import LLMError, Models
from src.models.fake import FakeLLM
from src.sandbox import Sandbox


class NoTools(FakeLLM):
    """Simulates a host that rejects the `tools` parameter."""
    def complete(self, messages, *, tools=None, **kw):
        if tools:
            raise LLMError("400: tools not supported")
        return super().complete(messages, tools=None, **kw)


class Dead(FakeLLM):
    available = False


def run(models, tmp_path, tools=("list_files", "read_file", "write_file", "run_python", "run_tests")):
    events = []
    sb = Sandbox(tmp_path / "w")
    out = ToolAgent(models, sb, lambda k, t: events.append((k, t)), list(tools)).run("sys", "task")
    return out, sb, events


def test_open_model_tool_calling_is_used_first(tmp_path):
    m = Models(FakeLLM("meta-api", "spark"), FakeLLM("baseten", "open"))
    out, sb, _ = run(m, tmp_path)
    assert out.mode == "tool_calling" and out.models_used == ["baseten:open"]
    assert sb.has_tests()


def test_open_model_without_tools_uses_text_protocol_not_meta(tmp_path):
    m = Models(FakeLLM("meta-api", "spark"), NoTools("baseten", "open"))
    out, sb, _ = run(m, tmp_path)
    assert out.mode == "text_fallback" and out.models_used == ["baseten:open"]
    assert sb.run_tests().ok


def test_meta_takes_over_only_if_open_unavailable(tmp_path):
    m = Models(FakeLLM("meta-api", "spark"), Dead("baseten", "open"))
    out, _, _ = run(m, tmp_path)
    assert out.mode == "tool_calling" and out.models_used == ["meta-api:spark"]


def test_unknown_or_disallowed_tool_is_refused(tmp_path):
    sb = Sandbox(tmp_path / "w")
    agent = ToolAgent(Models(FakeLLM("a", "b"), FakeLLM("c", "d")), sb, lambda *a: None, ["list_files"])
    call = {"id": "1", "type": "function", "function": {"name": "write_file", "arguments": '{"path":"x.py","content":"1"}'}}
    assert "not available" in agent._execute(call, AgentRun())
    bad = {"id": "2", "type": "function", "function": {"name": "list_files", "arguments": "not json"}}
    assert "bad arguments" in agent._execute(bad, AgentRun())
