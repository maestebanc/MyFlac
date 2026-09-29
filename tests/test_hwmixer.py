"""Curva de volumen por hardware (misma que alsamixer)."""
import pytest

from myflac.audio.hwmixer import db_from_normalized, normalized_from_db

# Rango del iFi HD USB: -127.00 dB .. 0.00 dB (centésimas de dB)
MIN_DB, MAX_DB = -12700, 0


@pytest.mark.parametrize("volume", [0.05, 0.25, 0.5, 0.75, 1.0])
def test_db_mapping_round_trips(volume):
    db = db_from_normalized(volume, MIN_DB, MAX_DB)
    assert normalized_from_db(db, MIN_DB, MAX_DB) == pytest.approx(volume, abs=0.002)


def test_db_mapping_endpoints_and_perceptual_middle():
    assert db_from_normalized(1.0, MIN_DB, MAX_DB) == 0
    assert db_from_normalized(0.0, MIN_DB, MAX_DB) == MIN_DB
    # La mitad del deslizador es una atenuación audible pero moderada, no la mitad del rango en dB
    assert -2000 < db_from_normalized(0.5, MIN_DB, MAX_DB) < -1500
