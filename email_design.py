"""Shared email presentation, usable by Flask, workers and standalone builders.

Only presentation is handled here. Recipients, attachments and delivery stay in
their existing workflows. Content passed to render_email is trusted application
HTML; callers must continue escaping recipient data.
"""
import re
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

PUBLIC_ASSETS = "https://gestionstagiaires-r5no.onrender.com"
_templates = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(("html",)),
)

# Retire the old green/purple action palette; retain warning and status colours.
_ACTION_COLOURS = {
    "#1f8f4a", "#178047", "#16a34a", "#2563eb", "#0b5ed7", "#4f46e5",
    "#4338ca", "#312e81", "#684293", "#087c86", "#2663ba", "#245ec2",
    "#2456b8", "#2360c4", "#3658d4", "#1d4ed8", "#6d28d9",
}


class _EmailStyles(HTMLParser):
    """Inline shared typography without changing text, URLs or table structure."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        style = dict(part.strip().split(":", 1) for part in (values.get("style") or "").split(";") if ":" in part)
        style = {key.strip().lower(): value.strip() for key, value in style.items()}
        defaults = {
            "p": {"margin": "0 0 18px", "line-height": "1.7"},
            "h2": {"font-size": "21px", "line-height": "1.35", "color": "#102c5c", "margin": "26px 0 14px"},
            "h3": {"font-size": "17px", "line-height": "1.4", "color": "#102c5c", "margin": "22px 0 12px"},
            "ul": {"padding-left": "22px", "margin": "0 0 20px"},
            "ol": {"padding-left": "22px", "margin": "0 0 20px"},
            "li": {"margin-bottom": "8px"},
            "a": {"color": "#285ac8", "overflow-wrap": "anywhere"},
            "img": {"max-width": "100%", "height": "auto", "border": "0"},
        }
        style = {**defaults.get(tag, {}), **style}
        for key, value in list(style.items()):
            if value.lower() in _ACTION_COLOURS:
                style[key] = "#285ac8"
            if key in {"animation", "transform", "box-shadow"}:
                del style[key]
        if tag == "a" and "padding" in style and style.get("display") in {"block", "inline-block"}:
            style.update({"background": "#285ac8", "color": "#ffffff", "border-radius": "10px",
                          "padding": "15px 24px", "font-size": "16px", "font-weight": "700",
                          "text-decoration": "none", "text-align": "center", "line-height": "1.45"})
        if values.get("bgcolor", "").lower() in _ACTION_COLOURS:
            values["bgcolor"] = "#285ac8"
        if style:
            values["style"] = ";".join(f"{key}:{value}" for key, value in style.items())
        attributes = "".join(f' {key}="{escape(value, quote=True)}"' if value is not None else f" {key}" for key, value in values.items())
        self.parts.append(f"<{tag}{attributes}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")


def style_fragment(content):
    parser = _EmailStyles()
    parser.feed(str(content or ""))
    parser.close()
    return Markup("".join(parser.parts))


def normalize_email_text_signature(content):
    """Retire the old sign-off in saved mail templates, preserving recipient names."""
    return re.sub(
        r"(?im)^Clément VAILLANT(?:[ \t]*[-–—·][ \t]*(?:Directeur[ \t]+)?Intégrale Academy|[ \t]*\nDirecteur(?: général)?[ \t]+Intégrale Academy(?:[ \t]*[-–—·][ \t]*Président Intégrale Group)?)[ \t]*$",
        "L’équipe Intégrale Academy", str(content or ""),
    )


def render_email(content, *, title="", eyebrow="VOTRE PARCOURS DE FORMATION",
                 subtitle="On avance avec vous.", preheader="", signature="team",
                 logo_url="", footer_text="", show_logo=True):
    content = str(content or "")
    # A heading formerly displayed above the greeting now belongs in the hero.
    heading = re.match(r"\s*<h[12]\b[^>]*>(.*?)</h[12]>\s*", content, re.I | re.S)
    if heading:
        if not title:
            title = unescape(re.sub(r"<[^>]+>", "", heading.group(1)))
            title = re.sub(r"^[^\wÀ-ÿ]+", "", title).strip()
        content = content[heading.end():]
    # Replace the legacy director signature only, preserving any preceding prose.
    director = r"(?:<strong>)?Clément VAILLANT(?:</strong>)?\s*<br\s*/?>\s*Directeur(?: général)?(?:\s*[·–—-])?\s*Intégrale (?:Academy|Sécurité Formations)(?:\s*[-–—·]\s*Président Intégrale Group)?"
    if re.search(director, content, re.I):
        content = re.sub(director, "", content, flags=re.I)
        content = re.sub(r"<p\b[^>]*>\s*</p>", "", content, flags=re.I)
        signature = "team"
    # Saved AFC templates may still contain a plain sign-off inside a paragraph.
    content = re.sub(r"<p\b[^>]*>\s*Clément VAILLANT\s*[-–—·]\s*Intégrale Academy\s*</p>", "", content, flags=re.I)
    # The common signature also replaces the old plain-text team sign-off.
    content = re.sub(r"(?:<br\s*/?>\s*)?(?:<strong>)?L[’']équipe Intégrale Academy(?:</strong>)?(?=\s*</(?:p|td)>)", "", content, flags=re.I)
    content = re.sub(r"<p\b[^>]*>\s*</p>", "", content, flags=re.I)
    title = title or "Votre formation, à vos côtés"
    return _templates.get_template("emails/_message.html").render(
        content=style_fragment(content), email_heading=title, email_eyebrow=eyebrow,
        email_subtitle=subtitle, email_preheader=preheader or title,
        email_signature=signature, email_logo=logo_url, email_show_logo=show_logo,
        email_footer_note=footer_text, email_base_url=PUBLIC_ASSETS,
    )
