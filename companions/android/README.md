# DSM Companion (Android / GrapheneOS)

Kotlin glance client for the desktop REST companion (`db-storage-manager-api`).
Sideload / debug APK first — **no** Google Play Services, **no** F-Droid listing yet.

Privacy model: [docs/privacy-companion.md](../../docs/privacy-companion.md) ·
install guide: [docs/android-grapheneos.md](../../docs/android-grapheneos.md).

## Requirements

- JDK **17** (Android Gradle Plugin)
- Android SDK with `platforms;android-35` and build-tools
- Desktop host running the API with a pairing token or `DSM_API_TOKEN`

## Build (debug APK)

```bash
cd companions/android
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/Android/Sdk   # or /opt/android-sdk
./gradlew :app:assembleDebug
```

APK path:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Sideload (GrapheneOS / stock)

1. Enable developer options → USB debugging (or allow install from USB/files).
2. Prefer ADB over random APK mirrors:

   ```bash
   adb install -r app/build/outputs/apk/debug/app-debug.apk
   ```

3. On the desktop:

   ```bash
   db-storage-manager-pair
   ./scripts/run-api-local.sh
   # From the phone: SSH local forward to 127.0.0.1:8765 on the desktop
   ```

4. In the app: set base URL (usually `http://127.0.0.1:8765` via tunnel), paste Bearer token, **Save pairing**, then Health / Connections / Backups.

## Opsec

- Token lives in EncryptedSharedPreferences only.
- Do not paste `.master-key`, connection passwords, or `--include-secrets` export files into the phone.
- Cleartext HTTP is restricted to loopback / emulator alias (`10.0.2.2`) via network security config.

## Out of scope (this foundation)

- F-Droid / Play Store metadata
- Query console, restore, or on-device database engines
- TLS termination (use SSH/VPN until shipped)
