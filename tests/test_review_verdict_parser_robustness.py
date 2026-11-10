"""Unit tests for robust review verdict parsing with JSONDecoder and nested literals."""

import pytest
from minime.domain.enums import FindingSeverity, ReviewVerdict
from minime.services.review_verdict_parser import (
    MalformedReviewOutputError,
    parse_review_verdict,
)


def test_parse_verdict_with_css_curly_braces_in_findings():
    """Validates that CSS blocks with curly braces inside strings do not corrupt parser."""
    raw = (
        '{"verdict":"CHANGES_REQUIRED",'
        '"summary":"La lógica es correcta pero los botones no se ocultan.",'
        '"findings":['
        '  {"severity":"MAJOR",'
        '   "location":"css/styles.css",'
        '   "violated_requirement":"El selector .btn { display: flex; } anula [hidden] { display: none !important; }.",'
        '   "expected_correction":"Asegurar que [hidden] tenga precedencia sobre display: flex."}'
        ']}'
    )
    parsed = parse_review_verdict(raw)
    assert parsed.verdict == ReviewVerdict.CHANGES_REQUIRED
    assert len(parsed.findings) == 1
    assert parsed.findings[0].severity == FindingSeverity.MAJOR
    assert ".btn { display: flex; }" in parsed.findings[0].violated_requirement


def test_parse_verdict_with_multiple_nested_findings():
    """Validates that responses with multiple findings and deep structures are extracted cleanly."""
    raw = (
        '{"verdict":"CHANGES_REQUIRED",'
        '"summary":"Se detectaron 3 hallazgos durante la revisión.",'
        '"findings":['
        '  {"severity":"BLOCKER","location":"sec/auth.py","violated_requirement":"Missing token check","expected_correction":"Add validation"},'
        '  {"severity":"MAJOR","location":"db/repo.py","violated_requirement":"Missing transaction","expected_correction":"Wrap in uow"},'
        '  {"severity":"MINOR","location":"ui/view.ts","violated_requirement":"Typo in header","expected_correction":"Fix typo"}'
        ']}'
    )
    parsed = parse_review_verdict(raw)
    assert parsed.verdict == ReviewVerdict.CHANGES_REQUIRED
    assert len(parsed.findings) == 3
    assert parsed.findings[0].severity == FindingSeverity.BLOCKER
    assert parsed.findings[1].severity == FindingSeverity.MAJOR
    assert parsed.findings[2].severity == FindingSeverity.MINOR


def test_parse_verdict_unfenced_with_subsequent_fenced_snippets():
    """Validates that unfenced verdict at start is preserved even if subsequent notes contain fenced code."""
    raw = (
        '{"verdict":"READY_TO_MERGE","summary":"Cambio limpio y verificado.","findings":[]}\n\n'
        'Notas adicionales para el equipo:\n'
        'Se recomienda en el próximo ciclo optimizar el siguiente bloque:\n'
        '```css\n'
        '.option-container {\n'
        '  display: flex;\n'
        '  gap: 1rem;\n'
        '}\n'
        '```\n'
        'Todo lo demás está aprobado.'
    )
    parsed = parse_review_verdict(raw)
    assert parsed.verdict == ReviewVerdict.READY_TO_MERGE
    assert parsed.findings == []
    assert parsed.summary == "Cambio limpio y verificado."


def test_parse_verdict_real_multiplo_deepseek_payload():
    """Validates the exact payload pattern emitted by DeepSeek on Multiplo run b0cbca1a."""
    raw = (
        '{"verdict":"CHANGES_REQUIRED",'
        '"summary":"La lógica del motor de preguntas es correcta y las pruebas pasan, pero la interfaz no oculta de verdad el botón Pista ni el botón Continuar porque el atributo hidden queda anulado por el display de CSS. Además, el historial local no tolera bien datos corruptos y algunas pruebas no comprueban la visibilidad real.",'
        '"findings":['
        '  {"severity":"MAJOR",'
        '   "location":"css/styles.css + js/app.js (renderCurrentQuestion) + index.html",'
        '   "violated_requirement":"El botón Pista y Continuar usan display: flex en .btn-option que anula hidden.",'
        '   "expected_correction":"Comprobar la visibilidad real (display/offsetParent) en los estados Pista y Continuar."}'
        ']}\n\n'
        'Análisis detallado de archivos:\n'
        '1. css/styles.css: los botones definen display: flex sin regla [hidden]...\n'
        '2. js/app.js: renderCurrentQuestion alterna el atributo hidden pero no inline display.'
    )
    parsed = parse_review_verdict(raw)
    assert parsed.verdict == ReviewVerdict.CHANGES_REQUIRED
    assert len(parsed.findings) == 1
    assert parsed.findings[0].severity == FindingSeverity.MAJOR
    assert "El botón Pista y Continuar" in parsed.findings[0].violated_requirement


def test_parse_verdict_rejects_malformed_syntax_fail_closed():
    """Validates that malformed JSON with broken syntax fails closed with MalformedReviewOutputError."""
    raw = '{"verdict":"READY_TO_MERGE", "summary": "unclosed string...'
    with pytest.raises(MalformedReviewOutputError) as exc_info:
        parse_review_verdict(raw)
    assert "Failed to parse valid structured review verdict" in str(exc_info.value) or "No structured verdict payload" in str(exc_info.value)


def test_parse_verdict_rejects_conflicting_verdicts_ambiguity():
    """Validates that ambiguous output with two verdict objects fails closed."""
    raw = (
        '{"verdict":"READY_TO_MERGE","summary":"OK 1","findings":[]}\n'
        '{"verdict":"CHANGES_REQUIRED","summary":"Wait, changes needed","findings":[{"severity":"MAJOR","location":"a.py","violated_requirement":"r","expected_correction":"c"}]}'
    )
    with pytest.raises(MalformedReviewOutputError) as exc_info:
        parse_review_verdict(raw)
    assert "Ambiguous reviewer output" in str(exc_info.value)
