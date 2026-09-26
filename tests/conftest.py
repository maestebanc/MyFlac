"""Configuración común de tests: aísla configuración, caché y datos del usuario."""
import os
import sys
import tempfile

import pytest

# GLib lee las rutas XDG la primera vez que se consultan, así que se fijan antes de importar myflac
_XDG_ROOT = tempfile.mkdtemp(prefix="myflac-tests-")
for _var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
    os.environ[_var] = os.path.join(_XDG_ROOT, _var.lower())
os.environ.setdefault("LANGUAGE", "es")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def make_flac(tmp_path):
    """Genera un FLAC de silencio con GStreamer y, opcionalmente, le añade etiquetas Vorbis."""
    gi = pytest.importorskip("gi")
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    if not Gst.ElementFactory.find("flacenc"):
        pytest.skip("flacenc no disponible")

    def _make(name="track.flac", rate=44100, fmt="S16LE", seconds=0.5, subdir="", tags=None):
        folder = tmp_path / subdir if subdir else tmp_path
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        buffers = max(1, int(rate * seconds / 1024))
        pipeline = Gst.parse_launch(
            f"audiotestsrc wave=silence num-buffers={buffers} samplesperbuffer=1024 ! "
            f"audio/x-raw,rate={rate},format={fmt},channels=2 ! flacenc ! filesink location=\"{path}\""
        )
        pipeline.set_state(Gst.State.PLAYING)
        pipeline.get_bus().timed_pop_filtered(10 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        pipeline.set_state(Gst.State.NULL)

        if tags:
            from mutagen.flac import FLAC

            audio = FLAC(str(path))
            for key, value in tags.items():
                audio[key] = value
            audio.save()
        return str(path)

    return _make
