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
