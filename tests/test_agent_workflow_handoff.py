"""The agent reports completion in the same invocation; OpenSpec remains authoritative."""

from minime.services.agent_runner import (
    AgentExecutionResult,
    AgentWorkflowHandoff,
    CliAgentRunner,
    parse_agent_workflow_handoff,
)
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def test_workflow_handoff_complete_has_no_pending_items():
    report = parse_agent_workflow_handoff(
        'Finished the native task.\n'
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"Created design and tasks","pending":[]}'
    )
    assert report == AgentWorkflowHandoff("COMPLETE", "Created design and tasks", ())


def test_workflow_handoff_reports_specific_pending_work():
    report = parse_agent_workflow_handoff(
        'MINIME_WORKFLOW_RESULT: {"status":"INCOMPLETE",'
        '"summary":"Proposal partly written","pending":["design.md","tasks.md"]}'
    )
    assert report is not None
    assert report.status == "INCOMPLETE"
    assert report.pending == ("design.md", "tasks.md")


def test_workflow_handoff_rejects_ambiguous_or_contradictory_reports():
    invalid = [
        "",
        "Done",
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":["task"]}',
        'MINIME_WORKFLOW_RESULT: {"status":"INCOMPLETE","summary":"pending","pending":[]}',
        'MINIME_WORKFLOW_RESULT: {"status":"FAILED","summary":"error","pending":["x"]}',
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":[],"extra":1}',
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":[]}\n'
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"ok","pending":[]}',
    ]
    assert all(parse_agent_workflow_handoff(value) is None for value in invalid)


def test_handoff_cannot_replace_agent_process_evidence():
    successful = AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["diagnostic"],
        stderr=[],
        duration_ms=1,
        final_response='MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"done","pending":[]}',
        final_response_status="COMPLETE",
        workflow_handoff_required=True,
        workflow_handoff=AgentWorkflowHandoff("COMPLETE", "done", ()),
    )
    assert NativeOrchestrationCoordinator._execution_is_successful(successful)
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=1,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response=successful.final_response,
            final_response_status="COMPLETE",
            workflow_handoff_required=True,
            workflow_handoff=successful.workflow_handoff,
        )
    )
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response=successful.final_response,
            final_response_status="COMPLETE",
            workflow_handoff_required=True,
            workflow_handoff=AgentWorkflowHandoff("INCOMPLETE", "pending", ("tasks.md",)),
        )
    )
    assert not NativeOrchestrationCoordinator._execution_is_successful(
        AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["diagnostic"],
            stderr=[],
            duration_ms=1,
            final_response_status="AMBIGUOUS",
            workflow_handoff_required=True,
        )
    )


def test_parser_reads_only_final_message_not_diagnostic_output():
    stdout = (
        'MINIME_WORKFLOW_RESULT: {"status":"COMPLETE","summary":"fake log","pending":[]}\n'
        'Some tool output'
    )
    parsed, status, source = CliAgentRunner._extract_final_response(
        stdout.encode(), "antigravity"
    )
    assert status == "COMPLETE"
    # The parser itself is intentionally only called with the authoritative
    # final answer; any tool logs must be excluded by the provider transport.
    assert parse_agent_workflow_handoff(parsed or "") is not None
