# MyFlac

**Reproductor de música Hi-Res Bit-Perfect para GNOME.**

Desarrollado en Python con GTK4 y Libadwaita, diseñado con la filosofía y ergonomía de [MyTag](https://github.com/maestebanc/MyTag), enfocado específicamente en la reproducción audiófila de alta resolución con salida exclusiva directa por hardware ALSA.

---

## Características Principales

- **Modo Exclusivo Bit-Perfect Directo (ALSA `hw:X,Y`)**:
  - Conexión física directa al DAC USB (ej. *iFi HD USB Audio*, *Chord*, *Topping*, etc.) o tarjeta de sonido sin pasar por el mezclador del sistema ni capas de software.
  - Sincronización exacta del reloj de hardware del DAC a la frecuencia nativa de la pista (44.1, 48, 88.2, 96, 176.4, 192, 352.8, 384 kHz).
  - Reproducción 100% bit-exacta: sin remuestreo (*no resampling*), sin *dithering* ni truncado de bits.
  - Bypass de volumen digital (fijado a 100% / 0 dB) con opción de atenuación si el usuario lo requiere.

- **Selector Rápido de Dispositivos de Audio**:
  - Detección automática en caliente de DACs USB y tarjetas de sonido ALSA.
  - Consulta de especificaciones reales de la tarjeta (frecuencias soportadas hasta 384 kHz, formatos PCM `S16_LE`, `S24_3LE`, `S32_LE`, `DSD`).
  - Posibilidad de alternar con un clic entre el DAC exclusivo y la salida compartida predeterminada del sistema (PipeWire / PulseAudio).

- **Inspector Técnico Audiófilo en Tiempo Real**:
  - Visualización en paralelo de la **Fuente** (códec, frecuencia exacta, bits por muestra, canales, tasa de bits y tamaño) y la **Salida DAC** (dispositivo conectado, frecuencia de reloj negociada en el hardware y confirmación de transporte Bit-Perfect).
  - Píldora de estado en vivo en la barra de reproducción: verde esmeralda `⚡ BIT-PERFECT` cuando el transporte es 100% bit-exacto.

- **Diseño Moderno GNOME / Libadwaita**:
  - Dos paneles con distribución fluida: lista de canciones a la izquierda e inspector audiófilo con carátula en alta definición a la derecha.
  - Soporte completo para arrastrar y soltar (*Drag & Drop*) carpetas de álbumes o pistas sueltas desde Nautilus u otros exploradores.
  - Búsqueda en vivo instantánea por título, artista o álbum.
  - Transición fluida entre canciones (*gapless playback*).
  - Atajos de teclado rápidos (`Espacio` para reproducir/pausar, `Ctrl+O` para abrir carpeta, `Ctrl+Shift+O` para pistas, `Ctrl+,` para preferencias).
- **Visualizadores y Experiencia Visual**:
  - **Osciloscopio en Tiempo Real**: Efecto fósforo a 60 FPS con sincronización de estado global persistente.
  - **Mini-Reproductor Flotante (500×500 px)**: Modo compacto con controles auto-ocultables y carátula limpia/osciloscopio alternable con un clic.
  - **Super-Reproductor a Pantalla Completa**: Interfaz inmersiva de doble panel con fondo ambiental reactivo a los colores de la carátula y letras sincronizadas online vía LRCLIB.

---

## Ejecución en Local

Para lanzar la aplicación localmente en modo desarrollo:

```bash
./run.sh
```

O bien directamente con Python:

```bash
python3 -m myflac
```

---

## Empaquetado e Instalación con Flatpak

MyFlac incluye soporte oficial para empaquetado Flatpak bajo el runtime GNOME 50 (`org.gnome.Platform//50`).

Para compilar, instalar localmente y generar el paquete portable `.flatpak`:

```bash
./build-flatpak.sh
```

O manualmente con `flatpak-builder`:

```bash
flatpak-builder --force-clean --user --install build-dir com.maestebanc.MyFlac.yaml
```

Para ejecutar la versión Flatpak instalada:

```bash
flatpak run com.maestebanc.MyFlac
```
