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
"$APP/Contents/MacOS/icc" --release-diagnostic \
    "$FIXTURES/project.icproj" "$FIXTURES/rules.icrules" "$diagnostic_dir"
test -s "$diagnostic_dir/release-diagnostic.json"
test -s "$diagnostic_dir/release-diagnostic.pdf"

dmg="$OUTPUT_DIR/insulation-coordination-${VERSION}-macos-arm64.dmg"
hdiutil create -volname "Insulation Coordination Calculator" -srcfolder "$APP" \
    -ov -format UDZO "$dmg"
mounted=$(hdiutil attach -nobrowse -readonly -plist "$dmg" | python3 -c '
import plistlib
import sys

entities = plistlib.loads(sys.stdin.buffer.read())["system-entities"]
print(next(entity["mount-point"] for entity in entities if "mount-point" in entity))
')
trap 'hdiutil detach "$mounted" >/dev/null || true; rm -rf "$diagnostic_dir"' EXIT
test -d "$mounted"
