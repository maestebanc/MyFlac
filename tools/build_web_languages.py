#!/usr/bin/env python3
"""
Genera las versiones estáticas de la web por idioma y el sitemap para los buscadores.

web/index.html (español) es la fuente; las traducciones viven en web/app.js. Este script escribe:
  - web/en/index.html y web/ca/index.html, ya traducidas (título, descripción, textos, datos
    estructurados, dirección canónica y Open Graph en su idioma);
  - web/sitemap.xml con las tres versiones enlazadas entre sí (hreflang).

Sin esto, los buscadores solo ven la página en español: el inglés y el catalán se aplicaban con
JavaScript sobre la misma dirección. Lo ejecuta el despliegue de GitHub Pages; en local:
    python3 tools/build_web_languages.py
"""
from __future__ import annotations

import datetime
import html
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
BASE_URL = "https://maestebanc.github.io/MyFlac/"
LANGS = {"es": "", "en": "en/", "ca": "ca/"}
OG_LOCALES = {"es": "es_ES", "en": "en_US", "ca": "ca_ES"}
# Textos alternativos de las capturas (también cuentan para la búsqueda de imágenes)
IMAGE_ALTS = {
    "en": {
        "MyFlac Ventana Principal": "MyFlac main window",
        "MyFlac Super-Reproductor a Pantalla Completa": "MyFlac fullscreen Super Player",
        "MyFlac Mini-Reproductor": "MyFlac Mini Player",
    },
    "ca": {
        "MyFlac Ventana Principal": "MyFlac finestra principal",
        "MyFlac Super-Reproductor a Pantalla Completa": "MyFlac Super-Reproductor a pantalla completa",
        "MyFlac Mini-Reproductor": "MyFlac Mini-Reproductor",
    },
}
_RELATIVE_ATTR = re.compile(r'(\s(?:href|src|data-src-dark|data-src-light)=")(?!https?:|#|mailto:|data:|/)([^"]*)"')


def load_translations(app_js: str) -> dict[str, dict[str, str]]:
    """Lee el objeto `translations` de app.js (claves con cadenas entre comillas dobles)."""
    block = app_js[app_js.index("const translations = {"):]
    block = block[:block.index("\n};\n")]
    result: dict[str, dict[str, str]] = {}
    current = None
    for line in block.splitlines():
        lang = re.match(r"^  (\w+): \{$", line)
        if lang:
            current = result.setdefault(lang.group(1), {})
            continue
        entry = re.match(r'^    (\w+): "((?:[^"\\]|\\.)*)",?$', line)
        if entry and current is not None:
            current[entry.group(1)] = json.loads(f'"{entry.group(2)}"')
    return result


def set_meta(page: str, attr: str, name: str, value: str) -> str:
    pattern = re.compile(rf'(<meta {attr}="{re.escape(name)}" content=")[^"]*(")')
    assert pattern.search(page), name
    return pattern.sub(lambda m: m.group(1) + html.escape(value, quote=True) + m.group(2), page, count=1)


def translate_page(source: str, lang: str, t: dict[str, str]) -> str:
    url = BASE_URL + LANGS[lang]
    page = re.sub(r'<html lang="es"', f'<html lang="{lang}"', source, count=1)

    # Textos marcados con data-i18n (la web los traducía con JavaScript sobre la marcha)
    def replace(match: re.Match) -> str:
        key = match.group(3)
        if key not in t:
            return match.group(0)
        return f"{match.group(1)}{html.escape(t[key], quote=False)}{match.group(4)}"

    page = re.sub(r'(<(\w+)[^>]*?\sdata-i18n="([^"]+)"[^>]*>).*?(</\2>)', replace, page, flags=re.S)

    title = t.get("page_title")
    description = t.get("meta_description")
    if title:
        page = re.sub(r"<title>.*?</title>", f"<title>{html.escape(title)}</title>", page, count=1)
        page = set_meta(page, "property", "og:title", title)
        page = set_meta(page, "name", "twitter:title", title)
    if description:
        page = set_meta(page, "name", "description", description)
        page = set_meta(page, "property", "og:description", description)
        page = set_meta(page, "name", "twitter:description", description)
    page = set_meta(page, "property", "og:locale", OG_LOCALES[lang])
    page = set_meta(page, "property", "og:url", url)
    page = set_meta(page, "name", "twitter:url", url)
    page = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', page, count=1)

    # Datos estructurados en el idioma de la página
    def jsonld(match: re.Match) -> str:
        data = json.loads(match.group(2))
        data["inLanguage"] = lang
        data["url"] = url
        if description:
            data["description"] = description
        return match.group(1) + "\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n  " + match.group(3)

    page = re.sub(r'(<script type="application/ld\+json">)(.*?)(</script>)', jsonld, page, count=1, flags=re.S)

    for old, new in IMAGE_ALTS.get(lang, {}).items():
        page = page.replace(f'alt="{old}"', f'alt="{html.escape(new, quote=True)}"')

    # La página vive un nivel más abajo: las rutas relativas suben uno ("en/" -> "../en/")
    return _RELATIVE_ATTR.sub(lambda m: f'{m.group(1)}../{"" if m.group(2) == "./" else m.group(2)}"', page)


def build_sitemap(today: str) -> str:
    alternates = "".join(
        f'\n    <xhtml:link rel="alternate" hreflang="{lang}" href="{BASE_URL}{path}"/>'
        for lang, path in LANGS.items()
    ) + f'\n    <xhtml:link rel="alternate" hreflang="x-default" href="{BASE_URL}en/"/>'
    urls = "".join(
        f"\n  <url>\n    <loc>{BASE_URL}{path}</loc>\n    <lastmod>{today}</lastmod>{alternates}\n  </url>"
        for path in LANGS.values()
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            f'xmlns:xhtml="http://www.w3.org/1999/xhtml">{urls}\n</urlset>\n')


def main() -> None:
    source = (WEB / "index.html").read_text(encoding="utf-8")
    translations = load_translations((WEB / "app.js").read_text(encoding="utf-8"))
    for lang, path in LANGS.items():
        if not path:
            continue
        out = WEB / path / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(translate_page(source, lang, translations[lang]), encoding="utf-8")
        print(f"Generada {out.relative_to(WEB.parent)}")
    (WEB / "sitemap.xml").write_text(build_sitemap(datetime.date.today().isoformat()), encoding="utf-8")
    print("Generado web/sitemap.xml")


if __name__ == "__main__":
    main()
