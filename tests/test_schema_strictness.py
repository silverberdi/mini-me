"""Unit tests for OpenAI strict schema validation and structured output conformance."""

import pytest

from minime.services.proposal_feasibility import (
    ProposalFeasibilityEvaluator,
    validate_openai_strict_schema,
)


def test_proposal_feasibility_output_schema_complies_with_openai_strict_rules():
    """Verify that ProposalFeasibilityEvaluator.output_schema() strictly complies with OpenAI schema rules."""
    schema = ProposalFeasibilityEvaluator.output_schema()
    # Must validate cleanly without raising ValueError
    validate_openai_strict_schema(schema)


def test_validate_strict_schema_detects_missing_required_property():
    """Schema must reject properties that are omitted from the required list."""
    invalid_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "optional_field": {"type": ["string", "null"]},
        },
        "required": ["title"],  # missing 'optional_field'
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match="every key in 'properties' must be listed in 'required'"):
        validate_openai_strict_schema(invalid_schema)


def test_validate_strict_schema_detects_missing_additional_properties_false():
    """Schema must reject objects missing additionalProperties: False."""
    invalid_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
        },
        "required": ["title"],
        # missing "additionalProperties": False
    }
    with pytest.raises(ValueError, match="'additionalProperties' must be explicitly False"):
        validate_openai_strict_schema(invalid_schema)


def test_validate_strict_schema_detects_nested_violations():
    """Schema must recursively validate nested objects and items."""
    invalid_nested = {
        "type": "object",
        "properties": {
            "nested": {
                "type": "object",
                "properties": {
                    "inner_a": {"type": "string"},
                    "inner_b": {"type": "string"},
                },
                "required": ["inner_a"],  # missing 'inner_b'
                "additionalProperties": False,
            }
        },
        "required": ["nested"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match="every key in 'properties' must be listed in 'required'"):
        validate_openai_strict_schema(invalid_nested)


def test_validate_strict_schema_detects_array_item_violations():
    """Schema must recursively validate items in arrays."""
    invalid_array = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "desc": {"type": "string"},
                    },
                    "required": ["id"],  # missing 'desc'
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match="every key in 'properties' must be listed in 'required'"):
        validate_openai_strict_schema(invalid_array)
