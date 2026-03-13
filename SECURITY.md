# Security Policy

## Reporting a Vulnerability

Email contact@voxhash.dev with details and reproduction steps.

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will respond within 48 hours and work with you to address the issue responsibly.

## Security Features

DB Storage Manager implements several security measures:

- **Encrypted Storage**: All credentials encrypted with cryptography (Fernet)
- **Safe Mode**: Prevents dangerous operations by default
- **Local-Only**: No external data transmission
- **Input Validation**: Comprehensive input sanitization

See [docs/SECURITY.md](docs/SECURITY.md) for detailed security documentation.
