"""Preferencia de modo exclusivo guardada por dispositivo."""
from myflac.config import is_device_exclusive_enabled, set_device_exclusive_enabled

IFI = "alsa_output.usb-iFi-00.analog-stereo"


def test_exclusive_is_remembered_per_device_and_survives_node_suffix():
    cfg = {}
    set_device_exclusive_enabled(cfg, IFI + ".3", True)
    # WirePlumber recrea el nodo con otro sufijo .N: la preferencia debe seguir aplicándose
    assert is_device_exclusive_enabled(cfg, IFI)
    assert is_device_exclusive_enabled(cfg, IFI + ".5")
    assert not is_device_exclusive_enabled(cfg, "alsa_output.pci-hdmi-stereo")
    set_device_exclusive_enabled(cfg, IFI, False)
    assert not is_device_exclusive_enabled(cfg, IFI + ".3")


def test_default_output_never_exclusive():
    cfg = {"exclusive_devices": ["default"]}
    set_device_exclusive_enabled(cfg, "default", True)
    assert not is_device_exclusive_enabled(cfg, "default")


def test_streaming_services_defaults():
    """Qobuz activo por defecto; TIDAL condicionado hasta pase a producción."""
    from myflac import config
    assert config.DEFAULTS["qobuz_enabled"] is True
    assert config.DEFAULTS["tidal_enabled"] is False
    assert config.TIDAL_AVAILABLE is False


def test_library_setup_defaults():
    """Valores por defecto para la configuración inicial y vista."""
    from myflac import config
    assert config.DEFAULTS["library_setup_dismissed"] is False
    assert config.DEFAULTS["last_view"] == "library"
