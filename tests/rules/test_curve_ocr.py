"""OCR boundary contract: protocol, adapter argv, TSV parsing. No real Tesseract."""

from __future__ import annotations

import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from insulation_coordination.rules.importer.curves import (
    OcrEngine,
    OcrEngineIdentity,
    OcrError,
    OcrToken,
    PixelBox,
    TesseractOcrEngine,
)


class FakeOcrEngine:
    identity = OcrEngineIdentity(name="fake", version="1", config_sha256="0" * 64)

    def recognize(self, image: Image.Image) -> tuple[OcrToken, ...]:
        return (OcrToken(text="13", confidence=Decimal("0.99"), box=PixelBox(left=1, top=2, right=3, bottom=4)),)


def _image() -> Image.Image:
    return Image.new("L", (8, 8), color=255)


TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "5\t1\t1\t1\t1\t2\t30\t10\t20\t12\t96.5\t13\n"
    "5\t1\t1\t1\t1\t1\t10\t10\t15\t12\t91.25\tms\n"
    "5\t1\t1\t1\t2\t1\t10\t40\t18\t12\t88.0\tabc\n"
)


def test_fake_ocr_is_protocol_compatible() -> None:
    assert isinstance(FakeOcrEngine(), OcrEngine)


def test_pixel_box_orders_edges() -> None:
    with pytest.raises(ValueError):
        PixelBox(left=5, top=2, right=3, bottom=4)
    with pytest.raises(ValueError):
        PixelBox(left=1, top=6, right=3, bottom=4)


def test_engine_identity_requires_sha256() -> None:
    with pytest.raises(ValueError):
        OcrEngineIdentity(name="fake", version="1", config_sha256="not-a-hash")


def test_adapter_calls_fixed_argv_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout=TSV.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    engine = TesseractOcrEngine(executable="tesseract-test")
    tokens = engine.recognize(_image())

    (call,) = calls
    argv = call["argv"]
    assert argv[0] == "tesseract-test"
    assert argv[1].endswith(".png")
    assert argv[2:] == ["stdout", "--psm", "6", "tsv"]
    assert call["shell"] is False
    assert call["timeout"] == engine.timeout_seconds
    assert call["capture_output"] is True
    assert isinstance(tokens, tuple)


def test_adapter_parses_tsv_in_reading_order(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=TSV.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tokens = TesseractOcrEngine(executable="tesseract-test").recognize(_image())
    assert [token.text for token in tokens] == ["ms", "13", "abc"]
    assert tokens[0].confidence == Decimal("0.9125")
    assert tokens[0].box == PixelBox(left=10, top=10, right=25, bottom=22)
    assert tokens[1].box == PixelBox(left=30, top=10, right=50, bottom=22)


def test_adapter_deletes_temporary_png(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    written: list[Path] = []

    def fake_run(argv, **kwargs):
        written.append(Path(argv[1]))
        return subprocess.CompletedProcess(argv, 0, stdout=TSV.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "insulation_coordination.rules.importer.curves.tempfile.mkstemp",
        lambda suffix: (
            None,
            str(tmp_path / f"ocr{suffix}"),
        ),
    )
    TesseractOcrEngine(executable="tesseract-test").recognize(_image())
    assert len(written) == 1
    assert not written[0].exists()


def test_nonzero_exit_blocks_with_ocr_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 3, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OcrError, match="OCR_FAILED"):
        TesseractOcrEngine(executable="tesseract-test").recognize(_image())


def test_missing_executable_blocks_with_ocr_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OcrError, match="OCR_UNAVAILABLE"):
        TesseractOcrEngine(executable="definitely-missing-tesseract").recognize(_image())


def test_timeout_blocks_with_ocr_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OcrError, match="OCR_FAILED"):
        TesseractOcrEngine(executable="tesseract-test").recognize(_image())


def test_identity_joins_engine_name_version_and_config() -> None:
    engine = TesseractOcrEngine(executable="tesseract-test", version="5.3.0")
    identity = engine.identity
    assert identity.name == "tesseract"
    assert identity.version == "5.3.0"
    assert len(identity.config_sha256) == 64
    other = TesseractOcrEngine(executable="tesseract-test", version="5.3.0")
    assert other.identity == identity


def _tsv_with_conf(conf: str) -> bytes:
    return (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        f"5\t1\t1\t1\t1\t1\t10\t10\t15\t12\t{conf}\tok\n"
    ).encode()


@pytest.mark.parametrize("conf", ("-1", "150"))
def test_out_of_range_confidence_blocks_with_ocr_failed(
    monkeypatch: pytest.MonkeyPatch, conf: str
) -> None:
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=_tsv_with_conf(conf), stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OcrError, match="OCR_FAILED"):
        TesseractOcrEngine(executable="tesseract-test").recognize(_image())


def test_non_utf8_output_blocks_with_ocr_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=b"\xff\xfe invalid", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(OcrError, match="OCR_FAILED"):
        TesseractOcrEngine(executable="tesseract-test").recognize(_image())
