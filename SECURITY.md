# Security Policy

## Reporting a Vulnerability

Email **contact@voxhash.dev** with details and reproduction steps.

Please include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will respond within 48 hours and work with you to address the issue responsibly.

## Security Features

- Encrypted credential storage with cryptography (Fernet)
- Safe Mode blocks dangerous query operations by default
- Local master key with restrictive Unix permissions
- Optional engines and cloud adapters only load when used

Architecture and encryption details: [docs/architecture.md](docs/architecture.md)
