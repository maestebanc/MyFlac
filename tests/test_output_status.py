"""Estado del transporte que muestra el selector de salida."""
from types import SimpleNamespace

from myflac.audio.devices import AudioDevice
from myflac.audio.engine import _format_depth
from myflac.ui.output_status import format_device_subtitle, output_status


def _engine(**kw):
    base = dict(exclusive_active=True, resampling_active=False, depth_reduced=False,
                output_sample_rate=0, output_bit_depth=0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_format_depth_reads_useful_bits():
    assert _format_depth("S16LE") == 16
    assert _format_depth("S24_32LE") == 24
    assert _format_depth("S24LE") == 24
    assert _format_depth("S32LE") == 32
    assert _format_depth("F32LE") is None


def test_mixer_output_has_no_indicator():
    status, level, _ = output_status(_engine(exclusive_active=False))
    assert status == "Mezclador del sistema"
    assert level == ""


def test_bitperfect_shows_rate():
    status, level, _ = output_status(_engine(output_sample_rate=192000))
    assert status == "Bit-perfect · 192 kHz"
    assert level == "ok"


def test_resampling_and_reduced_depth_are_warnings():
    status, level, _ = output_status(_engine(resampling_active=True, output_sample_rate=96000))
    assert (status, level) == ("Remuestreo a 96 kHz", "warn")
    status, level, _ = output_status(_engine(depth_reduced=True, output_bit_depth=16, output_sample_rate=44100))
    assert (status, level) == ("Reducido a 16 bits", "warn")


def test_device_subtitle():
    usb = AudioDevice(id="alsa_output.usb-iFi-00.analog-stereo", name="iFi", is_usb=True, max_sample_rate=384000)
    assert format_device_subtitle(usb) == "DAC USB · Hasta 384 kHz"
    hdmi = AudioDevice(id="alsa_output.pci-0000_c5_00.1.hdmi-stereo", name="HDMI",
                       description="Radeon HDMI [LG HDR 4K]", icon_name="video-display-symbolic")
    assert format_device_subtitle(hdmi) == "HDMI (LG HDR 4K)"


def test_dsd_native_and_dsd_to_pcm():
    status, level, _ = output_status(_engine(output_dsd=True, output_sample_rate=2822400))
    assert (status, level) == ("DSD nativo · DSD64", "ok")
    status, level, _ = output_status(_engine(dsd_to_pcm=True, output_sample_rate=352800))
    assert (status, level) == ("DSD → PCM · 352.8 kHz", "warn")
