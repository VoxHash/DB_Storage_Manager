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
- Off-machine backups (Proton Drive, S3) are always AES-256-GCM encrypted before upload
- Experimental full restore is off by default, requires `backups:restore`, typed confirmation and writes an `audit.log` (mode `600`, secrets stripped)
- Email alert SMTP passwords are stored encrypted; plain SMTP is accepted only for loopback relays
- Optional multi-user RBAC (encrypted `users.enc`, PBKDF2 password hashes, role permissions on sensitive desktop and API actions)

### Enabling multi-user RBAC (shared workstation)

By default the desktop app runs in single-user open mode (no login). To require local accounts:

```bash
db-storage-manager-bootstrap --username admin --password 'choose-a-long-password'
# or: python -m db_storage_manager.security.bootstrap
```

Or use **Settings → Users & RBAC → Bootstrap first admin…** in the GUI.

After bootstrap, the desktop prompts for sign-in on every launch. Keep the admin password in a gitignored local file such as `.env.rbac.local` (mode `600`; see `.env.rbac.local.example`) — never commit secrets. The REST companion requires HTTP Basic (username/password) or a configured `DSM_API_TOKEN` (treated as system admin). Permissions are enforced per role — viewers cannot mutate connections, manage plugins, change settings, or run restore dry-runs.

Architecture and encryption details: [docs/architecture.md](docs/architecture.md)
