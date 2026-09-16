# Leaf C: probe configuration is explicit per provider, validated, and selected
# per-provider by the health service (no hidden operator-critical timing defaults).

from pathlib import Path

import pytest
import yaml

from minime.config import (
    AppConfig,
    ProbeConfig,
    probe_configs_from_app_config,
)
from minime.services.provider_health_service import ProviderHealthService

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_probe_config_defaults_are_sensible():
    cfg = ProbeConfig()
    assert cfg.cooldown_seconds == 300
    assert cfg.backoff_base_seconds == 300
    assert cfg.backoff_max_seconds == 3600
    assert cfg.max_per_hour == 4


def test_probe_config_rejects_negative_values():
    with pytest.raises(ValueError):
        ProbeConfig(cooldown_seconds=-1)
    with pytest.raises(ValueError):
        ProbeConfig(max_per_hour=-5)


def test_probe_config_rejects_backoff_max_below_base():
    with pytest.raises(ValueError, match="backoff_max_seconds"):
        ProbeConfig(backoff_base_seconds=300, backoff_max_seconds=60)


def test_example_yaml_exposes_per_provider_probe():
    raw = yaml.safe_load((REPO_ROOT / "config/minime.example.yaml").read_text())
    cfg = AppConfig.model_validate(raw)
    assert cfg.providers["codex"].probe.cooldown_seconds == 300
    assert cfg.providers["codex"].probe.max_per_hour == 4
    assert cfg.providers["antigravity"].probe.cooldown_seconds == 300
    assert cfg.providers["antigravity"].probe.max_per_hour == 4


def test_probe_configs_from_app_config_selects_per_provider():
    cfg = AppConfig.model_validate(
        {
            "providers": {
                "codex": {
                    "command": "codex",
                    "roles": ["implementer", "reviewer"],
                    "probe": {"cooldown_seconds": 60, "max_per_hour": 2},
                },
                "antigravity": {
                    "command": "agy",
                    "roles": ["implementer", "reviewer"],
                    "probe": {"cooldown_seconds": 999},
                },
            }
        }
    )
    configs = probe_configs_from_app_config(cfg)
    assert configs["codex"].cooldown_seconds == 60
    assert configs["codex"].max_per_hour == 2
    assert configs["antigravity"].cooldown_seconds == 999
    # Unspecified fields fall back to canonical defaults.
    assert configs["antigravity"].max_per_hour == 4


def test_service_selects_per_provider_probe_config(in_memory_uow):
    service = ProviderHealthService(
        in_memory_uow,
        probe_configs={
            "codex": ProbeConfig(cooldown_seconds=60),
            "antigravity": ProbeConfig(cooldown_seconds=999),
        },
    )
    assert service._probe_config("codex").cooldown_seconds == 60
    assert service._probe_config("antigravity").cooldown_seconds == 999
    # Provider with no explicit entry falls back to the process-wide default.
    assert service._probe_config("codex") is not None
    assert service._probe_config("antigravity") is not None
