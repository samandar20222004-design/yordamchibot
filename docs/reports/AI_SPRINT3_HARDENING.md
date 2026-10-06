# Sprint 3 — AI quality and trust boundaries

## Changes

- Add dataclass contracts `PostResult`, `AuditResult`, `PlanResult`. Strict parsing
  rejects missing fields, incorrect list members, bool-as-score and scores outside
  0–100. Fail-soft parsing retains safe prose without inventing audit evidence or
  calendar days. Fallback values are **not** evidence of successful validation.
- `PromptEngine.build` composes system → language → task → channel context → user
  request → output schema. User/channel/RSS content is HTML-escaped inside
  `untrusted_input`; literal closing-tag injection cannot break the boundary.
- Wire envelopes into canonical generation, legacy fallback, real orchestrator
  adapters and vision requests. Existing feature-specific task instructions stay
  in place; no handlers or existing contracts are rewritten.
- Reject model-identity/internal-instruction leaks, recognizable API credentials
  and configured secret values. Sanitize dangerous HTML and Markdown links.
  Legacy payloads are checked recursively before returning; leaking candidates
  receive one retry within the original provider deadline.
- Validate real gateway provider output for repetition, empty/sparse content,
  promotional filler and obvious language mismatch. Typed gateway calls enforce
  required fields as well. One quality retry → next healthy provider → localized
  safe failure; rejected output is not cached. Network failures fall through
  directly. Existing orchestrator uses the strengthened shared validator.

## Typed API

```python
from services.ai_engine import generate_post, PostResult

result = await generate_post(topic, lang="uz", channel_context=channel_samples)
if result.ok:
    post = result.structured_result(PostResult)
    # post.hook / post.body / post.cta / post.tags / post.raw_html
```

`audit()` and `plan()` select their corresponding schemas. Existing
`generate(..., schema=...)` also supports explicit contracts. Cache keys include
schema instructions and channel context through the composed prompt.

## Compatibility and security limits

- Existing legacy audit/calendar handlers have different, richer JSON contracts
  (including local deterministic scores). They are retained rather than silently
  reinterpreted as the new models. Strict new contracts are used by the typed API;
  legacy fallback keeps its payload shape and adds leak/sanitization protection.
  It does not impose the new post schema on those legacy responses.
- Language checks are conservative offline heuristics for Uzbek/Russian/English,
  not proof of semantic correctness. Short code-switched prose can be ambiguous.
- Delimiters and leak patterns are defence in depth, not a guarantee that an LLM
  can never follow injected instructions. Never place credentials in prompts.
  Arbitrary paraphrased instructions or transformed secrets cannot be exhaustively
  recognized by regex. Application-provided `system` and `task` must be trusted.
- No live providers or live PostgreSQL were required for regression tests.

## Verification

New offline test suite: `tests/ai_quality_and_prompt_engine_test.py`, included in
`tests/run_tests.sh`. Tests exercise actual provider-boundary validation with fake
provider handles, typed parsing, injection delimiters, leaks, language mismatch,
HTML/Markdown sanitation, exactly one retry, fallback, cache and safe failure.
Existing tests were not modified.

Command: `PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh`

Final full regression result: **BASH EXIT CODE: 0**. `git diff --check` also passed.
