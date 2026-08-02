#!/bin/sh
set -eu

APP_DIR=${1:?usage: package.sh <pyinstaller-dir> <version> <output-dir>}
VERSION=${2:?usage: package.sh <pyinstaller-dir> <version> <output-dir>}
OUTPUT_DIR=${3:?usage: package.sh <pyinstaller-dir> <version> <output-dir>}
APPIMAGE_TOOL=${APPIMAGE_TOOL:?APPIMAGE_TOOL must point to a verified appimagetool}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-0}

mkdir -p "$OUTPUT_DIR"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/usr/bin" "$stage/usr/share/applications" "$stage/usr/share/mime/packages"
cp -R "$APP_DIR" "$stage/icc"
cp packaging/linux/AppRun "$stage/AppRun"
cp packaging/linux/icc.desktop "$stage/icc.desktop"
cp packaging/assets/icc.svg "$stage/icc.svg"
cp packaging/linux/icc.desktop "$stage/usr/share/applications/icc.desktop"
cp packaging/linux/application-x-icc.xml "$stage/usr/share/mime/packages/application-x-icc.xml"
chmod +x "$stage/AppRun" "$stage/icc/icc"

tarball="$OUTPUT_DIR/insulation-coordination-${VERSION}-linux-x86_64.tar.gz"
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 --numeric-owner \
    -C "$stage" -czf "$tarball" .
"$APPIMAGE_TOOL" --no-appstream "$stage" \
    "$OUTPUT_DIR/insulation-coordination-${VERSION}-linux-x86_64.AppImage"
