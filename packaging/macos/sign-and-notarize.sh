#!/bin/sh
set -eu

APP=${1:?usage: sign-and-notarize.sh <app> <dmg>}
DMG=${2:?usage: sign-and-notarize.sh <app> <dmg>}
: "${APPLE_SIGNING_IDENTITY:?set APPLE_SIGNING_IDENTITY for paid signing}"
: "${APPLE_NOTARY_PROFILE:?set APPLE_NOTARY_PROFILE for notarization}"

codesign --force --deep --options runtime --timestamp --sign "$APPLE_SIGNING_IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
xcrun notarytool submit "$DMG" --keychain-profile "$APPLE_NOTARY_PROFILE" --wait
xcrun stapler staple "$APP"
