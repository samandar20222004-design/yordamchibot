"""Typed AI contracts; tolerant transport parsing never implies quality approval."""
from dataclasses import dataclass, fields
import json
import re


@dataclass
class PostResult:
    hook: str
    body: str
    cta: str
    tags: list[str]
    raw_html: str


@dataclass
class AuditResult:
    score: int
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]


@dataclass
class PlanResult:
    days: list[dict]
    summary: str


def parse_result(text: str, model=PostResult, *, strict: bool = False):
    """Strict mode rejects missing/wrong fields; fallback preserves prose, not scores."""
    from .safety import contains_leak, sanitize
    if contains_leak(text):
        if strict:
            raise ValueError('unsafe output')
        text = ''
    source = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
    try:
        data = json.loads(source)
        if not isinstance(data, dict):
            raise ValueError('object required')
        values = {}
        for field in fields(model):
            value = data[field.name]
            if field.type == str:
                valid = isinstance(value, str)
            elif field.type == int:
                valid = type(value) is int and 0 <= value <= 100
            else:
                item_type = dict if field.name == 'days' else str
                valid = isinstance(value, list) and all(isinstance(x, item_type) for x in value)
            if not valid:
                raise ValueError('invalid field type')
            values[field.name] = value
        def clean(value):
            if isinstance(value, str):
                return sanitize(value)
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            return value
        return model(**clean(values))
    except (ValueError, TypeError, KeyError):
        if strict:
            raise ValueError('invalid output schema') from None
        from .safety import contains_leak, sanitize
        safe = '' if contains_leak(text) else sanitize(text)
        if model is PostResult:
            paragraphs = [p.strip() for p in safe.split('\n\n') if p.strip()]
            return PostResult(paragraphs[0] if len(paragraphs) > 1 else '',
                              '\n\n'.join(paragraphs[1:]) if len(paragraphs) > 1 else safe,
                              '', re.findall(r'#[\w]+', safe), safe)
        if model is AuditResult:
            return AuditResult(0, [], [], [safe] if safe else [])
        return PlanResult([], safe)
