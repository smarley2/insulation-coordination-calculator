"""Document-identity facts for IEC 62477-1:2022.

Layout and identification facts only. This build supports the 2022 edition and refuses
the 2012 edition rather than translating between them.
"""

EXPECTED_PAGE_COUNT = 522
METADATA_IDENTITY_FIELDS = ("/Title", "/Subject", "/Keywords")
METADATA_IDENTITY_ANCHORS = ("IEC 62477-1", "2022")
IDENTITY_ANCHORS = ("IEC 62477-1", "Edition 2.0 2022-05")
IDENTITY_CLAIM_PATTERN = r"(?i)(IEC\s*62477-1).{0,24}?\b((?:19|20)\d{2})\b"
