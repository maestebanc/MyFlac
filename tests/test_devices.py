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
