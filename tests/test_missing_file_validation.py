from minime.domain.enums import BlockerValidationVerdict
from minime.services.blocker_validation import BlockerValidationContext, BlockerValidationService


def _context(**kwargs):
    values = dict(
        change_name="change",
        required_files=["tests/test_required.py"],
        candidate_tree_files=["tests/test_required.py"],
        manifest_files=["tests/test_required.py"],
    )
    values.update(kwargs)
    return BlockerValidationContext(**values)


def test_unchanged_base_file_present_in_candidate_is_not_a_blocker():
    result = BlockerValidationService().validate_missing_file("tests/test_required.py", _context())
    assert result.verdict == BlockerValidationVerdict.FALSE_BLOCKER


def test_explicitly_required_file_absent_is_a_real_blocker():
    result = BlockerValidationService().validate_missing_file(
        "tests/test_required.py", _context(candidate_tree_files=[], manifest_files=[])
    )
    assert result.verdict == BlockerValidationVerdict.REAL_BLOCKER


def test_guessed_filename_absent_is_rejected_as_false_blocker():
    result = BlockerValidationService().validate_missing_file(
        "src/minime/services/scheduler_service.py",
        _context(
            required_files=[],
            candidate_tree_files=["src/minime/services/capacity_lifecycle_service.py"],
        ),
    )
    assert result.verdict == BlockerValidationVerdict.FALSE_BLOCKER
