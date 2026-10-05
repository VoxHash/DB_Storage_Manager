# Contributing to DB Storage Manager

Thanks for helping improve DB Storage Manager (VoxHash Technologies).

## Code of Conduct

Please read and follow our [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development Setup

```bash
git clone https://github.com/VoxHash/DB_Storage_Manager.git
cd DB_Storage_Manager
python3.12 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e ".[dev]"
pytest -v
```

Use Python 3.10–3.12. Optional engines: `pip install -e ".[engines]"` (and `".[oracle]"` when Instant Client is available).

## Branching & Commit Style

- Branches: `feature/…`, `fix/…`, `docs/…`, `chore/…`
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`

Examples:

- `feat(dashboard): add storage visualization charts`
- `fix(connections): resolve database connection timeout issue`
- `docs: update README with new features`

## Pull Requests

- Link related issues, add tests, update docs
- Follow `.github/PULL_REQUEST_TEMPLATE.md`
- Keep diffs focused
- Ensure lint/tests you can run locally are green

## Code Quality

```bash
black db_storage_manager/
flake8 db_storage_manager/ --count --select=E9,F63,F7,F82
mypy db_storage_manager/ --ignore-missing-imports
```

## Testing

```bash
pytest -v
pytest --cov=db_storage_manager
```

GUI smoke (headless):

```bash
QT_QPA_PLATFORM=offscreen python -c "from PyQt6.QtWidgets import QApplication; import sys; from db_storage_manager.gui.main_window import MainWindow; app=QApplication(sys.argv); print(MainWindow().windowTitle())"
```

## Release Process

- Semantic Versioning
- Update [CHANGELOG.md](CHANGELOG.md)
- Bump version in `setup.py`, `db_storage_manager/__init__.py`, and `config.APP_VERSION`
- Tag `vX.Y.Z` to trigger the release workflow

## Getting Help

- [docs/index.md](docs/index.md)
- https://github.com/VoxHash/DB_Storage_Manager/issues
- contact@voxhash.dev
