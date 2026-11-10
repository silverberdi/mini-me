## Context

See `proposal.md` for motivation. Reviewer agents (such as DeepSeek) output structured verdicts conforming to `ReviewVerdictPayload`. While verdict-first prompting places JSON at the beginning of the response, finding details often quote code snippets, CSS rules, and structured data with arbitrary nesting and curly braces.

## Goals / Non-Goals

**Goals:**
- Replace the fragile single-level nested regex (`brace_pattern`) in `review_verdict_parser.py` with standard library `json.JSONDecoder().raw_decode`.
- Robustly support arbitrarily nested JSON structures, quoted curly braces in strings (e.g. CSS rules, JS code), and multiple findings without token corruption or false rejection.
- Preserve full backward compatibility with markdown code fence extraction and strict fail-closed validation.

**Non-Goals:**
- Relax schema requirements: `verdict`, `findings`, `location`, `violated_requirement`, and `expected_correction` remain strictly required and validated.
- Change the downstream orchestration flow: `READY_TO_MERGE` and `CHANGES_REQUIRED` transitions remain unchanged.

## Decisions

### Decision 1: Use `json.JSONDecoder().raw_decode` over Regex for Unfenced JSON
*Rationale*: Standard regular expressions cannot handle context-free grammars like balanced nested brackets and escaped strings. `json.JSONDecoder().raw_decode` is built into Python's standard library, handles full JSON grammar (including string escapes, comments, and deep nesting), and stops at the precise character offset where the JSON object ends.
*Alternative considered*: Third-party parsing libraries (rejected: adds unnecessary dependency violating KISS/YAGNI). Extended regex recursive patterns (rejected: fragile and unmaintainable).

### Decision 2: Prioritize Root-Level Candidates Containing `"verdict"`
*Rationale*: A response might contain commentary or ancillary JSON blocks. Scanning for `{` and decoding with `raw_decode` ensures we find candidate dictionaries. Only dictionaries containing the key `"verdict"` are considered as potential verdict payloads.
*Alternative considered*: Parsing only `text.strip()` as a single JSON document (rejected: reviewers often include markdown narrative notes after the JSON block).

## Risks / Trade-offs

- [Risk]: Scanning large outputs with `raw_decode` at each `{` index.
  → Mitigation: Once a valid JSON dictionary is decoded at index `i` extending to index `i + end`, skip `i` forward by `end` characters to avoid inspecting internal sub-objects.
