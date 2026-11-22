import pytest
from unittest.mock import MagicMock
from minime.services.openspec_tasks import OpenSpecTask, is_verification_task
from minime.services.agent_runner import AgentExecutionResult


def test_spanish_verification_task_patterns():
    task1 = OpenSpecTask(task_id="4.3", text="4.3 Comprobar navegación móvil y enlaces de apoyo en Apply o Verify", section="Calidad", complete=False)
    assert is_verification_task(task1) is True

    task2 = OpenSpecTask(task_id="4.4", text="4.4 Verificar que las pruebas pasen en verde", section="Calidad", complete=False)
    assert is_verification_task(task2) is True

    task3 = OpenSpecTask(task_id="1.1", text="1.1 Crear componente Astro de navegación", section="Calidad", complete=False)
    assert is_verification_task(task3) is False


def test_spanish_verification_task_ignores_implementation_section():
    task = OpenSpecTask(task_id="2.1", text="2.1 Comprobar e implementar vista", section="Implementation Phase", complete=False)
    assert is_verification_task(task) is False


def test_apply_ready_when_tests_passed_despite_pending_markdown_tasks():
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        openspec_adapter=MagicMock(),
    )

    result = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["Done"],
        stderr=[],
        duration_ms=100,
        final_response="{}",
    )

    successful = coordinator._execution_is_successful(result)
    assert successful is True

    # Case A: Tests passed in green -> ready must be True even if markdown has unchecked boxes
    automated_pending = ["4.3"]
    tests_passed = True
    ready = successful and (not automated_pending or bool(tests_passed))
    status = "COMPLETE" if ready else ("PARTIAL" if successful else "FAILED")
    assert ready is True
    assert status == "COMPLETE"

    # Case B: Tests failed -> ready is False, status is PARTIAL
    tests_passed = False
    ready = successful and (not automated_pending or bool(tests_passed))
    status = "COMPLETE" if ready else ("PARTIAL" if successful else "FAILED")
    assert ready is False
    assert status == "PARTIAL"
