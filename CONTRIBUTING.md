# Contributing to DB Storage Manager

Thanks for helping improve DB Storage Manager!

## Code of Conduct

Please read and follow our [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development Setup

```bash
# Clone
git clone https://github.com/voxhash/db-storage-manager.git
cd db-storage-manager

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"  # For development dependencies

# Run tests
pytest
```

## Branching & Commit Style

- Branches: `feature/…`, `fix/…`, `docs/…`, `chore/…`
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`

Examples:
- `feat(dashboard): add storage visualization charts`
- `fix(connections): resolve database connection timeout issue`
- `docs: update README with new features`

## Pull Requests

- Link related issues, add tests, update docs
- Follow the PR template in `.github/PULL_REQUEST_TEMPLATE.md`
- Keep diffs focused and well-documented
- Ensure all tests pass and code follows style guidelines

## Code Quality

- Follow PEP 8 style guide
- Use `black` for code formatting: `black .`
- Run `flake8` for linting: `flake8 .`
- Run `mypy` for type checking: `mypy .`
- Write tests for new features
- Add type hints where appropriate

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=db_storage_manager

# Run specific test file
pytest tests/test_connections.py
```

## Release Process

- Semantic Versioning (MAJOR.MINOR.PATCH)
- Update [CHANGELOG.md](CHANGELOG.md) with changes
- Tag releases with version number
- Create GitHub release with release notes

## Getting Help

- Check [README.md](README.md) for project overview
- Review [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for setup
- Open an issue for bugs or questions
- Join discussions for feature ideas
