"""📋 POST SHABLONLARI xizmat qatlami (PostAssist V2 — PHASE C, 9-band).

Shablon — takroriy ishlatiladigan post matni, ichida o'zgaruvchilar::

    {TITLE}, {TEXT}, {PRICE}, {LINK}, {CTA}, {SOURCE}, {DATE}

Modullar:
    * :mod:`services.templates.service` — PURE render mantig'i
      (o'zgaruvchini aniqlash/almashtirish) + DB CRUD wapper'lari
      (IDOR himoyasi bilan);

Jadval: ``post_templates`` (id, user_id, channel_id, name, content,
variables JSONB, created_at) — ``database.py`` da yaratiladi va
``schema.sql`` bilan parallel yuritiladi.
"""

from services.templates.service import (  # noqa: F401
    DATE_DEFAULT_FORMAT,
    TEMPLATE_VARIABLES,
    extract_variables,
    parse_variable_values,
    render_template,
    validate_template_content,
)

__all__ = [
    "DATE_DEFAULT_FORMAT",
    "TEMPLATE_VARIABLES",
    "extract_variables",
    "parse_variable_values",
    "render_template",
    "validate_template_content",
]
