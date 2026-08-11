# Agent notes

Development conventions live in [CONTRIBUTING.md](CONTRIBUTING.md). Read it before changing
calculations, rule packages, traces, or reports. The rules on licensed standards and private test
data apply to agents exactly as they do to humans.

## Running the test suite

The suite is parallel-safe (`pytest-xdist` is in the dev group). Run it with `-n`:

```bash
uv run pytest -n auto
```

On a 24-core Windows machine the full suite takes about 100 s serially and about 20 s with
`-n 12`. `-n auto` is the right default on CI runners (4 cores), but on machines with many cores
worker startup dominates — `-n auto` measured 28 s against 19 s for `-n 12`. Pick an explicit
`-n 8`–`-n 12` locally if the machine is large.

Full check set before proposing a change:

```bash
uv run ruff check .
```

```bash
uv run mypy
```

```bash
uv run pytest -n auto --cov=insulation_coordination --cov-branch --cov-report=term-missing --cov-fail-under=80
```

Drop `-n` when debugging a single failing test — xdist hides `pdb` and reorders output.

## Running the licensed test suite

`tests/private` imports the maintainer's licensed IEC PDFs. It is skipped entirely when they
are absent, so a green public run says nothing about it. One piece of local setup is
needed, so it is written down here.

**The licensed PDF folder.** `tests/private/conftest.py` reads
`ICC_PRIVATE_STANDARDS_DIR`, defaulting to `standards/` at the repository root, which is
gitignored. It identifies documents by content, never by filename, so unrelated PDFs may
share the folder — it skips anything it cannot identify. It needs all three supported
documents: IEC 60664-1:2020, IEC 60664-4:2005, and IEC 62477-1:2022.

```bash
$env:ICC_PRIVATE_STANDARDS_DIR="C:\path\to\your\standards"
```

Note that identification reads each PDF in the folder. A malformed unrelated document used
to crash the fixture rather than being skipped; that is fixed, but a folder of hundreds of
PDFs will still cost seconds per file.

**Manual curve review.** The curve workflow imports only verified local source artifacts.
Maintainers calibrate each plot and enter points during review.

**What it costs.** The private suite shares one source-only import and one local manual-review
pass. Run it once with the timeout below; do not add timing claims without a measured licensed
run, and avoid a second import unless that is the assertion under test.

The default per-test timeout is 120 s. Use 900 s as a conservative allowance for a licensed
run until a measurement supports a tighter limit:

```bash
uv run pytest tests/private -q --timeout=900
```

**Do not edit source files while a licensed run is in flight.** pytest collects at start,
so a run overlapping your edits reports on a tree that no longer exists. This has produced
misleading results more than once.
