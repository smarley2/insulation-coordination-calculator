#!/bin/sh
set -eu

APP=${1:?usage: package.sh <app> <fixtures> <version> <output-dir>}
FIXTURES=${2:?usage: package.sh <app> <fixtures> <version> <output-dir>}
VERSION=${3:?usage: package.sh <app> <fixtures> <version> <output-dir>}
OUTPUT_DIR=${4:?usage: package.sh <app> <fixtures> <version> <output-dir>}

mkdir -p "$OUTPUT_DIR"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
diagnostic_dir=$(mktemp -d)
trap 'rm -rf "$diagnostic_dir"' EXIT
"$APP/Contents/MacOS/icc" --release-diagnostic "$FIXTURES" --output-dir "$diagnostic_dir"
test -s "$diagnostic_dir/diagnostic.json"
test -s "$diagnostic_dir/report.pdf"

dmg="$OUTPUT_DIR/insulation-coordination-${VERSION}-macos-arm64.dmg"
hdiutil create -volname "Insulation Coordination Calculator" -srcfolder "$APP" \
    -ov -format UDZO "$dmg"
mounted=$(hdiutil attach -nobrowse -readonly -plist "$dmg" | \
    /usr/libexec/PlistBuddy -c 'Print :system-entities:0:mount-point' /dev/stdin)
trap 'hdiutil detach "$mounted" >/dev/null || true; rm -rf "$diagnostic_dir"' EXIT
test -d "$mounted"
