"""Formatierter Text (Feldtyp HTML) und Berichte aus n8n, Teams-Workflows und Copilot.

Beim Speichern wird das HTML bereinigt (sanitize.py). Eingebettete Bilder als data:-Adresse
(z. B. ein Diagramm, das ein n8n-Agent als PNG erzeugt) speichert der Baukasten selbst
(Modell Attachment) und ersetzt sie durch eine eigene Adresse. Bilder von https-Adressen
bleiben Links; heruntergeladen wird nichts.

report_from_payload() übersetzt die üblichen Formate in (Titel, HTML, weitere Werte):
HTML oder Text/Markdown, Teams-Webhook ({"text": …}), MessageCard, Adaptive Card
(auch als Teams-Nachricht mit attachments) und Graph-Nachrichten (body + hostedContents).
"""
import base64
import binascii
import hashlib
import re
from html import escape
from html.parser import HTMLParser

from django.urls import reverse
from markdown import markdown

from .sanitize import sanitize_html

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 30
# Erkannt wird am Inhalt, nicht an der Angabe des Absenders. SVG fehlt mit Absicht:
# Es kann Skripte enthalten und liefe unter der Adresse des Baukastens.
IMAGE_TYPES = (
    ("image/png", "png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    ("image/jpeg", "jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    ("image/gif", "gif", lambda b: b[:6] in (b"GIF87a", b"GIF89a")),
    ("image/webp", "webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
)
DATA_URI = re.compile(
    r"""(?P<attr>\bsrc\s*=\s*)(?P<q>["']?)data:image/[a-z0-9.+-]+;base64,(?P<data>[A-Za-z0-9+/=\s]+)(?P=q)""",
    re.IGNORECASE,
)
HTML_HINT = re.compile(r"<\s*(p|br|div|span|b|strong|i|em|u|ul|ol|li|h[1-6]|table|tr|img|a|hr|pre|code|blockquote)\b",
                       re.IGNORECASE)
MARKDOWN_EXTENSIONS = ["tables", "sane_lists", "nl2br", "fenced_code"]


# ---------- Bilder ----------

def image_type(data):
    for content_type, ext, check in IMAGE_TYPES:
        if check(data):
            return content_type, ext
    return None, None


def attachment_url(attachment):
    _type, ext = image_type(bytes(attachment.data[:12]))
    return reverse("attachment", args=[attachment.app.slug, f"{attachment.sha256}.{ext or 'bin'}"])


def store_image(app, data):
    """Speichert ein Bild (Bytes) für die App und gibt seine Adresse zurück, sonst None."""
    from .models import Attachment

    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    content_type, _ext = image_type(data)
    if content_type is None:
        return None
    digest = hashlib.sha256(data).hexdigest()
    attachment, _created = Attachment.objects.get_or_create(
        app=app, sha256=digest, defaults={"content_type": content_type, "data": data, "size": len(data)},
    )
    return attachment_url(attachment)


def store_data_images(raw, app):
    """Ersetzt eingebettete Bilder (src="data:image/…;base64,…") durch gespeicherte Bilder.

    Was kein erkennbares Bild ist oder zu groß, verliert seine Adresse; der Sanitizer
    entfernt data:-Adressen ohnehin."""
    count = 0

    def replace(match):
        nonlocal count
        url = None
        if app is not None and count < MAX_IMAGES:
            try:
                data = base64.b64decode(re.sub(r"\s+", "", match.group("data")), validate=True)
            except (binascii.Error, ValueError):
                data = b""
            url = store_image(app, data)
            if url:
                count += 1
        return f'{match.group("attr")}"{url or ""}"'

    return DATA_URI.sub(replace, raw or "")


def prepare_html(raw, app=None):
    """Bilder speichern und bereinigen: so landet formatierter Text in der Datenbank."""
    return sanitize_html(store_data_images(raw, app)).strip()


# ---------- Anzeige ----------

BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol",
              "blockquote", "pre", "hr", "section", "figure", "dt", "dd"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f" [{alt}] ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(self.skip - 1, 0)
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(value, limit=None):
    """Reiner Text aus HTML, z. B. für Listen, Suche und die Überschrift eines Berichts."""
    parser = _Text()
    parser.feed(str(value or ""))
    parser.close()
    text = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


# ---------- Text, Markdown, HTML ----------

def to_html(text):
    """HTML bleibt HTML; alles andere gilt als Text mit Markdown, wie ihn Teams versteht."""
    text = str(text or "")
    if not text.strip():
        return ""
    if HTML_HINT.search(text):
        return text
    return markdown(text, extensions=MARKDOWN_EXTENSIONS)


def _inline(text):
    """Kurzer Text (Überschrift, Fakt) mit Markdown, ohne umschließenden Absatz."""
    html = to_html(text).strip()
    match = re.fullmatch(r"<p>(.*)</p>", html, re.DOTALL)
    return match.group(1) if match else html


def _img(url, alt=""):
    url = str(url or "").strip()
    if not url:
        return ""
    return f'<img src="{escape(url, quote=True)}" alt="{escape(str(alt or ""), quote=True)}">'


def _link(url, label):
    url = str(url or "").strip()
    if not url:
        return ""
    return f'<p><a href="{escape(url, quote=True)}">{escape(str(label or url))}</a></p>'


def _facts(rows):
    cells = "".join(f"<tr><th>{_inline(k)}</th><td>{_inline(v)}</td></tr>" for k, v in rows)
    return f'<table class="facts">{cells}</table>' if cells else ""


# ---------- Adaptive Cards ----------

def _card_actions(actions):
    out = []
    for action in actions or []:
        if isinstance(action, dict) and action.get("type") == "Action.OpenUrl":
            out.append(_link(action.get("url"), action.get("title")))
    return "".join(out)


def adaptive_card_html(card):
    """Die üblichen Elemente einer Adaptive Card als HTML. Unbekanntes wird übersprungen."""
    if not isinstance(card, dict):
        return ""
    return _card_elements(card.get("body")) + _card_actions(card.get("actions"))


def _card_elements(elements, depth=0):
    if depth > 8 or not isinstance(elements, list):
        return ""
    return "".join(_card_element(e, depth) for e in elements if isinstance(e, dict))


def _card_element(e, depth):
    kind = e.get("type")
    if kind == "TextBlock":
        text = e.get("text", "")
        if e.get("style") == "heading" or e.get("size") in ("large", "extraLarge"):
            return f"<h3>{_inline(text)}</h3>"
        if e.get("weight") == "bolder":
            return f"<p><strong>{_inline(text)}</strong></p>"
        return to_html(text)
    if kind == "RichTextBlock":
        runs = []
        for run in e.get("inlines") or []:
            text = run.get("text", "") if isinstance(run, dict) else str(run)
            piece = escape(text)
            if isinstance(run, dict):
                if run.get("weight") == "bolder":
                    piece = f"<strong>{piece}</strong>"
                if run.get("italic"):
                    piece = f"<em>{piece}</em>"
            runs.append(piece)
        return f"<p>{''.join(runs)}</p>"
    if kind == "Image":
        return f"<p>{_img(e.get('url'), e.get('altText'))}</p>"
    if kind == "ImageSet":
        return "<p>" + "".join(_img(i.get("url"), i.get("altText")) for i in e.get("images") or []
                               if isinstance(i, dict)) + "</p>"
    if kind == "FactSet":
        return _facts((f.get("title", ""), f.get("value", "")) for f in e.get("facts") or [] if isinstance(f, dict))
    if kind in ("Container", "Column"):
        return f"<div>{_card_elements(e.get('items'), depth + 1)}</div>"
    if kind == "ColumnSet":
        return "".join(f"<div>{_card_elements(c.get('items'), depth + 1)}</div>"
                       for c in e.get("columns") or [] if isinstance(c, dict))
    if kind == "Table":
        rows = []
        for row in e.get("rows") or []:
            if not isinstance(row, dict):
                continue
            cells = "".join(f"<td>{_card_elements(c.get('items'), depth + 1)}</td>"
                            for c in row.get("cells") or [] if isinstance(c, dict))
            rows.append(f"<tr>{cells}</tr>")
        return f"<table>{''.join(rows)}</table>"
    if kind == "ActionSet":
        return _card_actions(e.get("actions"))
    return ""


# ---------- MessageCard (alte Teams-Connectoren) ----------

def message_card_html(card):
    parts = []
    if card.get("text"):
        parts.append(to_html(card["text"]))
    for section in card.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if section.get("activityTitle"):
            parts.append(f"<h3>{_inline(section['activityTitle'])}</h3>")
        for key in ("activitySubtitle", "activityText", "text"):
            if section.get(key):
                parts.append(to_html(section[key]))
        hero = section.get("heroImage")
        if isinstance(hero, dict):
            parts.append(f"<p>{_img(hero.get('image'), hero.get('title'))}</p>")
        parts.append(_facts((f.get("name", ""), f.get("value", ""))
                            for f in section.get("facts") or [] if isinstance(f, dict)))
        images = [i for i in section.get("images") or [] if isinstance(i, dict)]
        if images:
            parts.append("<p>" + "".join(_img(i.get("image"), i.get("title")) for i in images) + "</p>")
    for action in card.get("potentialAction") or []:
        if isinstance(action, dict) and action.get("@type") == "OpenUri":
            target = next((t.get("uri") for t in action.get("targets") or [] if isinstance(t, dict)), "")
            parts.append(_link(target, action.get("name")))
    return "".join(parts)


# ---------- Graph-Nachricht (Teams-Kanal, n8n-Teams-Knoten) ----------

def _graph_body(payload):
    body = payload.get("body")
    content = str(body.get("content") or "")
    if str(body.get("contentType") or "html").lower() == "text":
        content = to_html(content)
    # Bilder, die mit der Nachricht kommen: <img src="../hostedContents/1/$value">
    for hosted in payload.get("hostedContents") or []:
        if not isinstance(hosted, dict):
            continue
        temp_id = str(hosted.get("@microsoft.graph.temporaryId") or "")
        data = str(hosted.get("contentBytes") or "")
        if temp_id and data:
            content = re.sub(r"\.\./hostedContents/" + re.escape(temp_id) + r"/\$value",
                             f"data:{hosted.get('contentType') or 'image/png'};base64,{data}", content)
    return content


# ---------- Eingang ----------

TITLE_KEYS = ("titel", "title", "subject", "betreff", "summary")
CONTENT_KEYS = ("html", "inhalt", "content", "text", "nachricht", "message")


def report_from_payload(payload):
    """Übersetzt eine eingehende Nachricht in (Titel, HTML). Gibt ("", "") bei leerem Inhalt."""
    if not isinstance(payload, dict):
        return "", ""
    parts = []
    if isinstance(payload.get("body"), dict) and "content" in payload["body"]:
        parts.append(_graph_body(payload))
    if payload.get("type") == "AdaptiveCard":
        parts.append(adaptive_card_html(payload))
    if payload.get("@type") == "MessageCard" or isinstance(payload.get("sections"), list):
        parts.append(message_card_html(payload))
    elif not parts:
        content = next((payload[k] for k in CONTENT_KEYS if isinstance(payload.get(k), str) and payload[k].strip()), "")
        parts.append(to_html(content))
    for attachment in payload.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        content = attachment.get("content")
        if "adaptive" in str(attachment.get("contentType") or "") and isinstance(content, dict):
            parts.append(adaptive_card_html(content))
        elif isinstance(content, str):
            parts.append(to_html(content))
    title = next((str(payload[k]).strip() for k in TITLE_KEYS
                  if isinstance(payload.get(k), str) and payload[k].strip()), "")
    return title, "".join(p for p in parts if p)


def title_from_html(html, limit=120):
    """Überschrift aus dem Inhalt, wenn der Absender keine mitschickt."""
    match = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", html or "", re.IGNORECASE | re.DOTALL)
    return html_to_text(match.group(1) if match else html, limit)


def split_report(payload, limit=200):
    """(Titel, HTML) für einen Bericht. Ohne mitgeschickten Titel wird eine Überschrift am Anfang
    zum Titel und aus dem Inhalt genommen, damit sie im Feed nicht doppelt steht."""
    title, html = report_from_payload(payload)
    if not title:
        match = re.match(r"\s*<h[1-6][^>]*>(.*?)</h[1-6]>", html, re.IGNORECASE | re.DOTALL)
        if match and html_to_text(html[match.end():]):
            return html_to_text(match.group(1), limit), html[match.end():].lstrip()
        title = title_from_html(html, limit)
    return title[:limit], html
