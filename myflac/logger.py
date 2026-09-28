"""Sistema de registro (logging) exhaustivo en archivo para MyFlac."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import sys

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from .constants import APP_NAME, APP_ID
from . import __version__

_LOGGER_INITIALIZED = False


def get_log_dir() -> str:
    """Retorna el directorio donde se almacenan los logs de MyFlac."""
    # Usar ~/.config/myflac/ o ~/.local/state/myflac/
    log_dir = os.path.join(GLib.get_user_config_dir(), "myflac")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_log_path() -> str:
    """Retorna la ruta absoluta del archivo de registro principal."""
    return os.path.join(get_log_dir(), "myflac.log")


def setup_logging(debug: bool = True) -> logging.Logger:
    """Inicializa el sistema de logging con salida a archivo rotativo y consola."""
    global _LOGGER_INITIALIZED
    logger = logging.getLogger("myflac")

    if _LOGGER_INITIALIZED:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Evitar duplicación de handlers si se llama varias veces
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)-7s] [%(name)s:%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Handler para archivo rotativo (máximo 2 MB)
    log_file = get_log_path()
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=1,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        sys.stderr.write(f"No se pudo crear el manejador de archivo de log: {e}\n")

    # 2. Handler para consola (stdout / stderr)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 3. Capturar excepciones no controladas en el log
    def _excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Excepción no capturada en la aplicación:",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _excepthook

    _LOGGER_INITIALIZED = True

    # Mensaje de cabecera en el arranque
    logger.info("=" * 70)
    logger.info(f"Iniciando {APP_NAME} v{__version__} ({APP_ID})")
    logger.info(f"Python: {sys.version.split()[0]} | Plataforma: {platform.platform()}")
    logger.info(f"Archivo de log activo: {log_file}")
    logger.info("=" * 70)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Obtiene un logger subordinado para un módulo específico."""
    if not _LOGGER_INITIALIZED:
        setup_logging()
    if name:
        return logging.getLogger(f"myflac.{name}")
    return logging.getLogger("myflac")
