# Arrow — Android Tactical App

Kotlin / Jetpack Compose operator client for the Arrow Soldier System Platform.

## Stack

- Kotlin 2.0 + Jetpack Compose (Material 3)
- AndroidX Navigation, DataStore (token + settings)
- OkHttp + kotlinx.serialization (REST + WebSocket)
- OSMdroid (offline-capable map)
- Google Play Services Location (Fused Location Provider)
- Foreground service for continuous GPS tracking

## Module map (mirrors §12 of the root README)

```
app/src/main/java/com/arrow/tactical/
 ├── auth/        # JWT login/register, TokenStore (DataStore)
 ├── settings/    # Server URL, callsign, team — DataStore-backed
 ├── network/     # ApiClient (OkHttp + auth interceptor), WsClient, DTOs
 ├── tracking/    # LocationService (foreground) → POST /tracking/position
 ├── map/         # OSMdroid Compose map; renders friendly operators live
 ├── messaging/   # Direct/group/broadcast chat
 ├── alerts/      # TIC / MEDICAL / EVAC / LOST_COMMS
 ├── reports/     # CONTACT / SPOT / CASEVAC / MEDEVAC / CAS (9-liners)
 ├── cot/         # CotEvent XML serialiser
 ├── offline/     # Tile cache directory helpers
 ├── di/          # AppContainer (composition root)
 └── ui/          # Theme + NavGraph
```

## Build

Open `android/` in Android Studio (Hedgehog or newer; AGP 8.7), let it sync,
then Run on a device/emulator.

From the CLI you'll need the Gradle wrapper jar (intentionally not committed):

```bash
cd android
gradle wrapper                # one-time, requires system Gradle 8.10+
./gradlew :app:assembleDebug
```

## Connecting to the backend

Default server URL is `http://10.0.2.2:6001` (Android emulator → host loopback).
On a physical device, open **Settings** in the app and point it at the host's
LAN IP, e.g. `http://192.168.1.10:6001`.

Use one of the seeded accounts from `backend/storage/seed.py`:

| Callsign | Password | Role |
| --- | --- | --- |
| `benoit` | `ranger14` | ADMIN |
| `capt`   | `ranger14` | BATTLE_CAPTAIN |
| `ALPHA-4` etc. | `ranger14` | OPERATOR |

The backend allows cleartext HTTP on the dev port. `usesCleartextTraffic="true"`
is set in the manifest for that reason — flip it off and add a TLS proxy for
production deployments.
