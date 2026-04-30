# Dependency install profiles

This directory keeps the installation paths explicit for fresh-machine bootstrap.

- `runtime.txt` — minimal editable install of CodePilot itself
- `dev.txt` — editable install plus test/lint tooling

Recommended bootstrap on a new machine:

```bash
python scripts/bootstrap.py --profile dev
```

If you only need the package without the test/lint extras:

```bash
python scripts/bootstrap.py --profile runtime
```
