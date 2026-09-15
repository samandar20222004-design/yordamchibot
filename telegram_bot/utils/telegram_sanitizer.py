"""Single source of truth for Telegram HTML. Standard library only.

sanitize_html preserves supported formatting; escape_html is for *literal*
values interpolated into templates. Do not interchange those two contracts.
Limits count decoded UTF-16 units (conservative for astral emoji), not markup
bytes. Unknown/malformed markup is displayed literally, never sent as a tag.
"""
from html import escape, unescape
from html.parser import HTMLParser
import re

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
ALLOWED_TAGS = frozenset({
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span",
    "tg-spoiler", "a", "code", "pre", "blockquote",
})
_ALIASES = {"strong": "b", "em": "i", "ins": "u", "strike": "s", "del": "s"}
_STYLE_TAGS = frozenset({"b", "i", "u", "s", "span", "tg-spoiler"})
_TAG_HINT = re.compile(r"</?([a-z][a-z0-9-]*)\b", re.I)
_LANGUAGE = re.compile(r"language-[a-zA-Z0-9_+.-]{1,64}\Z")


def _string(value):
    return "" if value is None else str(value)


def _unicode(text):
    # Surrogates are not valid UTF-8; NUL is not a valid Telegram character.
    return "".join("\ufffd" if (ord(c) < 32 and c not in "\n\r\t") or 0xD800 <= ord(c) <= 0xDFFF else c
                   for c in text)


def utf16_length(text):
    return sum(2 if ord(c) > 0xFFFF else 1 for c in _string(text))


def truncate_text(text, max_length=TELEGRAM_TEXT_LIMIT):
    """Limit literal text without splitting a Unicode code point."""
    text = _unicode(_string(text))
    if max_length is None or max_length < 0:
        return text
    used = 0
    for i, char in enumerate(text):
        used += 2 if ord(char) > 0xFFFF else 1
        if used > max_length:
            return text[:i]
    return text


def escape_html(text):
    """Escape a literal value, including quotes (legacy security contract)."""
    return escape(_unicode(_string(text)), quote=True)


def escape_html_limited(text, max_length=None):
    """Legacy serialized-length budget, but never cut an entity in half.

    If the next escaped character does not fit, fill the remaining (at most
    five) positions with dots. New post code should use sanitize_html instead,
    whose budget is the Telegram decoded-text limit.
    """
    if max_length is None or max_length < 0:
        return escape_html(text)
    out, used = [], 0
    for char in _unicode(_string(text)):
        item = escape(char, quote=True)
        if used + len(item) > max_length:
            out.append("." * (max_length - used))
            break
        out.append(item)
        used += len(item)
    return "".join(out)


class _LimitReached(Exception):
    pass


class _Sanitizer(HTMLParser):
    def __init__(self, max_length):
        super().__init__(convert_charrefs=False)
        # script/style contents must also pass through normal entity handling.
        self.CDATA_CONTENT_ELEMENTS = ()
        self.limit = max_length
        self.used = 0
        self.out = []
        # Both emitted and flattened tags get a frame: a rejected nested tag
        # must never close an accepted outer tag with the same name.
        self.stack = []
        self.plain = []

    def handle_data(self, data):
        data = _unicode(data)
        if self.limit is not None:
            piece = truncate_text(data, max(0, self.limit - self.used))
        else:
            piece = data
        self.used += utf16_length(piece)
        self.out.append(escape(piece, quote=False))
        self.plain.append(piece)
        if len(piece) < len(data):
            raise _LimitReached

    def handle_entityref(self, name):
        self.handle_data(unescape("&" + name + ";"))

    def handle_charref(self, name):
        self.handle_data(unescape("&#" + name + ";"))

    def handle_comment(self, data):
        self.handle_data("<!--" + data + "-->")

    def handle_decl(self, decl):
        self.handle_data("<!" + decl + ">")

    def unknown_decl(self, data):
        self.handle_data("<![" + data + "]>")

    def handle_pi(self, data):
        self.handle_data("<?" + data + ">")

    def _close(self):
        _, emitted = self.stack.pop()
        if emitted:
            self.out.append(f"</{emitted}>")

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if tag not in ALLOWED_TAGS or len(self.stack) >= 64:
            self.handle_data(raw)
            return
        name = _ALIASES.get(tag, tag)
        attributes = dict(attrs)
        suffix = ""
        if tag == "span":
            if attributes.get("class") != "tg-spoiler":
                self.handle_data(raw)
                return
            suffix = ' class="tg-spoiler"'
        elif tag == "a":
            # Lazy import avoids security <-> sanitizer initialization cycles.
            from utils.security import validate_button_url
            href = attributes.get("href") or ""
            if not validate_button_url(href):
                self.handle_data(raw)
                return
            suffix = f' href="{escape(href.strip(), quote=True)}"'
        elif tag == "blockquote" and "expandable" in attributes:
            suffix = " expandable"
        elif tag == "code" and self.stack and self.stack[-1][1] == "pre":
            language = attributes.get("class") or ""
            if _LANGUAGE.fullmatch(language):
                suffix = f' class="{language}"'

        active = [emitted for _, emitted in self.stack if emitted]
        # Telegram code/pre entities cannot overlap formatting. Keep the
        # text and flatten incompatible nested tags; pre > code is special.
        flatten = (
            name in active
            or (any(t in ("code", "pre") for t in active)
                and not (active == ["pre"] and name == "code"))
            or (name in ("code", "pre") and bool(active)
                and not (active == ["pre"] and name == "code"))
            or (name not in _STYLE_TAGS
                and any(t not in _STYLE_TAGS for t in active)
                and not (active == ["pre"] and name == "code"))
        )
        if flatten:
            self.stack.append((name, None))
        else:
            self.out.append(f"<{name}{suffix}>")
            self.stack.append((name, name))

    def handle_startendtag(self, tag, attrs):
        depth = len(self.stack)
        self.handle_starttag(tag, attrs)
        if len(self.stack) > depth:
            self._close()

    def handle_endtag(self, tag):
        name = _ALIASES.get(tag, tag)
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == name:
                while len(self.stack) > index:
                    self._close()
                return
        self.handle_data(f"</{tag}>")


def _parse(text, max_length):
    raw = _unicode(_string(text))
    limit = None if max_length is None or max_length < 0 else int(max_length)
    parser = _Sanitizer(limit)
    try:
        parser.feed(raw)
        parser.close()
    except _LimitReached:
        pass
    except (AssertionError, ValueError):
        # HTMLParser can reject malformed declarations. Fail closed to text,
        # never return the original unsafe fragment.
        parser = _Sanitizer(limit)
        try:
            parser.handle_data(raw)
        except _LimitReached:
            pass
    while parser.stack:
        parser._close()
    return parser


def sanitize_html(text, max_length=TELEGRAM_TEXT_LIMIT):
    """Balance, whitelist, escape and truncate; safe to apply repeatedly.

    None (or a negative limit) means unlimited, for composing fragments before
    the final request-boundary pass. No ellipsis is added to published posts.
    """
    return "".join(_parse(text, max_length).out)


def html_to_text(text, max_length=None):
    """Visible sanitized text, suitable for a parse_mode=None fallback."""
    return "".join(_parse(text, max_length).plain)


def html_length(text):
    return utf16_length(html_to_text(text))


def has_allowed_html(text):
    return any(m.group(1).lower() in ALLOWED_TAGS
               for m in _TAG_HINT.finditer(_string(text)))


def telegram_html_payload(text, max_length=TELEGRAM_TEXT_LIMIT):
    """Legacy (payload, parse_mode) contract; plain input stays plain."""
    raw = _string(text)
    if has_allowed_html(raw):
        return sanitize_html(raw, max_length), "HTML"
    return truncate_text(raw, max_length), None


safe_html = sanitize_html
html_escape = escape_html
