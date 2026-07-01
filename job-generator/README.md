# Job Generator

Job generator for Ubuntu GUI testing.

## Usage

Generate a jenkins-job-builder config from an input YAML:

```bash
job-generator input.yaml -o jobs.yaml
```

Omit `-o` to write to stdout.

### Input format

```yaml
release: resolute
suites:
  desktop-installer:
    tests:
      resolute.entire-disk: {}
  firefox-example:
    tests:
      firefox-example-basic:
        depends-on: desktop-installer/resolute.entire-disk
```

The top-level `release` field is required and must be a YAML string. It selects
the ISO used by tests that do not define `depends-on`. Those producer tests boot from
`/srv/data/.rf_image_cache/<release>/<release>-desktop-amd64.iso` on the agent.

Generated ISO-backed jobs first invoke the externally provided
`dl-iso-to-cache` builder with the configured `release`, so the expected ISO is
available in the cache before the runner starts.

Each test may define:

- `depends-on: <suite>/<test>` — clone the libvirt domain produced by another
  test. The producer job runs with `--keep` so its domain survives, and a
  `reverse` trigger starts the consumer job whenever the producer succeeds. The
  consumer resolves the producer's most recent domain itself via
  `--source-domain-prefix ugt-<suite>-<test>`, so no Jenkins plugin or build
  parameter is required.

### Output format

The shared SCM and runner invocation are factored into a single JJB
`job-template`; a `project` then instantiates one job per test with only its
`suite`, `test`, `args`, and `triggers`. This keeps the generated config compact
and free of per-job boilerplate. The SCM lives in the template rather than a
global `defaults` block, so the output can be combined with other JJB files
without overriding their shared defaults.

Every job first provisions `yarf` for the build: a setup builder clones
`https://github.com/canonical/yarf` into the job workspace and runs `uv sync`,
and the runner builder prepends the resulting `.venv/bin` to `PATH`. This keeps
`yarf` self-contained per build (reclaimed by Jenkins workspace cleanup) rather
than installed on the agent. The git ref is the `YARF_REF` build parameter
(default `main`), overridable from the Jenkins UI.

## Development

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd job-generator
uv sync --group dev
```

### Quality checks

```bash
uv run ruff format .
uv run ruff check .
uv run mypy .
uv run pytest tests/
```
