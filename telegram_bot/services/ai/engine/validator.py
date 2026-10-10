"""Quality checks shared by typed gateway and legacy text validation."""
from dataclasses import asdict, dataclass
import html
import re
from .schemas import PostResult, AuditResult, PlanResult, parse_result
from .safety import contains_leak, sanitize


class OutputQualityError(ValueError):
    """Only quality failures may be retried once on the same provider."""


@dataclass
class QualityResult:
    is_valid: bool
    text: str = ''
    value: object = None
    error_code: str | None = None


def quality_error(text: str, lang: str | None = None) -> str | None:
    if contains_leak(text):
        return 'PROMPT_LEAK'
    plain = html.unescape(re.sub('<[^>]*>', '', text)).lower()
    words = re.findall(r"[^\W\d_]+", plain)
    if len(set(words)) < 4 or (len(words) > 20 and len(set(words)) / len(words) < .15):
        return 'THIN_OUTPUT'
    if any(p in plain for p in ("kanalga obuna bo'ling", 'biz eng yaxshimiz', 'we are the best')):
        return 'FLUFF_OUTPUT'
    en = sum(w in {'the', 'with', 'your', 'this', 'and', 'for', 'you'} for w in words)
    uz = sum(w in {'uchun', 'bilan', 'siz', 'yangi', 'orqali', 'kerak', 'va'} for w in words)
    cyr = len(re.findall('[а-яё]', plain)) / max(1, sum(c.isalpha() for c in plain))
    if ((lang == 'uz' and (cyr > .6 or (en >= 3 and uz == 0))) or
        (lang == 'en' and (cyr > .15 or (uz >= 3 and en == 0))) or
        (lang == 'ru' and cyr < .35)):
        return 'LANGUAGE_MISMATCH'
    return None


def validate_output(text: str, *, lang: str | None = None, schema=None) -> QualityResult:
    if contains_leak(text):
        return QualityResult(False, error_code='PROMPT_LEAK')
    value = None
    if schema:
        try:
            value = parse_result(text, schema, strict=True)
        except ValueError:
            return QualityResult(False, error_code='INVALID_SCHEMA')
        if isinstance(value, PostResult):
            if not all((value.hook.strip(), value.body.strip(), value.cta.strip(), value.raw_html.strip())):
                return QualityResult(False, error_code='INVALID_SCHEMA')
            prose = value.hook + ' ' + value.body + ' ' + value.cta
        elif isinstance(value, AuditResult):
            if not value.suggestions or not (value.strengths or value.weaknesses):
                return QualityResult(False, error_code='INVALID_SCHEMA')
            prose = ' '.join(value.strengths + value.weaknesses + value.suggestions)
        else:
            if not value.days or not all(d and all(isinstance(k, str) for k in d) for d in value.days):
                return QualityResult(False, error_code='INVALID_SCHEMA')
            prose = value.summary
    else:
        prose = text
    error = quality_error(prose, lang)
    if error:
        return QualityResult(False, error_code=error)
    if value:
        def clean(item):
            if isinstance(item, str): return sanitize(item)
            if isinstance(item, list): return [clean(x) for x in item]
            if isinstance(item, dict): return {k: clean(v) for k, v in item.items()}
            return item
        import json
        value = schema(**clean(asdict(value)))
        return QualityResult(True, json.dumps(asdict(value), ensure_ascii=False), value)
    return QualityResult(True, sanitize(text))
