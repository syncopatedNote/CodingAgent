"""Unit tests for the coding-agent custom tools.

Focus on ``generate_code``'s new ``target_path`` argument and the
Generate-vs-Improve branching driven by ``existing_code``. The module-level
``code_llm`` is monkeypatched so no real LLM call is made; the test captures
the messages the tool builds and asserts on the rendered prompt.
"""

import pytest

from langchain_core.messages import HumanMessage, SystemMessage

from agents.coding_pipeline.coding_agent import custom_tools


class FakeResponse:
    def __init__(self, content):
        self.content = content


class CaptureLLM:
    """Captures the messages passed to ainvoke and returns canned content."""

    def __init__(self):
        self.captured_messages = None

    async def ainvoke(self, messages):
        self.captured_messages = messages
        return FakeResponse("### `app/main.py`\n```\ncode\n```")


@pytest.fixture
def capture_llm(monkeypatch):
    fake = CaptureLLM()
    monkeypatch.setattr(custom_tools, "code_llm", fake)
    return fake


def _human_text(messages):
    return next(m.content for m in messages if isinstance(m, HumanMessage))


async def test_generate_code_includes_target_path_in_prompt(capture_llm):
    await custom_tools.generate_code.ainvoke(
        {
            "target_path": "agents/supervisor_agent.py",
            "requirements": "add a method",
            "context": "the supervisor routes tasks",
        }
    )

    prompt = _human_text(capture_llm.captured_messages)
    assert "agents/supervisor_agent.py" in prompt


async def test_generate_code_generate_mode_without_existing_code(capture_llm):
    await custom_tools.generate_code.ainvoke(
        {
            "target_path": "app/new.py",
            "requirements": "create it",
            "context": "brand new file",
        }
    )

    prompt = _human_text(capture_llm.captured_messages)
    assert "Generate production-ready code" in prompt
    assert "CURRENT CODE TO IMPROVE" not in prompt


async def test_generate_code_improve_mode_with_existing_code(capture_llm):
    await custom_tools.generate_code.ainvoke(
        {
            "target_path": "app/existing.py",
            "requirements": "tweak it",
            "context": "modify the existing file",
            "existing_code": "def old():\n    pass",
        }
    )

    prompt = _human_text(capture_llm.captured_messages)
    assert "Improve production-ready code" in prompt
    assert "CURRENT CODE TO IMPROVE" in prompt
    assert "def old()" in prompt


async def test_generate_code_injects_guidelines_as_system_message(capture_llm):
    await custom_tools.generate_code.ainvoke(
        {
            "target_path": "app/x.py",
            "requirements": "do",
            "context": "ctx",
            "guidelines": "ALWAYS use settings",
        }
    )

    sys_msgs = [
        m for m in capture_llm.captured_messages if isinstance(m, SystemMessage)
    ]
    assert any("ALWAYS use settings" in m.content for m in sys_msgs)


async def test_generate_code_no_system_message_without_guidelines(capture_llm):
    await custom_tools.generate_code.ainvoke(
        {
            "target_path": "app/x.py",
            "requirements": "do",
            "context": "ctx",
        }
    )

    sys_msgs = [
        m for m in capture_llm.captured_messages if isinstance(m, SystemMessage)
    ]
    assert sys_msgs == []
