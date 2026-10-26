# Privacy review — companion credential model

**Status:** documented deliverable for the Android / GrapheneOS companion milestone (see [ROADMAP.md](../ROADMAP.md)). Desktop remains the system of record for secrets.

## Threat model (summary)

| Asset | Desktop | Phone companion |
|---|---|---|
| Fernet `.master-key` | Required locally; mode `600` | **Never** copy or sync |
| `connections.enc` / `settings.enc` / `users.enc` | Encrypted at rest | **Never** mirror by default |
| Connection passwords / SSH passwords / private keys | In SecureStore | **Not** on device; API returns `***` |
| Companion Bearer (`DSM_API_TOKEN` or pairing token) | Env / shown once | EncryptedSharedPreferences only |
| Local backup files / DSMENC1 passphrases | Host-side | List / verify / dry-run metadata only |
| Cloud IAM / Proton Drive credentials | Host-side adapters | **Never** on phone |

## Hard rules

1. **No master-key on mobile.** GrapheneOS / stock Android companions authenticate to the host REST API; they do not decrypt `*.enc` stores.
2. **Sanitized by default.** `GET /api/v1/connections` and `db-storage-manager-export` redact password-like fields unless the operator explicitly opts into plaintext export with consent (desktop air-gap only).
3. **Pairing token ≠ master key.** `db-storage-manager-pair` stores only a SHA-256 digest in SecureStore `settings.companion`. The plaintext Bearer is shown once for phone entry.
4. **Prefer tunnel over LAN.** Bind `127.0.0.1`; reach the API via SSH/VPN from the phone. Cleartext HTTP is localhost / trusted-tunnel only until TLS termination is shipped.
5. **Least privilege.** Prefer RBAC HTTP Basic with a `viewer` account for glance-only phones; treat Bearer as system-admin strength.

## Credential export format

Format id: `dsm-companion-export` (version `1`).

```bash
# Safe metadata (default) — suitable as an offline inventory snapshot
db-storage-manager-export -o /tmp/dsm-export.json

# Dangerous: plaintext secrets — requires --i-consent; never load on a phone
db-storage-manager-export --include-secrets --i-consent -o /tmp/dsm-secrets.json
```

Document fields include `secrets_mode` (`redacted` | `plaintext_with_consent`), `warnings[]`, pairing fingerprint (not the token), and connection profiles. See [android-grapheneos.md](android-grapheneos.md) and [cross-platform.md](cross-platform.md).

## Pairing flow

```bash
db-storage-manager-pair                 # print token once on stderr
db-storage-manager-pair --status        # fingerprint only
db-storage-manager-pair --revoke
./scripts/run-api-local.sh              # accepts DSM_API_TOKEN and/or pairing Bearer
```

On the Android companion: enter base URL (usually via SSH forward to `127.0.0.1:8765`) and the Bearer token. The app stores the token in EncryptedSharedPreferences and calls health / connections / backups read APIs only.

## Residual risks / out of scope for this review

- Companion remains **plain HTTP** — TLS termination not shipped.
- Sideload APK integrity is the operator’s responsibility until F-Droid / signed release metadata exists.
- Export with `--include-secrets` can still be mishandled; tooling refuses without `--i-consent` but cannot stop unsafe sharing of the resulting file.

## Related

- [android-grapheneos.md](android-grapheneos.md) — install / sideload / opsec
- [cross-platform.md](cross-platform.md) — shared trust model
- [api.md](api.md) — REST surface
- [SECURITY.md](../SECURITY.md) — project security policy
