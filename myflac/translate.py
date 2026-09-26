"""
Traducción al español y al catalán de la información en inglés de Discogs y Wikipedia:
- Términos fijos de Discogs (roles de créditos, géneros, estilos, formatos y países) con un
  diccionario propio: instantáneo, sin conexión y sin errores de contexto.
- Textos libres (perfiles, notas de edición, entradillas en inglés) con traducción automática:
  Google Traductor (acceso web sin clave) y, si no responde, MyMemory. Se cachea en disco.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.parse
import urllib.request

from gi.repository import GLib

from .logger import get_logger

log = get_logger("translate")

USER_AGENT = "MyFlac/0.1.0 (https://github.com/maestebanc/MyFlac)"
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
GOOGLE_MAX_CHARS = 4500
MYMEMORY_MAX_CHARS = 450  # MyMemory admite hasta 500 bytes por petición


# ---------------------------------------------------------------------------------------------
# Diccionarios de términos de Discogs: {"término": ("español", "català")}
# ---------------------------------------------------------------------------------------------
TERMS: dict[str, tuple[str, str]] = {
    # --- Roles de los créditos
    "Producer": ("Producción", "Producció"),
    "Co-producer": ("Coproducción", "Coproducció"),
    "Executive-Producer": ("Producción ejecutiva", "Producció executiva"),
    "Written-By": ("Autoría", "Autoria"),
    "Songwriter": ("Autoría", "Autoria"),
    "Composed By": ("Composición", "Composició"),
    "Music By": ("Música", "Música"),
    "Lyrics By": ("Letra", "Lletra"),
    "Words By": ("Letra", "Lletra"),
    "Arranged By": ("Arreglos", "Arranjaments"),
    "Orchestrated By": ("Orquestación", "Orquestració"),
    "Conductor": ("Dirección", "Direcció"),
    "Performer": ("Intérprete", "Intèrpret"),
    "Featuring": ("Con la colaboración de", "Amb la col·laboració de"),
    "Vocals": ("Voz", "Veu"),
    "Lead Vocals": ("Voz principal", "Veu principal"),
    "Backing Vocals": ("Coros", "Cors"),
    "Choir": ("Coro", "Cor"),
    "Chorus": ("Coros", "Cors"),
    "Voice": ("Voz", "Veu"),
    "Rap": ("Rap", "Rap"),
    "Guitar": ("Guitarra", "Guitarra"),
    "Acoustic Guitar": ("Guitarra acústica", "Guitarra acústica"),
    "Electric Guitar": ("Guitarra eléctrica", "Guitarra elèctrica"),
    "Lead Guitar": ("Guitarra solista", "Guitarra solista"),
    "Rhythm Guitar": ("Guitarra rítmica", "Guitarra rítmica"),
    "Bass": ("Bajo", "Baix"),
    "Bass Guitar": ("Bajo", "Baix"),
    "Electric Bass": ("Bajo eléctrico", "Baix elèctric"),
    "Double Bass": ("Contrabajo", "Contrabaix"),
    "Drums": ("Batería", "Bateria"),
    "Percussion": ("Percusión", "Percussió"),
    "Drum Programming": ("Programación de batería", "Programació de bateria"),
    "Programmed By": ("Programación", "Programació"),
    "Keyboards": ("Teclados", "Teclats"),
    "Synthesizer": ("Sintetizador", "Sintetitzador"),
    "Piano": ("Piano", "Piano"),
    "Organ": ("Órgano", "Orgue"),
    "Strings": ("Cuerdas", "Cordes"),
    "Violin": ("Violín", "Violí"),
    "Viola": ("Viola", "Viola"),
    "Cello": ("Violonchelo", "Violoncel"),
    "Harp": ("Arpa", "Arpa"),
    "Horns": ("Metales", "Metalls"),
    "Brass": ("Metales", "Metalls"),
    "Trumpet": ("Trompeta", "Trompeta"),
    "Trombone": ("Trombón", "Trombó"),
    "Saxophone": ("Saxofón", "Saxòfon"),
    "Tenor Saxophone": ("Saxo tenor", "Saxo tenor"),
    "Alto Saxophone": ("Saxo alto", "Saxo alt"),
    "Flute": ("Flauta", "Flauta"),
    "Clarinet": ("Clarinete", "Clarinet"),
    "Harmonica": ("Armónica", "Harmònica"),
    "Banjo": ("Banjo", "Banjo"),
    "Mandolin": ("Mandolina", "Mandolina"),
    "Ukulele": ("Ukelele", "Ukulele"),
    "Accordion": ("Acordeón", "Acordió"),
    "Vibraphone": ("Vibráfono", "Vibràfon"),
    "Turntables": ("Platos", "Plats"),
    "Samples": ("Samples", "Samples"),
    "Effects": ("Efectos", "Efectes"),
    "Instruments": ("Instrumentos", "Instruments"),
    "Engineer": ("Ingeniería de sonido", "Enginyeria de so"),
    "Recording Engineer": ("Ingeniería de grabación", "Enginyeria d'enregistrament"),
    "Mixing Engineer": ("Ingeniería de mezcla", "Enginyeria de mescla"),
    "Assistant Engineer": ("Asistencia de ingeniería", "Assistència d'enginyeria"),
    "Recorded By": ("Grabación", "Enregistrament"),
    "Mixed By": ("Mezcla", "Mescla"),
    "Remix": ("Remezcla", "Remescla"),
    "Mastered By": ("Masterización", "Masterització"),
    "Lacquer Cut By": ("Corte del lacado", "Tall del lacat"),
    "Edited By": ("Edición", "Edició"),
    "Technician": ("Técnico", "Tècnic"),
    "Artwork": ("Arte", "Art"),
    "Artwork By": ("Arte", "Art"),
    "Art Direction": ("Dirección artística", "Direcció artística"),
    "Design": ("Diseño", "Disseny"),
    "Layout": ("Maquetación", "Maquetació"),
    "Cover": ("Portada", "Portada"),
    "Illustration": ("Ilustración", "Il·lustració"),
    "Painting": ("Pintura", "Pintura"),
    "Photography By": ("Fotografía", "Fotografia"),
    "Photography": ("Fotografía", "Fotografia"),
    "Liner Notes": ("Notas del libreto", "Notes del llibret"),
    "Management": ("Representación", "Representació"),
    "A&R": ("A&R", "A&R"),
    "Coordinator": ("Coordinación", "Coordinació"),
    "Translated By": ("Traducción", "Traducció"),
    "Directed By": ("Dirección", "Direcció"),
    # --- Géneros de Discogs
    "Rock": ("Rock", "Rock"),
    "Electronic": ("Electrónica", "Electrònica"),
    "Pop": ("Pop", "Pop"),
    "Folk, World, & Country": ("Folk, música del mundo y country", "Folk, música del món i country"),
    "Jazz": ("Jazz", "Jazz"),
    "Funk / Soul": ("Funk / soul", "Funk / soul"),
    "Classical": ("Clásica", "Clàssica"),
    "Hip Hop": ("Hip hop", "Hip hop"),
    "Latin": ("Latina", "Llatina"),
    "Stage & Screen": ("Teatro y cine", "Teatre i cinema"),
    "Reggae": ("Reggae", "Reggae"),
    "Blues": ("Blues", "Blues"),
    "Non-Music": ("No musical", "No musical"),
    "Children's": ("Infantil", "Infantil"),
    "Brass & Military": ("Banda y música militar", "Banda i música militar"),
    # --- Estilos frecuentes
    "Pop Rock": ("Pop rock", "Pop rock"),
    "Soft Rock": ("Soft rock", "Soft rock"),
    "Hard Rock": ("Hard rock", "Hard rock"),
    "Folk Rock": ("Folk rock", "Folk rock"),
    "Indie Rock": ("Rock independiente", "Rock independent"),
    "Alternative Rock": ("Rock alternativo", "Rock alternatiu"),
    "Progressive Rock": ("Rock progresivo", "Rock progressiu"),
    "Psychedelic Rock": ("Rock psicodélico", "Rock psicodèlic"),
    "Classic Rock": ("Rock clásico", "Rock clàssic"),
    "Art Rock": ("Art rock", "Art rock"),
    "Blues Rock": ("Blues rock", "Blues rock"),
    "Acoustic": ("Acústico", "Acústic"),
    "Ballad": ("Balada", "Balada"),
    "Vocal": ("Vocal", "Vocal"),
    "Chanson": ("Canción francesa", "Cançó francesa"),
    "Soundtrack": ("Banda sonora", "Banda sonora"),
    "Score": ("Banda sonora", "Banda sonora"),
    "Experimental": ("Experimental", "Experimental"),
    "Abstract": ("Abstracta", "Abstracta"),
    "Avantgarde": ("Vanguardia", "Avantguarda"),
    "Ambient": ("Ambient", "Ambient"),
    "Downtempo": ("Downtempo", "Downtempo"),
    "Modern Classical": ("Clásica contemporánea", "Clàssica contemporània"),
    "Contemporary": ("Contemporánea", "Contemporània"),
    "Neo-Classical": ("Neoclásica", "Neoclàssica"),
    "Baroque": ("Barroco", "Barroc"),
    "Romantic": ("Romanticismo", "Romanticisme"),
    "Opera": ("Ópera", "Òpera"),
    "Contemporary Jazz": ("Jazz contemporáneo", "Jazz contemporani"),
    "Fusion": ("Fusión", "Fusió"),
    "Latin Jazz": ("Jazz latino", "Jazz llatí"),
    "Soul": ("Soul", "Soul"),
    "Funk": ("Funk", "Funk"),
    "Disco": ("Disco", "Disco"),
    "Europop": ("Europop", "Europop"),
    "Italo-Disco": ("Italo disco", "Italo disco"),
    "Euro House": ("Euro house", "Euro house"),
    "Synth-pop": ("Synth pop", "Synth pop"),
    "New Wave": ("New wave", "New wave"),
    "Post-Punk": ("Post punk", "Post punk"),
    "Punk": ("Punk", "Punk"),
    "Heavy Metal": ("Heavy metal", "Heavy metal"),
    "Industrial": ("Industrial", "Industrial"),
    "Darkwave": ("Darkwave", "Darkwave"),
    "Minimal": ("Minimalista", "Minimalista"),
    "Berlin-School": ("Escuela de Berlín", "Escola de Berlín"),
    "Krautrock": ("Krautrock", "Krautrock"),
    "Electro": ("Electro", "Electro"),
    "Techno": ("Techno", "Techno"),
    "House": ("House", "House"),
    "Trance": ("Trance", "Trance"),
    "Progressive Trance": ("Trance progresivo", "Trance progressiu"),
    "Progressive House": ("House progresivo", "House progressiu"),
    "Breakbeat": ("Breakbeat", "Breakbeat"),
    "Trip Hop": ("Trip hop", "Trip hop"),
    "Chillwave": ("Chillwave", "Chillwave"),
    "Dream Pop": ("Dream pop", "Dream pop"),
    "Shoegaze": ("Shoegaze", "Shoegaze"),
    "Indie Pop": ("Pop independiente", "Pop independent"),
    "Rumba": ("Rumba", "Rumba"),
    "Flamenco": ("Flamenco", "Flamenc"),
    "Cantautor": ("Cantautor", "Cantautor"),
    "Singer/Songwriter": ("Cantautor", "Cantautor"),
    "Spoken Word": ("Palabra recitada", "Paraula recitada"),
    "Religious": ("Religiosa", "Religiosa"),
    "Gospel": ("Góspel", "Gòspel"),
    "Country": ("Country", "Country"),
    "Folk": ("Folk", "Folk"),
    "World": ("Música del mundo", "Música del món"),
    # --- Formatos y descripciones
    "Vinyl": ("Vinilo", "Vinil"),
    "Cassette": ("Casete", "Casset"),
    "File": ("Archivo digital", "Fitxer digital"),
    "Box Set": ("Caja recopilatoria", "Capsa recopilatòria"),
    "All Media": ("Varios soportes", "Diversos suports"),
    "Album": ("Álbum", "Àlbum"),
    "Compilation": ("Recopilatorio", "Recopilatori"),
    "Reissue": ("Reedición", "Reedició"),
    "Repress": ("Reimpresión", "Reimpressió"),
    "Remastered": ("Remasterizado", "Remasteritzat"),
    "Limited Edition": ("Edición limitada", "Edició limitada"),
    "Special Edition": ("Edición especial", "Edició especial"),
    "Deluxe Edition": ("Edición de lujo", "Edició de luxe"),
    "Numbered": ("Numerada", "Numerada"),
    "Stereo": ("Estéreo", "Estèreo"),
    "Mono": ("Mono", "Mono"),
    "Single": ("Sencillo", "Senzill"),
    "Maxi-Single": ("Maxisencillo", "Maxisenzill"),
    "Mini-Album": ("Miniálbum", "Miniàlbum"),
    "Promo": ("Promocional", "Promocional"),
    "Unofficial Release": ("Edición no oficial", "Edició no oficial"),
    "Enhanced": ("Enriquecido", "Enriquit"),
    "Club Edition": ("Edición de club", "Edició de club"),
    "Test Pressing": ("Prensaje de prueba", "Premsatge de prova"),
    "Mixed": ("Mezclado", "Mesclat"),
    "Partially Mixed": ("Parcialmente mezclado", "Parcialment mesclat"),
    "Picture Disc": ("Disco ilustrado", "Disc il·lustrat"),
    "Gatefold": ("Portada desplegable", "Portada desplegable"),
    "Digipak": ("Digipak", "Digipak"),
    "Jewel Case": ("Caja de CD", "Capsa de CD"),
    # --- Países y regiones
    "US": ("EE. UU.", "EUA"), "USA": ("EE. UU.", "EUA"), "UK": ("Reino Unido", "Regne Unit"),
    "Europe": ("Europa", "Europa"), "Worldwide": ("Todo el mundo", "Tot el món"), "Spain": ("España", "Espanya"),
    "Germany": ("Alemania", "Alemanya"), "France": ("Francia", "França"), "Italy": ("Italia", "Itàlia"),
    "Netherlands": ("Países Bajos", "Països Baixos"), "Belgium": ("Bélgica", "Bèlgica"), "Japan": ("Japón", "Japó"),
    "Canada": ("Canadá", "Canadà"), "Australia": ("Australia", "Austràlia"), "Sweden": ("Suecia", "Suècia"),
    "Norway": ("Noruega", "Noruega"), "Denmark": ("Dinamarca", "Dinamarca"), "Finland": ("Finlandia", "Finlàndia"),
    "Iceland": ("Islandia", "Islàndia"), "Ireland": ("Irlanda", "Irlanda"), "Switzerland": ("Suiza", "Suïssa"),
    "Austria": ("Austria", "Àustria"), "Portugal": ("Portugal", "Portugal"), "Greece": ("Grecia", "Grècia"),
    "Poland": ("Polonia", "Polònia"), "Russia": ("Rusia", "Rússia"), "Brazil": ("Brasil", "Brasil"),
    "Mexico": ("México", "Mèxic"), "Argentina": ("Argentina", "Argentina"), "Chile": ("Chile", "Xile"),
    "Colombia": ("Colombia", "Colòmbia"), "South Africa": ("Sudáfrica", "Sud-àfrica"), "India": ("India", "Índia"),
    "China": ("China", "Xina"), "South Korea": ("Corea del Sur", "Corea del Sud"), "Turkey": ("Turquía", "Turquia"),
    "Israel": ("Israel", "Israel"), "New Zealand": ("Nueva Zelanda", "Nova Zelanda"), "Scandinavia": ("Escandinavia", "Escandinàvia"),
    "Benelux": ("Benelux", "Benelux"), "Czech Republic": ("Chequia", "Txèquia"), "Hungary": ("Hungría", "Hongria"),
    "Romania": ("Rumanía", "Romania"), "Yugoslavia": ("Yugoslavia", "Iugoslàvia"), "Taiwan": ("Taiwán", "Taiwan"),
    "Hong Kong": ("Hong Kong", "Hong Kong"), "Unknown": ("Desconocido", "Desconegut"),
}
# Matices entre corchetes de los roles ("Guitar [Acoustic]", "Producer [Additional]")
QUALIFIERS: dict[str, tuple[str, str]] = {
    "Additional": ("adicional", "addicional"),
    "Acoustic": ("acústica", "acústica"),
    "Electric": ("eléctrica", "elèctrica"),
    "Assistant": ("asistente", "assistent"),
    "Uncredited": ("sin acreditar", "sense acreditar"),
    "Lead": ("principal", "principal"),
    "Backing": ("coros", "cors"),
    "12-String": ("de 12 cuerdas", "de 12 cordes"),
    "Fretless": ("sin trastes", "sense trasts"),
    "Steel": ("steel", "steel"),
}
_TERMS_LOWER = {k.lower(): v for k, v in TERMS.items()}
_QUALIFIERS_LOWER = {k.lower(): v for k, v in QUALIFIERS.items()}
_LANG_INDEX = {"es": 0, "ca": 1}


def term(text: str, language: str) -> str:
    """Traduce un término fijo de Discogs; si no está en el diccionario, se deja como está."""
    idx = _LANG_INDEX.get(language)
    if idx is None or not text:
        return text
    found = _TERMS_LOWER.get(text.strip().lower())
    return found[idx] if found else text


def region(text: str, language: str) -> str:
    """Países compuestos de Discogs: "UK & Europe", "USA & Canada"."""
    parts = [term(p.strip(), language) for p in text.split("&")]
    joiner = " y " if language == "es" else " i " if language == "ca" else " & "
    return joiner.join(parts)


def role(text: str, language: str) -> str:
    """
    Roles de créditos de Discogs, que pueden ser compuestos: "Layout, Artwork",
    "Guitar [Acoustic], Vocals", "Producer [Additional]".
    """
    if language not in _LANG_INDEX:
        return text
    out = []
    for part in re.split(r",\s*(?![^\[]*\])", text):
        match = re.match(r"^(.*?)\s*\[(.+)\]$", part.strip())
        if match:
            base, qualifiers = match.group(1), [q.strip() for q in match.group(2).split(",")]
            idx = _LANG_INDEX[language]
            translated = [_QUALIFIERS_LOWER[q.lower()][idx] if q.lower() in _QUALIFIERS_LOWER else term(q, language)
                          for q in qualifiers]
            out.append(f"{term(base, language)} ({', '.join(translated)})")
        else:
            out.append(term(part.strip(), language))
    return ", ".join(out)


# ---------------------------------------------------------------------------------------------
# Traducción automática de textos libres
# ---------------------------------------------------------------------------------------------
class Translator:
    """Traduce textos en inglés con Google Traductor (o MyMemory de respaldo) y los cachea."""

    _instance: Translator | None = None

    @classmethod
    def get_default(cls) -> Translator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._cache_dir = os.path.join(GLib.get_user_cache_dir(), "myflac", "translations")
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
        except OSError:
            pass
        self._lock = threading.Lock()

    def translate(self, text: str, target: str, source: str = "en") -> tuple[str | None, str]:
        """
        (texto traducido o None si falló, servicio usado). Respeta los párrafos.
        Debe llamarse fuera del hilo principal: hace peticiones de red.
        """
        text = (text or "").strip()
        if not text or target == source or target not in _LANG_INDEX:
            return text, ""
        key = hashlib.sha256(f"{source}|{target}|{text}".encode()).hexdigest()[:40]
        path = os.path.join(self._cache_dir, f"{key}.json")
        try:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            return cached["text"], cached["service"]
        except (OSError, ValueError, KeyError):
            pass

        for service, func in (("Google", self._google), ("MyMemory", self._mymemory)):
            try:
                paragraphs = [p for p in text.split("\n\n")]
                translated = "\n\n".join(func(p, source, target) if p.strip() else p for p in paragraphs)
            except Exception as e:
                log.info("Traducción con %s no disponible: %s", service, e)
                continue
            if translated.strip():
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump({"text": translated, "service": service}, f, ensure_ascii=False)
                except OSError:
                    pass
                return translated, service
        return None, ""

    @staticmethod
    def _chunks(text: str, limit: int) -> list[str]:
        """Parte un texto largo por frases para no superar el límite de cada servicio."""
        if len(text) <= limit:
            return [text]
        chunks, current = [], ""
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if len(sentence) > limit and current:
                chunks.append(current)  # lo pendiente va antes que los trozos de la frase larga
                current = ""
            while len(sentence) > limit:  # frase larguísima: se corta por palabras
                cut = sentence.rfind(" ", 0, limit)
                if cut <= 0:
                    cut = limit
                chunks.append(sentence[:cut])
                sentence = sentence[cut:].lstrip()
            if current and len(current) + len(sentence) + 1 > limit:
                chunks.append(current); current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
        return chunks

    def _get_json(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _google(self, text: str, source: str, target: str) -> str:
        out = []
        for chunk in self._chunks(text, GOOGLE_MAX_CHARS):
            params = urllib.parse.urlencode({"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": chunk})
            data = self._get_json(f"{GOOGLE_URL}?{params}")
            out.append("".join(segment[0] for segment in data[0] if segment and segment[0]))
        return " ".join(out)

    def _mymemory(self, text: str, source: str, target: str) -> str:
        out = []
        for chunk in self._chunks(text, MYMEMORY_MAX_CHARS):
            params = urllib.parse.urlencode({"q": chunk, "langpair": f"{source}|{target}"})
            data = self._get_json(f"{MYMEMORY_URL}?{params}")
            if data.get("quotaFinished") or int(data.get("responseStatus", 200)) != 200:
                raise RuntimeError(data.get("responseDetails") or "cuota agotada")
            out.append(data["responseData"]["translatedText"])
        return " ".join(out)
