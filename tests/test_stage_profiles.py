"""Tests for per-stage profile resolution, model/effort capability, and CLI compatibility."""

import asyncio
import shutil
from datetime import UTC, datetime, timedelta

import pytest

from minime.adapters.provider_adapter import (
    AntigravityProviderAdapter,
    CodexProviderAdapter,
    OpenRouterProviderAdapter,
)
from minime.config import (
    AppConfig,
    CliInvocationConfig,
    OpenSpecStage,
    ProjectConfig,
    ProviderConfig,
    StageProfileConfig,
    StageProfileError,
    resolve_cli_invocation,
    resolve_stage_profile,
)
from minime.services.cli_preflight import preflight_cli_invocation
from minime.services.native_openspec_apply import (
    AGY_APPLY_SKILL_PATH,
    CODEX_APPLY_SKILL_PATH,
    resolve_native_openspec_apply,
    workflow_unchanged,
)


@pytest.fixture
def default_project() -> ProjectConfig:
    return ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["codex", "antigravity", "deepseek"],
    )


def test_default_r01_stage_profiles_resolve_non_premium(default_project, monkeypatch):
    """Prove canonical R01 stage profiles resolve non-premium defaults for all stages."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    stages = [
        OpenSpecStage.PLAN,
        OpenSpecStage.CONTRACT_REVIEW,
        OpenSpecStage.APPLY,
        OpenSpecStage.TEST,
        OpenSpecStage.VERIFY,
        OpenSpecStage.REVIEW,
    ]
    for stage in stages:
        resolved = resolve_stage_profile(default_project, stage)
        assert resolved.stage == stage.value
        assert resolved.is_premium is False
        assert resolved.is_escalated is False
        assert resolved.cost_basis == "standard"
        assert resolved.model != ""
        assert resolved.effort in ("low", "medium")

    # Specific role assignments from R01 spec:
    plan = resolve_stage_profile(default_project, OpenSpecStage.PLAN)
    assert plan.provider == "codex"
    assert plan.model == "gpt-5.6-luna"
    assert plan.workflow == "openspec-propose"

    apply_profile = resolve_stage_profile(default_project, OpenSpecStage.APPLY)
    assert apply_profile.provider == "antigravity"
    assert apply_profile.model == "gemini-3.8-flash-medium"
    assert apply_profile.effort == "medium"
    assert apply_profile.workflow == "openspec-apply-change"

    test_profile = resolve_stage_profile(default_project, OpenSpecStage.TEST)
    assert test_profile.provider == "antigravity"
    assert test_profile.model == "gemini-3.8-flash-low"
    assert test_profile.effort == "low"

    verify_profile = resolve_stage_profile(default_project, "VERIFY_E2E")
    assert verify_profile.stage == "VERIFY"
    assert verify_profile.provider == "codex"
    assert verify_profile.model == "gpt-5.6-luna"


def test_stage_profile_rejects_premium_model_by_default(default_project, monkeypatch):
    """Prove premium models fail closed when configured as default without escalation."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    premium_cases = [
        ("antigravity", "gemini-2.5-pro"),
        ("antigravity", "gemini-pro"),
        ("antigravity", "claude-opus-5-5-high"),
        ("codex", "gpt-4o"),
        ("codex", "o1"),
    ]
    for provider, model in premium_cases:
        proj = ProjectConfig(
            repository="test-org/test-repo",
            external_providers_allowed=["codex", "antigravity", "deepseek"],
            stage_profiles={
                "APPLY": StageProfileConfig(
                    provider=provider,
                    model=model,
                    effort="medium",
                )
            },
        )
        with pytest.raises(StageProfileError, match="PREMIUM_MODEL_REJECTED"):
            resolve_stage_profile(proj, "APPLY")

    deepseek_reviewer = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["deepseek"],
        stage_profiles={
            "CONTRACT_REVIEW": StageProfileConfig(
                provider="deepseek", model="deepseek-reasoner", effort="medium"
            )
        },
    )
    with pytest.raises(StageProfileError, match="PREMIUM_MODEL_REJECTED"):
        resolve_stage_profile(deepseek_reviewer, "CONTRACT_REVIEW")


def test_stage_profile_rejects_max_effort_by_default(default_project):
    """Prove max/xhigh effort fails closed when configured without escalation."""
    max_effort_cases = [
        ("antigravity", "max"),
        ("antigravity", "xhigh"),
    ]
    for provider, effort in max_effort_cases:
        proj = ProjectConfig(
            repository="test-org/test-repo",
            external_providers_allowed=["codex", "antigravity"],
            stage_profiles={
                "APPLY": StageProfileConfig(
                    provider=provider,
                    model="gemini-3.8-flash-medium",
                    effort=effort,
                )
            },
        )
        with pytest.raises(StageProfileError, match="MAX_EFFORT_REJECTED"):
            resolve_stage_profile(proj, "APPLY")


def test_stage_profile_allows_escalation_when_fully_authorized():
    """Prove escalation succeeds only when authorization, rationale, and budget are all present."""
    proj = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["codex", "antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-2.5-pro",
                effort="max",
            )
        },
    )
    resolved = resolve_stage_profile(
        proj,
        "APPLY",
        escalation_authorized=True,
        escalation_rationale="Task complexity requires advanced reasoning and expanded context.",
        budget_authorized=True,
    )
    assert resolved.is_premium is True
    assert resolved.is_escalated is True
    assert resolved.cost_basis == "premium"
    assert resolved.model == "gemini-2.5-pro"
    assert resolved.effort == "max"


def test_stage_profile_escalation_fails_closed_if_missing_any_requirement():
    """Prove escalation fails closed if rationale, authorization, or budget is omitted."""
    proj = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["codex", "antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-2.5-pro",
                effort="medium",
            )
        },
    )
    # Missing rationale
    with pytest.raises(StageProfileError, match="PREMIUM_MODEL_REJECTED"):
        resolve_stage_profile(
            proj,
            "APPLY",
            escalation_authorized=True,
            escalation_rationale="",
            budget_authorized=True,
        )

    # Missing budget
    with pytest.raises(StageProfileError, match="PREMIUM_MODEL_REJECTED"):
        resolve_stage_profile(
            proj,
            "APPLY",
            escalation_authorized=True,
            escalation_rationale="Need bigger model",
            budget_authorized=False,
        )

    # Missing authorization flag
    with pytest.raises(StageProfileError, match="PREMIUM_MODEL_REJECTED"):
        resolve_stage_profile(
            proj,
            "APPLY",
            escalation_authorized=False,
            escalation_rationale="Need bigger model",
            budget_authorized=True,
        )


def test_stage_profile_rejects_unsupported_model(default_project):
    """Prove unsupported model names fail closed immediately."""
    proj = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="totally-unsupported-model-9000",
            )
        },
    )
    with pytest.raises(StageProfileError, match="UNSUPPORTED_MODEL"):
        resolve_stage_profile(proj, "APPLY")


def test_stage_profile_rejects_unsupported_effort(default_project):
    """Prove unsupported effort names fail closed immediately."""
    proj = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-3.8-flash-medium",
                effort="hyperdrive",
            )
        },
    )
    with pytest.raises(StageProfileError, match="UNSUPPORTED_EFFORT"):
        resolve_stage_profile(proj, "APPLY")


def test_stage_profile_rejects_unallowed_provider():
    """Prove provider outside project allowed list fails closed."""
    proj = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["codex"],  # antigravity is forbidden
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-3.8-flash-medium",
            )
        },
    )
    with pytest.raises(StageProfileError, match="PROVIDER_NOT_ALLOWED"):
        resolve_stage_profile(proj, "APPLY")


def test_stage_profile_requires_deepseek_direct_for_code_review(default_project):
    """A primary CLI cannot substitute for the independent DeepSeek reviewer."""
    with pytest.raises(StageProfileError, match="CODE_REVIEW_(WAITING|REQUIRES_DEEPSEEK_DIRECT)"):
        resolve_stage_profile(
            default_project,
            "REVIEW",
            implementer_provider="codex",  # default REVIEW uses codex
        )


def test_cli_invocation_args_include_exact_model_variant_and_codex_effort(default_project):
    """AGY gets its indivisible model variant; Codex gets explicit reasoning effort."""
    resolved_agy = resolve_stage_profile(default_project, OpenSpecStage.APPLY)
    assert resolved_agy.cli_invocation is not None
    assert resolved_agy.cli_invocation.model == "gemini-3.8-flash-medium"
    assert resolved_agy.cli_invocation.effort == "medium"
    assert "--model" in resolved_agy.cli_invocation.args
    model_index = resolved_agy.cli_invocation.args.index("--model")
    assert resolved_agy.cli_invocation.args[model_index + 1] == "gemini-3.8-flash-medium"
    assert "--effort" not in resolved_agy.cli_invocation.args

    resolved_codex = resolve_stage_profile(default_project, OpenSpecStage.PLAN)
    assert resolved_codex.cli_invocation is not None
    assert resolved_codex.cli_invocation.model == "gpt-5.6-luna"
    assert "--model" in resolved_codex.cli_invocation.args
    assert "gpt-5.6-luna" in resolved_codex.cli_invocation.args
    assert 'model_reasoning_effort="medium"' in resolved_codex.cli_invocation.args


def test_cli_invocation_rejects_embedded_model_or_effort_substitution():
    """A base invocation cannot override the model/effort selected for a stage."""
    agy_config = AppConfig(
        providers={
            "antigravity": ProviderConfig(
                command="agy",
                roles=["implementer"],
                invocation={
                    "implementer": CliInvocationConfig(
                        args=[
                            "--model",
                            "gemini-3.8-flash-low",
                            "--effort",
                            "low",
                            "--print={prompt}",
                        ],
                        prompt_transport="argument",
                    )
                },
            )
        }
    )
    with pytest.raises(ValueError, match="refusing silent model/effort substitution"):
        resolve_cli_invocation(
            "antigravity",
            "implementer",
            agy_config,
            model="gemini-3.8-flash-medium",
            effort="medium",
        )

    codex_config = AppConfig(
        providers={
            "codex": ProviderConfig(
                command="codex",
                roles=["implementer"],
                invocation={
                    "implementer": CliInvocationConfig(
                        args=[
                            "exec",
                            "-",
                            "-c",
                            'model="gpt-5.5"',
                            "-c",
                            'model_reasoning_effort="low"',
                        ],
                        prompt_transport="stdin",
                    )
                },
            )
        }
    )
    with pytest.raises(ValueError, match="refusing silent model/effort substitution"):
        resolve_cli_invocation(
            "codex",
            "implementer",
            codex_config,
            model="gpt-5.6-luna",
            effort="medium",
        )


def test_agy_effort_variant_omits_effort_flag_and_rejects_contradictions():
    config = AppConfig(
        providers={
            "antigravity": ProviderConfig(
                command="agy",
                roles=["implementer"],
                invocation={
                    "implementer": CliInvocationConfig(
                        args=["--effort", "medium", "--print={prompt}"],
                        prompt_transport="argument",
                    )
                },
            )
        }
    )
    resolved = resolve_cli_invocation(
        "antigravity",
        "implementer",
        config,
        model="gemini-3.8-flash-medium",
        effort="medium",
    )
    assert resolved.model == "gemini-3.8-flash-medium"
    assert resolved.effort == "medium"
    assert resolved.args.count("--model") == 1
    assert resolved.args[resolved.args.index("--model") + 1] == "gemini-3.8-flash-medium"
    assert "--effort" not in resolved.args

    with pytest.raises(ValueError, match="encodes effort 'medium'"):
        resolve_cli_invocation(
            "antigravity",
            "implementer",
            config,
            model="gemini-3.8-flash-medium",
            effort="low",
        )


def test_stage_profile_rejects_effort_conflicting_with_agy_model_variant():
    project = ProjectConfig(
        repository="test-org/test-repo",
        external_providers_allowed=["antigravity"],
        stage_profiles={
            "APPLY": StageProfileConfig(
                provider="antigravity",
                model="gemini-3.8-flash-medium",
                effort="low",
            )
        },
    )
    with pytest.raises(StageProfileError, match="encodes effort 'medium'"):
        resolve_stage_profile(project, "APPLY")


@pytest.mark.skipif(shutil.which("agy") is None, reason="agy CLI not installed")
async def test_resolved_agy_profile_passes_real_cli_preflight(default_project):
    """The installed AGY catalog authorizes the exact effort-bearing model variant."""
    resolved = resolve_stage_profile(default_project, OpenSpecStage.APPLY)
    assert resolved.cli_invocation is not None
    preflight = await preflight_cli_invocation(resolved.cli_invocation)
    assert preflight.ok is True, preflight.reason


@pytest.mark.asyncio
async def test_agy_catalog_does_not_fabricate_model_effort_compatibility(monkeypatch):
    adapter = AntigravityProviderAdapter()

    async def listed_models(timeout_seconds=10.0):
        del timeout_seconds
        return {"models": ["gemini-3.8-flash-medium"], "model_efforts": {}}

    monkeypatch.setattr(adapter, "discover_account_capabilities", listed_models)
    supported, reason = await adapter.check_model_supported(
        "gemini-3.8-flash-medium", effort="medium"
    )
    assert supported is False
    assert reason.startswith("EFFORT_CAPABILITY_UNOBSERVABLE")


@pytest.mark.asyncio
async def test_agy_variant_requires_exact_live_catalog_identity_and_effort(monkeypatch):
    adapter = AntigravityProviderAdapter()

    async def listed_models(timeout_seconds=10.0):
        del timeout_seconds
        return {
            "models": ["gemini-3.8-flash-low", "gemini-3.8-flash-medium"],
            "model_efforts": {
                "gemini-3.8-flash-low": "low",
                "gemini-3.8-flash-medium": "medium",
            },
        }

    monkeypatch.setattr(adapter, "discover_account_capabilities", listed_models)
    supported, reason = await adapter.check_model_supported(
        "gemini-3.8-flash-medium", effort="medium"
    )
    wrong_effort, wrong_reason = await adapter.check_model_supported(
        "gemini-3.8-flash-medium", effort="low"
    )
    absent_variant, absent_reason = await adapter.check_model_supported(
        "gemini-3.8-flash-high", effort="high"
    )

    assert supported is True and reason is None
    assert wrong_effort is False
    assert wrong_reason.startswith("EFFORT_VARIANT_CONFLICT")
    assert absent_variant is False
    assert absent_reason.startswith("MODEL_ABSENT_FROM_ACCOUNT")


@pytest.mark.asyncio
async def test_agy_live_catalog_derives_effort_only_from_listed_model_variant(monkeypatch):
    adapter = AntigravityProviderAdapter()

    class CatalogProcess:
        returncode = 0

        async def communicate(self):
            return (
                b"Fetching available models...\n"
                b"gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)\n"
                b"gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
                b"claude-sonnet-5-5\tClaude Sonnet 5.5\n",
                b"",
            )

    async def create_process(*args, **kwargs):
        assert args[1] == "models"
        assert kwargs["stdin"] is asyncio.subprocess.DEVNULL
        return CatalogProcess()

    monkeypatch.setattr(adapter, "_resolve_executable", lambda: "/usr/bin/agy")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)

    caps = await adapter.discover_account_capabilities()

    assert caps["models"] == [
        "gemini-3.8-flash-medium",
        "gemini-3.8-flash-high",
        "claude-sonnet-5-5",
    ]
    assert caps["model_efforts"] == {
        "gemini-3.8-flash-medium": "medium",
        "gemini-3.8-flash-high": "high",
    }


@pytest.mark.asyncio
async def test_codex_model_list_without_effort_data_fails_closed(monkeypatch):
    adapter = CodexProviderAdapter()

    async def listed_models(timeout_seconds=10.0):
        del timeout_seconds
        return {"models": {"gpt-5.6-luna": None}}

    monkeypatch.setattr(adapter, "discover_account_capabilities", listed_models)
    supported, reason = await adapter.check_model_supported("gpt-5.6-luna", effort="medium")
    assert supported is False
    assert reason.startswith("EFFORT_CAPABILITY_UNOBSERVABLE")


@pytest.mark.asyncio
async def test_codex_model_list_efforts_are_bound_to_each_exact_model(monkeypatch):
    adapter = CodexProviderAdapter()

    async def model_list(method, params=None, timeout_seconds=10.0):
        del params, timeout_seconds
        assert method == "model/list"
        return {
            "data": [
                {"id": "gpt-stage-a", "supportedReasoningEfforts": ["low", "medium"]},
                {"id": "gpt-stage-b", "supportedReasoningEfforts": ["low"]},
            ]
        }

    monkeypatch.setattr(adapter, "_call_app_server_method", model_list)
    supported_a, reason_a = await adapter.check_model_supported("gpt-stage-a", effort="medium")
    supported_b, reason_b = await adapter.check_model_supported("gpt-stage-b", effort="medium")

    assert supported_a is True
    assert reason_a is None
    assert supported_b is False
    assert reason_b.startswith("EFFORT_UNSUPPORTED_FOR_MODEL")


@pytest.mark.asyncio
async def test_codex_active_account_model_list_rejects_absent_model(monkeypatch):
    adapter = CodexProviderAdapter()

    async def listed_models(timeout_seconds=10.0):
        del timeout_seconds
        return {"models": {"gpt-5.6-luna": ["medium"]}}

    monkeypatch.setattr(adapter, "discover_account_capabilities", listed_models)
    supported, reason = await adapter.check_model_supported("gpt-4o-mini", effort="medium")
    assert supported is False
    assert reason.startswith("MODEL_ABSENT_FROM_ACCOUNT")


@pytest.mark.asyncio
async def test_adapter_without_capability_discovery_fails_closed():
    supported, reason = await OpenRouterProviderAdapter().check_model_supported(
        "unverified-model", effort="medium"
    )
    assert supported is False
    assert reason.startswith("CAPABILITY_DISCOVERY_UNAVAILABLE")


@pytest.mark.asyncio
async def test_agy_failed_live_model_discovery_does_not_reuse_cached_catalog(monkeypatch):
    adapter = AntigravityProviderAdapter()
    adapter._cached_capabilities = {
        "models": ["gemini-3.8-flash-medium"],
        "model_efforts": {"gemini-3.8-flash-medium": ["medium"]},
    }
    adapter._capabilities_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    monkeypatch.setattr(adapter, "_resolve_executable", lambda: None)

    supported, reason = await adapter.check_model_supported(
        "gemini-3.8-flash-medium", effort="medium"
    )
    assert supported is False
    assert reason.startswith("EXECUTABLE_MISSING")


@pytest.mark.asyncio
async def test_codex_failed_live_model_discovery_does_not_reuse_cached_catalog(monkeypatch):
    adapter = CodexProviderAdapter()
    adapter._cached_capabilities = {"models": {"gpt-5.6-luna": ["medium"]}}
    adapter._capabilities_expires_at = datetime.now(UTC) + timedelta(minutes=1)

    async def unavailable(*args, **kwargs):
        return None

    monkeypatch.setattr(adapter, "_call_app_server_method", unavailable)
    supported, reason = await adapter.check_model_supported("gpt-5.6-luna", effort="medium")
    assert supported is False
    assert reason.startswith("CAPABILITY_DISCOVERY_UNAVAILABLE")


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed")
async def test_resolved_codex_profile_passes_real_cli_preflight(default_project):
    """Prove the resolved Codex stage profile passes preflight against installed codex CLI."""
    resolved = resolve_stage_profile(default_project, OpenSpecStage.PLAN)
    assert resolved.cli_invocation is not None
    preflight = await preflight_cli_invocation(resolved.cli_invocation)
    assert preflight.ok is True, (
        f"Preflight failed: {preflight.reason}, missing: {preflight.missing_flags}"
    )


def test_native_apply_resolution_for_antigravity_and_codex(tmp_path):
    """Prove native apply resolves both Antigravity (.agent) and Codex (.agents) skills."""
    skill_content = """---
name: openspec-apply-change
description: Apply a change.
metadata:
  version: "1.0"
---
Use the native OpenSpec workflow.
"""
    # 1. Antigravity skill in .agent/skills/openspec-apply-change/SKILL.md
    agy_skill = tmp_path / AGY_APPLY_SKILL_PATH
    agy_skill.parent.mkdir(parents=True)
    agy_skill.write_text(skill_content, encoding="utf-8")

    # 2. Codex skill in .agents/skills/openspec-apply-change/SKILL.md
    codex_skill = tmp_path / CODEX_APPLY_SKILL_PATH
    codex_skill.parent.mkdir(parents=True)
    codex_skill.write_text(skill_content, encoding="utf-8")

    # Resolve Antigravity native apply
    agy_wf = resolve_native_openspec_apply(
        tmp_path,
        "sample-change",
        provider="antigravity",
        project_id="proj-1",
        repository_identity="github.com/acme/repo",
        run_id="run-1",
        job_id="job-1",
        base_sha="0" * 40,
    )
    assert agy_wf.provider == "antigravity"
    assert "/opsx-apply sample-change" in agy_wf.dispatch_instruction()
    assert agy_wf.workflow_path == AGY_APPLY_SKILL_PATH
    assert workflow_unchanged(tmp_path, agy_wf)

    # Resolve Codex native apply
    codex_wf = resolve_native_openspec_apply(
        tmp_path,
        "sample-change",
        provider="codex",
        project_id="proj-1",
        repository_identity="github.com/acme/repo",
        run_id="run-1",
        job_id="job-1",
        base_sha="0" * 40,
    )
    assert codex_wf.provider == "codex"
    assert "$openspec-apply-change sample-change" in codex_wf.dispatch_instruction()
    assert codex_wf.workflow_path == CODEX_APPLY_SKILL_PATH
    assert workflow_unchanged(tmp_path, codex_wf)
