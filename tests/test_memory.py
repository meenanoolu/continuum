from src.gate import overlap_ratio
from src.jsonutil import extract_json
from src.memory import PersonalMemory


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here: {"a": {"b": "}"}} thanks') == {"a": {"b": "}"}}
    assert extract_json("[1,2]") == [1, 2]
    assert extract_json("no json") is None and extract_json(None) is None


def test_overlap_detects_copying():
    ref = "pure functions depend only on their inputs which makes them trivial to test without setup"
    assert overlap_ratio("pure functions depend only on their inputs which makes them trivial to test", ref) > 0.8
    assert overlap_ratio("because nothing else changes the result I can call it directly in a test", ref) < 0.5
    assert overlap_ratio("short", ref) == 0.0


def test_memory_changes_policy(tmp_path):
    m = PersonalMemory(str(tmp_path / "m.json"))
    assert m.gate_policy("p")["strictness"] == "standard"
    m.record_gate("p", "s1", "Unit Testing", False, 0.4, {"parroting": True}, 1)
    m.record_gate("p", "s1", "unit testing", False, 0.5, {"parroting": True}, 2)
    pol = m.gate_policy("p", "unit testing")
    assert pol["strictness"] == "strict" and pol["questions"] == 4
    assert m.weak_concepts() == ["unit testing"]
    assert m.should_revise("p", 0)
    assert m.should_revise("p", 2) is None  # already revised at this point
    m.record_learning("p", "unit testing", True)
    m.record_gate("p", "s2", "unit testing", True, 1.8, {}, 1)
    assert "unit testing" in m.mastered_concepts() and m.weak_concepts() == []


def test_v1_memory_migrates(tmp_path):
    import json
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"user_id": "default", "projects": {"x": {"reflections": []}},
                             "global_patterns": {"mastered_concepts": ["fastapi routing"]}}))
    m = PersonalMemory(str(p))
    assert m.has_mastered("FastAPI routing") and "x" in m.data["projects"]
    m.get_project("x")["gate_outcomes"]  # missing keys are created lazily
