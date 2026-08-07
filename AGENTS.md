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
