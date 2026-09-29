from myflac.audio.devices import AudioDevice, _parse_alsa_fields, base_node_name


def test_parse_alsa_fields_builds_hw_path():
    fields = _parse_alsa_fields({"alsa.card": "2", "alsa.id": "Audio", "alsa.device": "0"})
    dev = AudioDevice(id="alsa_output.usb-x.analog-stereo", name="DAC", **fields)
    assert dev.alsa_card == 2
    assert dev.hw_path == "hw:CARD=Audio,DEV=0"


def test_non_alsa_device_has_no_hw_path():
    assert _parse_alsa_fields({}) == {}
    assert _parse_alsa_fields({"alsa.card": "x", "alsa.id": "A", "alsa.device": "0"}) == {}
    assert AudioDevice(id="raop_sink.Terraza", name="Terraza").hw_path is None


def test_base_node_name_strips_wireplumber_suffix_only_on_alsa_nodes():
    assert base_node_name("alsa_output.usb-iFi-00.analog-stereo.4") == "alsa_output.usb-iFi-00.analog-stereo"
    assert base_node_name("alsa_output.usb-iFi-00.analog-stereo") == "alsa_output.usb-iFi-00.analog-stereo"
    assert base_node_name("raop_sink.Mac.local.10.0.0.1.7000") == "raop_sink.Mac.local.10.0.0.1.7000"


_IFI_STREAM0 = """iFi (by AMR) iFi (by AMR) HD USB Audio at usb-0000:67:00.0-1, high speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S32_LE
    Rates: 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000
  Interface 1
    Altset 2
    Format: S24_3LE
    Rates: 44100, 48000, 96000

Capture:
  Status: Stop
  Interface 2
    Altset 1
    Rates: 768000
"""


def test_parse_stream_max_rate_uses_playback_only():
    from myflac.audio.devices import parse_stream_max_rate

    assert parse_stream_max_rate(_IFI_STREAM0) == 384000


def test_parse_stream_max_rate_continuous_range_and_missing():
    from myflac.audio.devices import parse_stream_max_rate

    assert parse_stream_max_rate("Playback:\n  Interface 1\n    Rates: 8000 - 192000\n") == 192000
    assert parse_stream_max_rate("Capture:\n    Rates: 48000\n") is None


def test_parse_stream_dsd_native():
    from myflac.audio.devices import parse_stream_dsd_native

    assert not parse_stream_dsd_native(_IFI_STREAM0)
    with_dsd = _IFI_STREAM0.replace("Capture:", "  Interface 1\n    Altset 4\n    Format: DSD_U32_BE\n\nCapture:")
    assert parse_stream_dsd_native(with_dsd)
    # Un formato DSD solo en la sección de captura no cuenta
    assert not parse_stream_dsd_native("Playback:\n    Format: S32_LE\nCapture:\n    Format: DSD_U32_BE\n")
