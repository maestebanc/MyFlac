/**
 * MyFlac — Official Landing Page Script
 * Multi-language engine (ES, EN, CA), theme handling, interactive gallery, lightbox, and clipboard copy.
 */

// ==========================================
// 1. Translations Dictionary (ES, EN, CA)
// ==========================================
const translations = {
  es: {
    page_title: "MyFlac — Reproductor de música Hi-Res y Bit-Perfect para Linux",
    meta_desc: "MyFlac es un reproductor audiófilo nativo para GNOME y Linux con sonido bit-perfect, letras sincronizadas, fichas de Wikipedia y Discogs, y diseño GTK4 / Libadwaita.",

    // Header
    nav_about: "Por qué MyFlac",
    nav_features: "Características",
    nav_screenshots: "Capturas",
    nav_formats: "Formatos",
    nav_download: "Descargar",

    // Hero
    hero_badge: "Diseñado nativamente para GNOME & Linux • Audio Bit-Perfect",
    hero_title: "Tu música en máxima fidelidad, sin rodeos",
    hero_subtitle: "Un reproductor audiófilo moderno, rápido y elegante para Linux. Envía el audio directo a tu DAC sin alteraciones, muestra letras sincronizadas en tiempo real y enriquece tu colección con fichas de Wikipedia y Discogs.",
    btn_download: "Descargar para Linux",
    btn_github: "Código en GitHub",
    zoom_hint: "Haz clic en la captura para ampliar en alta resolución",

    // Suite Cross-Reference
    suite_badge: "La Suite MyFlac & MyTag",
    suite_title: "Dos aplicaciones creadas a medida para convivir",
    suite_desc: "Ningún reproductor de Linux se adaptaba a lo que realmente quería para mi colección musical, algo muy parecido a lo que me motivó a crear MyTag. Por eso nacieron ambas herramientas: con MyTag organizas, limpias y descargas carátulas para tus archivos, y con MyFlac los disfrutas en máxima calidad con sonido bit-perfect y una interfaz hecha con mimo.",
    suite_btn: "Conocer MyTag — Editor de Etiquetas ↗",

    // Why MyFlac
    about_title: "Por qué MyFlac",
    about_subtitle: "Diseñado pensando en quien ama escuchar música con calma, apreciar cada instrumento y disfrutar de una experiencia visual a la altura de su equipo.",

    feat_bitperfect_title: "Sonido Puro Bit-Perfect",
    feat_bitperfect_desc: "Acceso directo por hardware a tu DAC mediante ALSA exclusivo y reserva D-Bus frente a PipeWire. Sin remuestreo forzado, sin dither y a 0 dB digitales. Tu música suena exactamente como se masterizó.",

    feat_lyrics_title: "Letras Sincronizadas estilo Roon",
    feat_lyrics_desc: "Descarga automática de letras sincronizadas (LRC). El texto avanza verso a verso centrado en pantalla, se atenúa al pasar y puedes hacer clic en cualquier línea para saltar a ese segundo exacto.",

    feat_backdrop_title: "Fondo Ambiental y Foto del Artista",
    feat_backdrop_desc: "La biblioteca cobra vida con la foto del artista desenfocada en segundo plano con tinte adaptativo. No estorba la lectura y aporta una atmósfera moderna y cálida.",

    feat_info_title: "Fichas de Wikipedia y Discogs",
    feat_info_desc: "Pestañas integradas para explorar la historia del tema, el disco y el artista: año, sello, créditos de músicos y productores, y notas de edición, traducidas automáticamente a tu idioma.",

    feat_views_title: "Tres Vistas para Cada Momento",
    feat_views_desc: "Navegador por columnas para explorar tu colección, Mini-Reproductor flotante de 500×500 px para trabajar sin distracciones, o el Super-Reproductor a pantalla completa con osciloscopio fósforo.",

    feat_tray_title: "Icono en la Bandeja del Sistema",
    feat_tray_desc: "Un clic izquierdo abre una elegante ventanita con portada y barra de progreso; el clic derecho ofrece un menú D-Bus completo, y la rueda del ratón ajusta el volumen al instante.",

    // Gallery
    gallery_title: "Galería de Capturas",
    gallery_subtitle: "Descubre las distintas interfaces y modos de visualización de MyFlac.",
    tab_main: "Ventana Principal",
    tab_super: "Super-Reproductor",
    tab_mini: "Mini-Reproductor",
    cap_main: "Ventana principal: navegador por columnas (Artistas / Álbumes), fondo ambiental desenfocado, barra de transporte y panel inspector con fichas y especificaciones audiófilas.",
    cap_super: "Super-Reproductor a pantalla completa: fondo dinámico con fotografía en alta resolución del artista, tarjeta translúcida de letras sincronizadas y controles flotantes.",
    cap_mini: "Mini-Reproductor flotante (500×500 px): portada limpia o con osciloscopio interactivo y controles HUD auto-ocultables que aparecen al pasar el ratón.",

    // Formats
    formats_title: "Soporte Multiformato",
    formats_subtitle: "Reproduce con total soltura los formatos de audio más populares y los estándares Hi-Res más exigentes.",

    // Download
    dl_title: "Descarga e Instalación",
    dl_subtitle: "Elige el paquete adecuado para tu distribución GNU/Linux.",
    copied_text: "¡Copiado!",
    copy_text: "Copiar"
  },

  en: {
    page_title: "MyFlac — Bit-Perfect Hi-Res Music Player for Linux",
    meta_desc: "MyFlac is a native audiophile music player for GNOME and Linux featuring bit-perfect output, synchronized lyrics, Wikipedia and Discogs info cards, and GTK4 / Libadwaita design.",

    // Header
    nav_about: "Why MyFlac",
    nav_features: "Features",
    nav_screenshots: "Screenshots",
    nav_formats: "Formats",
    nav_download: "Download",

    // Hero
    hero_badge: "Natively designed for GNOME & Linux • Bit-Perfect Audio",
    hero_title: "Your music in pristine fidelity, with zero fuss",
    hero_subtitle: "A modern, fast, and elegant audiophile player for Linux. Sends audio straight to your DAC untouched, displays real-time synchronized lyrics, and enriches your library with Wikipedia and Discogs metadata.",
    btn_download: "Download for Linux",
    btn_github: "View on GitHub",
    zoom_hint: "Click screenshot to expand in high resolution",

    // Suite Cross-Reference
    suite_badge: "The MyFlac & MyTag Suite",
    suite_title: "Two tailored applications built to live together",
    suite_desc: "No music player on Linux matched what I truly wanted for my personal collection, much like what drove me to create MyTag. That is why both tools were born: with MyTag you organize, tag, and download high-res covers; with MyFlac you enjoy them in bit-perfect fidelity with a crafted interface.",
    suite_btn: "Discover MyTag — Tag Editor ↗",

    // Why MyFlac
    about_title: "Why MyFlac",
    about_subtitle: "Created for those who love mindful listening, savoring every instrument, and enjoying a visual experience that honors their audio gear.",

    feat_bitperfect_title: "Pure Bit-Perfect Audio",
    feat_bitperfect_desc: "Direct hardware output to your DAC via exclusive ALSA with D-Bus device reservation against PipeWire. No forced resampling, no digital dither, and fixed 0 dB volume.",

    feat_lyrics_title: "Roon-Style Synced Lyrics",
    feat_lyrics_desc: "Automatic real-time lyrics (LRC). Lines scroll smoothly centered on screen, past lyrics dim gently, and clicking any line jumps immediately to that exact second.",

    feat_backdrop_title: "Ambient Backdrop & Artist Art",
    feat_backdrop_desc: "Your library comes alive with an enlarged, softly blurred artist photo tinted to match the colors. Keeps text crystal clear while providing a warm, modern feel.",

    feat_info_title: "Wikipedia & Discogs Insights",
    feat_info_desc: "Integrated tabs exploring the story behind the song, album, and artist: release year, label, musicians and producers credits, and liner notes, auto-translated to your language.",

    feat_views_title: "Three Views for Every Moment",
    feat_views_desc: "Dual-column browser to explore your music, 500×500 px floating Mini-Player for focused work, or the fullscreen Super-Player with phosphor oscilloscope.",

    feat_tray_title: "System Tray Control",
    feat_tray_desc: "Left-click opens a sleek popup with cover art and progress bar; right-click gives a full D-Bus menu, and scrolling the mouse wheel adjusts volume instantly.",

    // Gallery
    gallery_title: "Screenshot Gallery",
    gallery_subtitle: "Explore the different views and display modes of MyFlac.",
    tab_main: "Main Window",
    tab_super: "Super-Player",
    tab_mini: "Mini-Player",
    cap_main: "Main window: column browser (Artists / Albums), ambient backdrop blur, transport bar, and inspector panel with info cards and audiophile audio specs.",
    cap_super: "Fullscreen Super-Player: dynamic high-resolution artist photography, translucent synced lyrics panel, and floating HUD playback controls.",
    cap_mini: "Floating Mini-Player (500×500 px): clean album cover or interactive oscilloscope with auto-hiding controls on mouse hover.",

    // Formats
    formats_title: "Multi-Format Support",
    formats_subtitle: "Seamlessly plays everyday audio formats as well as demanding Hi-Res studio master standards.",

    // Download
    dl_title: "Download & Installation",
    dl_subtitle: "Choose the package tailored to your GNU/Linux distribution.",
    copied_text: "Copied!",
    copy_text: "Copy"
  },

  ca: {
    page_title: "MyFlac — Reproductor de música Hi-Res i Bit-Perfect per a Linux",
    meta_desc: "MyFlac és un reproductor audiòfil natiu per a GNOME i Linux amb so bit-perfect, lletres sincronitzades, fitxes de Wikipedia i Discogs, i disseny GTK4 / Libadwaita.",

    // Header
    nav_about: "Per què MyFlac",
    nav_features: "Característiques",
    nav_screenshots: "Captures",
    nav_formats: "Formats",
    nav_download: "Descarregar",

    // Hero
    hero_badge: "Dissenyat nativament per a GNOME & Linux • Àudio Bit-Perfect",
    hero_title: "La teva música amb la màxima fidelitat, sense dreceres",
    hero_subtitle: "Un reproductor audiòfil modern, ràpid i elegant per a Linux. Envia l'àudio directe al teu DAC sense alteracions, mostra lletres sincronitzades en temps real i enriqueix la teva col·lecció amb fitxes de Wikipedia i Discogs.",
    btn_download: "Descarregar per a Linux",
    btn_github: "Codi a GitHub",
    zoom_hint: "Fes clic a la captura per ampliar en alta resolució",

    // Suite Cross-Reference
    suite_badge: "La Suite MyFlac & MyTag",
    suite_title: "Dues aplicacions creades a mida per conviure",
    suite_desc: "Cap reproductor de Linux s'adaptava al que realment volia per a la meva col·lecció musical, una cosa molt semblant al que em va motivar a crear MyTag. Per això van néixer totes dues eines: amb MyTag organitzes, neteges i descarregues caràtules per als teus arxius, i amb MyFlac els gaudeixes amb màxima qualitat amb so bit-perfect i una interfície feta amb cura.",
    suite_btn: "Conèixer MyTag — Editor d'Etiquetes ↗",

    // Why MyFlac
    about_title: "Per què MyFlac",
    about_subtitle: "Dissenyat pensant en qui estima escoltar música amb calma, apreciar cada instrument i gaudir d'una experiència visual a l'alçada del seu equip.",

    feat_bitperfect_title: "So Pur Bit-Perfect",
    feat_bitperfect_desc: "Accés directe per maquinari al teu DAC mitjançant ALSA exclusiu i reserva D-Bus davant de PipeWire. Sense remostreig forçat, sense dither i a 0 dB digitals. La teva música sona exactament com es va masteritzar.",

    feat_lyrics_title: "Lletres Sincronitzades estil Roon",
    feat_lyrics_desc: "Descàrrega automàtica de lletres sincronitzades (LRC). El text avança vers a vers centrat en pantalla, s'atenua en passar i pots fer clic en qualsevol línia per saltar a aquell segon exacte.",

    feat_backdrop_title: "Fons Ambiental i Foto de l'Artista",
    feat_backdrop_desc: "La biblioteca pren vida amb la foto de l'artista desenfocada en segon pla amb tint adaptatiu. No molesta la lectura i aporta una atmosfera moderna i càlida.",

    feat_info_title: "Fitxes de Wikipedia i Discogs",
    feat_info_desc: "Pestanyes integrades per explorar la història del tema, el disc i l'artista: any, segell, crèdits de músics i productors, i notes d'edició, traduïdes automàticament al teu idioma.",

    feat_views_title: "Tres Vistes per a Cada Moment",
    feat_views_desc: "Navegador per columnes per explorar la teva col·lecció, Mini-Reproductor flotant de 500×500 px per treballar sense distraccions, o el Super-Reproductor a pantalla completa amb oscil·loscopi fòsfor.",

    feat_tray_title: "Icona a la Safata del Sistema",
    feat_tray_desc: "Un clic esquerre obre una elegant finestreta amb caràtula i barra de progrés; el clic dret ofereix un menú D-Bus complet, i la roda del ratolí ajusta el volum a l'instant.",

    // Gallery
    gallery_title: "Galeria de Captures",
    gallery_subtitle: "Descobreix les diferents interfícies i modes de visualització de MyFlac.",
    tab_main: "Finestra Principal",
    tab_super: "Super-Reproductor",
    tab_mini: "Mini-Reproductor",
    cap_main: "Finestra principal: navegador per columnes (Artistes / Àlbums), fons ambiental desenfocat, barra de transport i panell inspector amb fitxes i especificacions audiòfiles.",
    cap_super: "Super-Reproductor a pantalla completa: fons dinàmic amb fotografia en alta resolució de l'artista, targeta translúcida de lletres sincronitzades i controls flotants.",
    cap_mini: "Mini-Reproductor flotant (500×500 px): caràtula neta o amb oscil·loscopi interactiu i controls HUD auto-ocultables que apareixen en passar el ratolí.",

    // Formats
    formats_title: "Suport Multiformat",
    formats_subtitle: "Reprodueix amb total facilitat els formats d'àudio més populars i els estàndards Hi-Res més exigents.",

    // Download
    dl_title: "Descàrrega i Instal·lació",
    dl_subtitle: "Tria el paquet adequat per a la teva distribució GNU/Linux.",
    copied_text: "Copiat!",
    copy_text: "Copiar"
  },
};

// ==========================================
// 2. Language Engine
// ==========================================
let currentLang = "es";

function detectLanguage() {
  const saved = localStorage.getItem("myflac_lang");
  if (saved && translations[saved]) return saved;

  const browser = (navigator.language || navigator.userLanguage || "es").toLowerCase();
  if (browser.startsWith("ca")) return "ca";
  if (browser.startsWith("en")) return "en";
  return "es";
}

function setLanguage(lang) {
  if (!translations[lang]) lang = "es";
  currentLang = lang;
  localStorage.setItem("myflac_lang", lang);

  document.documentElement.lang = lang;

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (translations[lang][key]) {
      el.textContent = translations[lang][key];
    }
  });

  if (translations[lang].page_title) {
    document.title = translations[lang].page_title;
  }

  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-lang") === lang);
  });
}

// ==========================================
// 3. Theme Engine (Dark by default)
// ==========================================
function getEffectiveTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  if (current === "dark" || current === "light") return current;
  return "dark";
}

function initTheme() {
  const saved = localStorage.getItem("myflac_theme");
  if (saved === "light") {
    applyTheme("light");
  } else {
    applyTheme("dark");
  }
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "light") {
    root.setAttribute("data-theme", "light");
    localStorage.setItem("myflac_theme", "light");
  } else {
    root.setAttribute("data-theme", "dark");
    localStorage.setItem("myflac_theme", "dark");
  }
}

function toggleTheme() {
  const effective = getEffectiveTheme();
  const next = effective === "dark" ? "light" : "dark";
  applyTheme(next);
}

// ==========================================
// 4. Hero Interactive Carousel Engine
// ==========================================
let currentSlideIndex = 0;
let carouselAutoplayTimer = null;
let isLightboxActive = false;

const slideCaptions = ["cap_main", "cap_super", "cap_mini"];

function initCarousel() {
  const container = document.getElementById("carouselContainer");
  const track = document.getElementById("carouselTrack");
  const prevBtn = document.getElementById("carouselPrev");
  const nextBtn = document.getElementById("carouselNext");
  const dots = document.querySelectorAll("#carouselIndicators .indicator-dot");
  const captionEl = document.getElementById("carouselCaption");
  const slides = document.querySelectorAll(".carousel-slide");
  const totalSlides = slides.length;

  if (!container || !track || totalSlides === 0) return;

  function updateSlide(index, userInitiated = false) {
    if (index < 0) {
      currentSlideIndex = totalSlides - 1;
    } else if (index >= totalSlides) {
      currentSlideIndex = 0;
    } else {
      currentSlideIndex = index;
    }

    // Move track smoothly
    track.style.transform = `translateX(-${currentSlideIndex * 100}%)`;

    // Active state on slides
    slides.forEach((slide, idx) => {
      slide.classList.toggle("active", idx === currentSlideIndex);
    });

    // Active state on indicator dots
    dots.forEach((dot, idx) => {
      dot.classList.toggle("active", idx === currentSlideIndex);
    });

    // Update dynamic caption with smooth fade
    if (captionEl) {
      const capKey = slideCaptions[currentSlideIndex] || "cap_main";
      captionEl.setAttribute("data-i18n", capKey);
      captionEl.style.opacity = "0";
      setTimeout(() => {
        captionEl.textContent = (translations[currentLang] && translations[currentLang][capKey]) || "";
        captionEl.style.opacity = "1";
      }, 150);
    }

    // If user manually switched slides, restart the timer
    if (userInitiated) {
      resetAutoplay();
    }
  }

  function startAutoplay() {
    stopAutoplay();
    if (!isLightboxActive) {
      carouselAutoplayTimer = setInterval(() => {
        updateSlide(currentSlideIndex + 1, false);
      }, 3000);
    }
  }

  function stopAutoplay() {
    if (carouselAutoplayTimer) {
      clearInterval(carouselAutoplayTimer);
      carouselAutoplayTimer = null;
    }
  }

  function resetAutoplay() {
    stopAutoplay();
    startAutoplay();
  }

  // Next & Prev button clicks
  if (prevBtn) {
    prevBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      updateSlide(currentSlideIndex - 1, true);
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      updateSlide(currentSlideIndex + 1, true);
    });
  }

  // Dots clicks
  dots.forEach((dot) => {
    dot.addEventListener("click", (e) => {
      e.stopPropagation();
      const targetIndex = parseInt(dot.getAttribute("data-slide"), 10);
      if (!isNaN(targetIndex)) {
        updateSlide(targetIndex, true);
      }
    });
  });

  // Pause on hover
  container.addEventListener("mouseenter", () => {
    stopAutoplay();
  });

  container.addEventListener("mouseleave", () => {
    if (!isLightboxActive) {
      startAutoplay();
    }
  });

  // Touch Swipe for Mobile / Tablets
  let touchStartX = 0;
  let touchStartY = 0;

  container.addEventListener(
    "touchstart",
    (e) => {
      touchStartX = e.changedTouches[0].screenX;
      touchStartY = e.changedTouches[0].screenY;
      stopAutoplay();
    },
    { passive: true }
  );

  container.addEventListener(
    "touchend",
    (e) => {
      const diffX = e.changedTouches[0].screenX - touchStartX;
      const diffY = e.changedTouches[0].screenY - touchStartY;
      if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 40) {
        if (diffX < 0) {
          updateSlide(currentSlideIndex + 1, true);
        } else {
          updateSlide(currentSlideIndex - 1, true);
        }
      }
      if (!isLightboxActive) {
        startAutoplay();
      }
    },
    { passive: true }
  );

  // Keyboard navigation when not typing in inputs
  window.addEventListener("keydown", (e) => {
    if (isLightboxActive) return;
    if (document.activeElement && (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA")) return;
    if (e.key === "ArrowLeft") {
      updateSlide(currentSlideIndex - 1, true);
    } else if (e.key === "ArrowRight") {
      updateSlide(currentSlideIndex + 1, true);
    }
  });

  // Expose pause/resume to Lightbox
  window.pauseCarouselAutoplay = stopAutoplay;
  window.resumeCarouselAutoplay = startAutoplay;

  // Initial trigger
  updateSlide(0, false);
  startAutoplay();
}

// ==========================================
// 5. Lightbox Modal
// ==========================================
function initLightbox() {
  const modal = document.getElementById("lightboxModal");
  const backdrop = document.getElementById("lightboxBackdrop");
  const closeBtn = document.getElementById("lightboxClose");
  const modalImg = document.getElementById("lightboxImage");
  const modalCap = document.getElementById("lightboxCaption");

  if (!modal || !modalImg) return;

  function openLightbox(src, alt, caption) {
    modalImg.src = src;
    modalImg.alt = alt || "Captura ampliada de MyFlac";
    if (modalCap) modalCap.textContent = caption || "";
    modal.classList.add("active");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    isLightboxActive = true;
    if (window.pauseCarouselAutoplay) window.pauseCarouselAutoplay();
  }

  function closeLightbox() {
    modal.classList.remove("active");
    modal.setAttribute("aria-hidden", "true");
    modalImg.src = "";
    document.body.style.overflow = "";
    isLightboxActive = false;
    if (window.resumeCarouselAutoplay) window.resumeCarouselAutoplay();
  }

  document.querySelectorAll(".zoomable").forEach((el) => {
    el.addEventListener("click", () => {
      const img = el.querySelector("img");
      if (img) {
        const slide = el.closest(".carousel-slide");
        let caption = "";
        if (slide && slide.getAttribute("data-caption-key")) {
          const key = slide.getAttribute("data-caption-key");
          caption = (translations[currentLang] && translations[currentLang][key]) || el.getAttribute("data-caption") || "";
        } else {
          caption = el.getAttribute("data-caption") || img.alt || "";
        }
        openLightbox(img.src, img.alt, caption);
      }
    });
  });

  if (closeBtn) closeBtn.addEventListener("click", closeLightbox);
  if (backdrop) backdrop.addEventListener("click", closeLightbox);

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("active")) {
      closeLightbox();
    }
  });
}

// ==========================================
// 6. Clipboard Copy Engine
// ==========================================
function initCopyButtons() {
  document.querySelectorAll(".code-copy-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const textToCopy = btn.getAttribute("data-copy");
      if (!textToCopy) return;

      navigator.clipboard.writeText(textToCopy).then(() => {
        const originalText = btn.textContent;
        const successText = (translations[currentLang] && translations[currentLang].copied_text) || "¡Copiado!";
        btn.textContent = successText;
        btn.classList.add("copied");

        setTimeout(() => {
          btn.textContent = originalText;
          btn.classList.remove("copied");
        }, 2000);
      });
    });
  });
}

// ==========================================
// 7. Mobile Menu
// ==========================================
function initMobileMenu() {
  const toggle = document.getElementById("mobileToggle");
  const nav = document.getElementById("navMenu");

  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", !expanded);
      nav.classList.toggle("open", !expanded);
    });

    nav.querySelectorAll(".nav-link").forEach((link) => {
      link.addEventListener("click", () => {
        toggle.setAttribute("aria-expanded", "false");
        nav.classList.remove("open");
      });
    });
  }
}

// ==========================================
// 8. DOM Content Loaded
// ==========================================
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  setLanguage(detectLanguage());

  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      setLanguage(btn.getAttribute("data-lang"));
    });
  });

  const themeToggle = document.getElementById("themeToggle");
  if (themeToggle) {
    themeToggle.addEventListener("click", toggleTheme);
  }

  initCarousel();
  initLightbox();
  initCopyButtons();
  initMobileMenu();
});
