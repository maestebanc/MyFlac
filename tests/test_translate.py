import pytest

from myflac import translate
from myflac.translate import Translator


def test_dictionary_terms_roles_and_regions():
    assert translate.role("Guitar [Acoustic], Vocals", "es") == "Guitarra (acústica), Voz"
    assert translate.role("Producer [Additional]", "ca") == "Producció (addicional)"
    assert translate.role("Some Unknown Role", "es") == "Some Unknown Role"  # sin traducción, intacto
    assert translate.term("Folk, World, & Country", "ca") == "Folk, música del món i country"
    assert translate.term("Acoustic", "es") == "Acústico"
    assert translate.region("UK & Europe", "es") == "Reino Unido y Europa"
    assert translate.term("Rock", "en") == "Rock"  # en inglés no se toca


def test_chunks_respect_limits():
    text = "Una frase. " * 100 + "x" * 900
    chunks = Translator._chunks(text.strip(), 450)
    assert all(len(c) <= 450 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


@pytest.fixture
def translator(tmp_path):
    t = Translator()
    t._cache_dir = str(tmp_path)
    return t


def test_falls_back_to_mymemory_and_caches(translator, monkeypatch):
    calls = []

    def google(text, source, target):
        calls.append("google")
        raise OSError("bloqueado")

    def mymemory(text, source, target):
        calls.append("mymemory")
        return f"ES:{text}"

    monkeypatch.setattr(translator, "_google", google)
    monkeypatch.setattr(translator, "_mymemory", mymemory)
    assert translator.translate("Hello.\n\nBye.", "es") == ("ES:Hello.\n\nES:Bye.", "MyMemory")
    # Segunda vez: desde la caché, sin red
    assert translator.translate("Hello.\n\nBye.", "es") == ("ES:Hello.\n\nES:Bye.", "MyMemory")
    assert calls == ["google", "mymemory", "mymemory"]


def test_no_service_available(translator, monkeypatch):
    def fail(*_a):
        raise OSError("sin red")
    monkeypatch.setattr(translator, "_google", fail)
    monkeypatch.setattr(translator, "_mymemory", fail)
    assert translator.translate("Hello", "ca") == (None, "")
    assert translator.translate("Hello", "en") == ("Hello", "")
