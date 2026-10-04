%define srcdir %{getenv:MYFLAC_SRCDIR}
%define pysitelib %(python3 -c "import sys; print(f'/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')")

Name:           myflac
Version:        0.2.3
Release:        1%{?dist}
Summary:        Bit-perfect Hi-Res audio player for GNOME
License:        GPL-3.0-or-later
URL:            https://maestebanc.github.io/MyFlac/
BuildArch:      noarch

Requires:       python3 >= 3.11
Requires:       python3-mutagen
Requires:       python3-pillow
Requires:       python3-gobject
Requires:       gtk4 >= 4.10
Requires:       libadwaita >= 1.4
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Recommends:     gstreamer1-plugin-libav
Recommends:     webkitgtk6.0

%description
MyFlac is an audiophile, bit-perfect music player built specifically for GNOME
and Linux. Features hardware ALSA direct mode, column browser, background artist
blur, synchronized lyrics with live scroll, rich album/artist metadata from
Wikipedia and Discogs, system tray mini-player and Apple Music-style compact mode.

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}%{pysitelib}
cp -r %{srcdir}/myflac %{buildroot}%{pysitelib}/
find %{buildroot}%{pysitelib}/myflac -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

mkdir -p %{buildroot}/usr/bin
cat > %{buildroot}/usr/bin/myflac <<'LAUNCHER'
#!/usr/bin/python3
import sys
from myflac.app import main
if __name__ == "__main__":
    sys.exit(main())
LAUNCHER
chmod 755 %{buildroot}/usr/bin/myflac

mkdir -p %{buildroot}/usr/share/applications
cp %{srcdir}/data/com.maestebanc.MyFlac.desktop %{buildroot}/usr/share/applications/

mkdir -p %{buildroot}/usr/share/metainfo
cp %{srcdir}/data/com.maestebanc.MyFlac.metainfo.xml %{buildroot}/usr/share/metainfo/

for size in 16 22 24 32 48 64 128 256 512; do
  mkdir -p %{buildroot}/usr/share/icons/hicolor/${size}x${size}/apps
  cp %{srcdir}/data/icons/hicolor/${size}x${size}/apps/com.maestebanc.MyFlac.png %{buildroot}/usr/share/icons/hicolor/${size}x${size}/apps/
done
mkdir -p %{buildroot}/usr/share/icons/hicolor/scalable/apps
cp %{srcdir}/data/icons/hicolor/scalable/apps/com.maestebanc.MyFlac.svg %{buildroot}/usr/share/icons/hicolor/scalable/apps/
mkdir -p %{buildroot}/usr/share/icons/hicolor/symbolic/apps
cp %{srcdir}/data/icons/hicolor/symbolic/apps/com.maestebanc.MyFlac-symbolic.svg %{buildroot}/usr/share/icons/hicolor/symbolic/apps/
mkdir -p %{buildroot}/usr/share/icons/hicolor/symbolic/actions
cp %{srcdir}/data/icons/hicolor/symbolic/actions/*.svg %{buildroot}/usr/share/icons/hicolor/symbolic/actions/

%files
%{pysitelib}/myflac
/usr/bin/myflac
/usr/share/applications/com.maestebanc.MyFlac.desktop
/usr/share/metainfo/com.maestebanc.MyFlac.metainfo.xml
/usr/share/icons/hicolor/*/apps/com.maestebanc.MyFlac.png
/usr/share/icons/hicolor/scalable/apps/com.maestebanc.MyFlac.svg
/usr/share/icons/hicolor/symbolic/apps/com.maestebanc.MyFlac-symbolic.svg
/usr/share/icons/hicolor/symbolic/actions/*.svg

%post
update-desktop-database -q /usr/share/applications &>/dev/null || :
gtk-update-icon-cache -q /usr/share/icons/hicolor &>/dev/null || :

%changelog
* Fri Oct 02 2026 Miguel Angel Esteban <maestebanc@gmail.com> - 0.2.1-1
- Oscilloscope relocated to bottom-left mini-cover in main window to keep main artwork clear.
- Compact oscilloscope bottom strip with gentle alpha fade in Mini Player and Super Player.
- Active lyrics line zoom, bold emphasis, text glow, and silky smooth organic scrolling.
- Bundled window-pop-out-symbolic icon for Ubuntu/Yaru compatibility.

* Tue Sep 29 2026 Miguel Angel Esteban <maestebanc@gmail.com> - 0.2.0-1
- Safe exclusive mode negotiation with WirePlumber (the DAC no longer disappears from the system).
- Native DSD playback on DSD-capable DACs; DSD128+ converted to 352.8 kHz PCM in exclusive mode.
- DAC hardware volume in exclusive mode, restored when the DAC is handed back.
- Honest transport status in the output selector (bit-perfect, resampling, reduced bits, DSD).
- Network libraries: covers, lyrics and session restore no longer freeze the interface.
- Redesigned output selector and tabbed preferences without scrolling.
- Light and dark theme tones (Warm Paper and Obsidian by default).

* Tue Sep 29 2026 Miguel Angel Esteban <maestebanc@gmail.com> - 0.1.2-1
- Header bar theme toggle button (dark / Soft Slate light mode).
- Super Player expanded to 80% screen height with 4 tabs (Lyrics, Track, Album, Artist).
- Limited log file size to 2 MB with automatic rotation.

* Sun Sep 27 2026 Miguel Angel Esteban <maestebanc@gmail.com> - 0.1.1-1
- Added close behavior setting: quit completely or keep running in system tray.

* Sun Sep 27 2026 Miguel Angel Esteban <maestebanc@gmail.com> - 0.1.0-1
- Initial public release of MyFlac.
- Hardware ALSA bit-perfect output with D-Bus device reservation.
- Dual-column library browser with search and metadata scanner.
- Synchronized LRC lyrics display with interactive seek.
- Artist wallpaper & ambient backdrop blur behind library.
- Ultra HD album art fetching with pixel-correlation validation.
- Rich artist and album metadata cards from Wikipedia & Discogs with automatic translation.
- System tray integration with mini-player popup and volume control.
- Floating 500x500 mini-player with Apple Music-inspired HUD.
- Fullscreen Super-Player with oscilloscope.
