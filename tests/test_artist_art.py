from myflac.artist_art import (
    _clean_artist_name,
    _normalize_name,
    _pick_deezer_picture,
    _pick_wikipedia_thumbnail,
)

PLACEHOLDER = "https://cdn-images.dzcdn.net/images/artist//1000x1000-000000-80-0-0.jpg"


def test_clean_artist_name_removes_collaborators():
    assert _clean_artist_name("Daft Punk feat. Pharrell Williams") == "Daft Punk"
    assert _clean_artist_name("Calvin Harris ft. Rihanna") == "Calvin Harris"
    assert _clean_artist_name("Simon & Garfunkel") == "Simon"
    assert _clean_artist_name("Artist A / Artist B") == "Artist A"
    assert _clean_artist_name("  Björk  ") == "Björk"
    assert _clean_artist_name("") == ""


def test_normalize_name_ignores_accents_case_article_and_punctuation():
    assert _normalize_name("Rosalía") == _normalize_name("ROSALIA")
    assert _normalize_name("The Beatles") == _normalize_name("Beatles")
    assert _normalize_name("AC/DC") == _normalize_name("ACDC")
    assert _normalize_name("Air") != _normalize_name("Air & Tur")


def test_deezer_picks_exact_name_match_not_first_result():
    results = [
        {"name": "Air ( Bach )", "picture_xl": "https://x/images/artist/aaa/1.jpg", "nb_fan": 10},
        {"name": "Air", "picture_xl": "https://x/images/artist/bbb/1.jpg", "nb_fan": 5},
    ]
    assert _pick_deezer_picture("Air", results) == "https://x/images/artist/bbb/1.jpg"


def test_deezer_prefers_most_followed_homonym():
    results = [
        {"name": "Air", "picture_xl": "https://x/images/artist/small/1.jpg", "nb_fan": 12},
        {"name": "Air", "picture_xl": "https://x/images/artist/big/1.jpg", "nb_fan": 900000},
    ]
    assert _pick_deezer_picture("Air", results) == "https://x/images/artist/big/1.jpg"


def test_deezer_skips_generic_silhouette():
    results = [
        {"name": "Nobody", "picture_xl": PLACEHOLDER, "nb_fan": 3},
    ]
    assert _pick_deezer_picture("Nobody", results) is None


def test_deezer_no_match_returns_none():
    results = [{"name": "Somebody Else", "picture_xl": "https://x/images/artist/abc/1.jpg"}]
    assert _pick_deezer_picture("Nobody", results) is None
    assert _pick_deezer_picture("Nobody", []) is None


def _wiki_candidates(name):
    return [f"{name} (band)", f"{name} (musician)", f"{name} (singer)", f"{name} (rapper)", name]


def test_wikipedia_skips_non_music_and_disambiguation_pages():
    # Respuesta real simplificada para "Air": la página "Air" redirige a la atmósfera terrestre
    query = {
        "redirects": [
            {"from": "Air", "to": "Atmosphere of Earth"},
            {"from": "Air (band)", "to": "Air (disambiguation)"},
        ],
        "pages": [
            {"title": "Air (musician)", "missing": True},
            {"title": "Atmosphere of Earth", "description": "Gas layer surrounding Earth",
             "thumbnail": {"source": "https://img/atmosphere.jpg"}},
            {"title": "Air (disambiguation)", "description": "Topics referred to by the same term",
             "pageprops": {"disambiguation": ""}},
            {"title": "Air (singer)", "description": "Japanese musician"},
        ],
    }
    assert _pick_wikipedia_thumbnail(_wiki_candidates("Air"), query) is None


def test_wikipedia_picks_band_page():
    query = {
        "pages": [
            {"title": "Queen", "description": "Topics referred to by the same term",
             "pageprops": {"disambiguation": ""}},
            {"title": "Queen (band)", "description": "British rock band",
             "thumbnail": {"source": "https://img/queen.jpg"}},
        ],
    }
    assert _pick_wikipedia_thumbnail(_wiki_candidates("Queen"), query) == "https://img/queen.jpg"


def test_wikipedia_follows_normalization_to_bare_title():
    query = {
        "normalized": [{"from": "björk", "to": "Björk"}],
        "pages": [
            {"title": "Björk", "description": "Icelandic singer (born 1965)",
             "thumbnail": {"source": "https://img/bjork.jpg"}},
        ],
    }
    assert _pick_wikipedia_thumbnail(["björk"], query) == "https://img/bjork.jpg"


def test_backdrop_blur_and_tint(tmp_path):
    from PIL import Image

    from myflac.ui.backdrop import blur_artist_image, scrim_color, scrim_opacity

    path = tmp_path / "artist.jpg"
    Image.new("RGB", (1000, 1000), (200, 40, 40)).save(path)
    png, average = blur_artist_image(str(path))
    assert png.startswith(b"\x89PNG")
    assert average[0] > 150 and average[1] < 80

    dark = scrim_color(average, dark=True, intensity=42)
    assert dark.startswith("rgba(") and dark.endswith("0.58)")
    # El tinte rojo se nota, pero la capa sigue siendo oscura
    r, g, b = (int(v) for v in dark[5:].split(",")[:3])
    assert r > g and max(r, g, b) < 60
    assert scrim_color(None, dark=False, intensity=42) == "rgba(230, 224, 214, 0.62)"  # Papel cálido
    # Por defecto, intensidad 10 %: capa del 90 % (94 % en tema claro)
    assert scrim_color(None, dark=True).endswith("0.9)") and scrim_color(None, dark=False).endswith("0.94)")


def test_backdrop_intensity_maps_to_scrim_opacity():
    from myflac.ui.backdrop import scrim_opacity

    assert scrim_opacity(42, dark=True) == 0.58
    assert scrim_opacity(80, dark=True) == 0.2
    # Fuera de rango se limita a 10-80 %
    assert scrim_opacity(0, dark=True) == 0.9
    assert scrim_opacity(100, dark=True) == 0.2
    assert scrim_opacity(10, dark=False) == 0.94


def test_hires_same_image_detection():
    from PIL import Image, ImageDraw, ImageEnhance, ImageOps

    from myflac.hires_cover import is_same_image

    def cover(color, text_pos, frame=0):
        img = Image.new("RGB", (500, 500), color)
        draw = ImageDraw.Draw(img)
        draw.rectangle((60, 60, 300, 200), fill=(250, 250, 250))
        draw.ellipse((text_pos, 250, text_pos + 180, 430), fill=(10, 10, 10))
        return ImageOps.expand(img.resize((500 - 2 * frame,) * 2), frame, (0, 0, 0)) if frame else img

    original = cover((180, 30, 40), 100)
    big = original.resize((1400, 1400), Image.Resampling.LANCZOS)
    # La misma imagen más grande, con otra corrección de brillo o un marco fino, se acepta
    assert is_same_image(original, big)
    assert is_same_image(original, ImageEnhance.Brightness(big).enhance(1.25))
    assert is_same_image(original, cover((180, 30, 40), 100, frame=12))
    # Otra composición, una edición recoloreada o la misma recortada a otro formato, se rechaza
    other = Image.new("RGB", (500, 500), (180, 30, 40))
    draw = ImageDraw.Draw(other)
    draw.rectangle((200, 300, 440, 440), fill=(250, 250, 250))
    draw.ellipse((40, 40, 220, 220), fill=(10, 10, 10))
    assert not is_same_image(original, other)
    assert not is_same_image(original, cover((250, 240, 60), 100))
    assert not is_same_image(original, big.crop((0, 0, 1400, 1000)))


def test_hires_rejects_relayout_of_mostly_white_cover():
    from PIL import Image, ImageDraw

    from myflac.hires_cover import is_same_image

    # Caso real ("Please" de Pet Shop Boys): portada casi blanca y su reedición con la foto más
    # grande. Casi todos los píxeles coinciden, pero no es la misma imagen
    def white_cover(box):
        img = Image.new("RGB", (500, 500), (250, 250, 250))
        ImageDraw.Draw(img).rectangle(box, fill=(190, 150, 130))
        return img

    assert not is_same_image(white_cover((225, 225, 275, 270)), white_cover((190, 180, 330, 310)))
    assert is_same_image(white_cover((225, 225, 275, 270)), white_cover((225, 225, 275, 270)).resize((1400, 1400)))
