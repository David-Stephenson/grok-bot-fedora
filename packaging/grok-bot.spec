# Unofficial Linux packaging of Grok Bot. Binaries in the payload are
# copyright Anysphere / xAI; this spec only describes how we lay them out.
Name:           grok-bot
Version:        %{grokbot_version}
Release:        %{grokbot_release}
Summary:        Unofficial Linux build of Grok Bot
License:        Proprietary
URL:            https://x.ai/bot
ExclusiveArch:  x86_64 aarch64

# Prebuilt Electron + Node addons: skip debuginfo and rpath checks.
%global debug_package %{nil}
%global __brp_check_rpaths %{nil}
%undefine _debugsource_packages
%undefine _debuginfo_subpackages

Requires:       ca-certificates
Requires:       libX11
Requires:       libXcomposite
Requires:       libXdamage
Requires:       libXext
Requires:       libXfixes
Requires:       libXrandr
Requires:       alsa-lib
Requires:       atk
Requires:       at-spi2-atk
Requires:       at-spi2-core
Requires:       cairo
Requires:       cups-libs
Requires:       dbus-libs
Requires:       expat
Requires:       mesa-libgbm
Requires:       gtk3
Requires:       nss
Requires:       nspr
Requires:       pango
Requires:       libdrm
Requires:       libxkbcommon
Requires:       xdg-utils
Requires:       libnotify

%description
Desktop client for Grok Bot, assembled from the official macOS app.asar,
the official Electron Linux binary, and native Node addons extracted from
the Cursor Linux RPM.

This package is unofficial and not supported by xAI, Anysphere, or Cursor.

%install
install -d %{buildroot}/usr/libexec/grok-bot
cp -a %{payload_dir}/. %{buildroot}/usr/libexec/grok-bot/

install -D -m 0755 %{wrapper} %{buildroot}/usr/bin/grok-bot
install -D -m 0644 %{desktop} %{buildroot}/usr/share/applications/grok-bot.desktop
%if 0%{?has_icon}
install -D -m 0644 %{icon} %{buildroot}/usr/share/icons/hicolor/256x256/apps/grok-bot.png
%endif

# Electron will not start a sandboxed renderer unless chrome-sandbox is
# setuid root. rpmbuild preserves that mode only if we declare the attr.
chmod 4755 %{buildroot}/usr/libexec/grok-bot/chrome-sandbox || true

%files
%dir /usr/libexec/grok-bot
%exclude /usr/libexec/grok-bot/chrome-sandbox
/usr/libexec/grok-bot/*
/usr/bin/grok-bot
/usr/share/applications/grok-bot.desktop
%attr(4755, root, root) /usr/libexec/grok-bot/chrome-sandbox
%if 0%{?has_icon}
/usr/share/icons/hicolor/256x256/apps/grok-bot.png
%endif

%post
/bin/touch --no-create /usr/share/icons/hicolor 2>/dev/null || :
/usr/bin/gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || :
/usr/bin/update-desktop-database /usr/share/applications 2>/dev/null || :

%postun
/usr/bin/gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || :
/usr/bin/update-desktop-database /usr/share/applications 2>/dev/null || :

%changelog
* Sun Aug 23 2026 Grok Bot Fedora packagers <noreply@local> - %{grokbot_version}-%{grokbot_release}
- Automated unofficial Linux RPM.
