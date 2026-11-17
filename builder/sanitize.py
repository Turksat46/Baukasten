"""Bereinigt HTML eigener Bausteine.

Erlaubt ist eine feste Liste von Tags und Attributen. Skripte, Ereignis-Attribute
(onclick …), eingebettete Fremdinhalte und gefährliche Adressen werden entfernt.
"""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED_TAGS = {
    "div", "span", "p", "h1", "h2", "h3", "h4", "strong", "em", "b", "i", "u", "small", "br", "hr",
    "ul", "ol", "li", "a", "img", "table", "thead", "tbody", "tr", "th", "td", "code", "pre",
    "blockquote", "section", "figure", "figcaption", "dl", "dt", "dd",
}
VOID_TAGS = {"br", "hr", "img"}
# Inhalt dieser Tags wird vollständig verworfen, nicht nur das Tag selbst.
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "noscript", "svg", "math"}
ALLOWED_ATTRS = {
    "*": {"class", "title", "style"},
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
URL_ATTRS = {"href", "src"}
SAFE_URL = re.compile(r"^(https://|/(?!/)|mailto:|#)", re.IGNORECASE)
UNSAFE_STYLE = re.compile(r"url\s*\(|expression|@import|javascript:|behavior|position\s*:\s*fixed", re.IGNORECASE)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.dropping = 0
        self.open_tags = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.dropping += 1
            return
        if self.dropping or tag not in ALLOWED_TAGS:
            return
        allowed = ALLOWED_ATTRS["*"] | ALLOWED_ATTRS.get(tag, set())
        parts = []
        for name, value in attrs:
            value = value or ""
            if name not in allowed:
                continue
            if name in URL_ATTRS and not SAFE_URL.match(value.strip()):
                continue
            if name == "style" and UNSAFE_STYLE.search(value):
                continue
            parts.append(f' {name}="{escape(value, quote=True)}"')
        if tag == "a":
            parts.append(' rel="noopener"')
        self.out.append(f"<{tag}{''.join(parts)}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in DROP_WITH_CONTENT:
            self.dropping = max(self.dropping - 1, 0)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.dropping = max(self.dropping - 1, 0)
            return
        if self.dropping or tag not in self.open_tags:
            return
        # Schließt auch vergessene innere Tags, damit das Seitenlayout nicht bricht.
        while self.open_tags:
            current = self.open_tags.pop()
            self.out.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(escape(data, quote=False))

    def result(self):
        while self.open_tags:
            self.out.append(f"</{self.open_tags.pop()}>")
        return "".join(self.out)


def sanitize_html(html):
    parser = _Sanitizer()
    parser.feed(html or "")
    parser.close()
    return parser.result()


PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


def fill_placeholders(html, values):
    """Ersetzt {{ name }} durch den maskierten Wert; unbekannte Platzhalter werden leer."""
    return PLACEHOLDER.sub(lambda m: escape(str(values.get(m.group(1), "")), quote=True), html or "")
