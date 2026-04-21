import threading

from openjarvis.speech.clap_boot_service import ClapBootService


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self) -> None:
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


class _FakeManager:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.agent = {"id": "jarvis-1", "agent_type": "jarvis", "status": "idle"}

    def list_agents(self):
        return [self.agent]

    def get_agent(self, agent_id: str):
        if agent_id == self.agent["id"]:
            return dict(self.agent)
        return None

    def send_message(self, agent_id: str, content: str):
        assert agent_id == self.agent["id"]
        self.messages.append(content)

    def update_agent(self, agent_id: str, **kwargs):
        assert agent_id == self.agent["id"]
        self.agent.update(kwargs)
        return dict(self.agent)


class _FakeExecutor:
    pass


def test_boot_instruction_only_queues_once_per_wake_cycle(monkeypatch) -> None:
    manager = _FakeManager()
    service = ClapBootService(manager=manager, executor=_FakeExecutor())
    service._jarvis_id = "jarvis-1"

    boot_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        "openjarvis.speech.clap_boot_service.threading.Thread",
        _ImmediateThread,
    )
    monkeypatch.setattr(
        service,
        "_boot_sequence",
        lambda agent_id, should_bootstrap: boot_calls.append((agent_id, should_bootstrap)),
    )

    service._on_double_clap()
    service._on_double_clap()

    assert len(manager.messages) == 1
    assert "BOOT ROUTINE ACTIVATED" in manager.messages[0]
    assert boot_calls == [("jarvis-1", True), ("jarvis-1", False)]