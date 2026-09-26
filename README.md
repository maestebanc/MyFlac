# MyFlac

**Reproductor de música Hi-Res Bit-Perfect para GNOME.**

Desarrollado en Python con GTK4 y Libadwaita, diseñado con la filosofía y ergonomía de [MyTag](https://github.com/maestebanc/MyTag), enfocado específicamente en la reproducción audiófila de alta resolución, con modo exclusivo opcional directo por hardware ALSA.

---

## Características Principales

- **Modo Exclusivo Bit-Perfect (ALSA `hw:X,Y`)**, desactivado por defecto:
  - Se activa desde el selector de dispositivos de la barra inferior y se recuerda entre sesiones.
  - Reserva la tarjeta frente a PipeWire mediante el protocolo D-Bus `org.freedesktop.ReserveDevice1` y reproduce directamente sobre `hw:CARD=…,DEV=…`, sin pasar por el mezclador del sistema.
  - Sin remuestreo: el DAC recibe la frecuencia nativa de cada pista (también al encadenar pistas *gapless* de distinta frecuencia).
  - Sin volumen digital ni *dithering*: el volumen queda fijo a 0 dB y solo se reempaqueta la muestra al formato que acepte el DAC (p. ej. 24 bits en contenedor de 32 → `S24_3LE`).
  - Si el DAC no admite la frecuencia o el formato de una pista, esa pista suena por el mezclador con un aviso y la siguiente vuelve al modo exclusivo. Si la tarjeta está ocupada, se vuelve al mezclador.
  - Píldora `⚡ BIT-PERFECT` en la barra de reproducción mientras el transporte es exclusivo.

- **Selector Rápido de Dispositivos de Audio**:
  - Detección automática de DACs USB, tarjetas de sonido, HDMI y altavoces de red de PipeWire / PulseAudio.
  - Cambio de salida con un clic, conservando pista y posición.

- **Inspector Técnico Audiófilo**:
  - Especificaciones de la **Fuente**: códec, frecuencia exacta, bits por muestra, canales, tasa de bits y tamaño.

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
