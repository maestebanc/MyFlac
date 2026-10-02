"""Constantes globales de MyFlac."""

APP_ID = "com.maestebanc.MyFlac"
APP_NAME = "MyFlac"
APP_WEBSITE = "https://maestebanc.github.io/MyFlac/"
APP_REPOSITORY = "https://github.com/maestebanc/MyFlac"

SUPPORTED_EXTENSIONS = (
    ".flac",
    ".wav",
    ".wave",
    ".aiff",
    ".aif",
    ".alac",
    ".m4a",
    ".dsf",
    ".dff",
    ".mp3",
    ".ogg",
    ".opus",
)

# Extensiones de carátula local a buscar en el directorio del archivo
COVER_FILENAMES = (
    "cover.jpg",
    "cover.png",
    "cover.jpeg",
    "folder.jpg",
    "folder.png",
    "front.jpg",
    "front.png",
    "albumart.jpg",
    "albumart.png",
)

# Umbrales para considerar audio Hi-Res
HIRES_MIN_SAMPLE_RATE = 48000
HIRES_MIN_BIT_DEPTH = 24
