# Fuel Finder mobile interface

This Expo/React Native app is a mobile frontend for the parent project's Google Maps-backed API in `server.py`.

## Run

From this directory:

```sh
npm install
npx expo start
```

Start the Python backend separately from the repository root with `python3 server.py`. It now listens on `0.0.0.0:8765` by default so a physical device can connect over the local network; set `HOST` or `PORT` to override these defaults. The app expects `POST /api/stations` on `http://localhost:8765` for web/iOS simulator or `http://10.0.2.2:8765` for Android emulator. For a physical phone, set `EXPO_PUBLIC_API_BASE_URL` to the backend machine’s LAN address, such as `http://192.168.1.20:8765`. Use HTTPS for deployed APIs.

The API key stays on the backend. The app uses device location only after the user taps the location button and grants permission; otherwise, it offers Hanoi area presets. The Google Routes response provides station distance and traffic-aware travel estimates. Queue length is not supplied by Google and is not represented as live data.

Sample stations appear until a live search succeeds. If the backend is not configured or reachable, the app explains the issue and keeps the sample list available. Estimates do not guarantee that the rider can reach a station; stop safely before interacting.

Run the ranking unit tests with `npm test`; export a web preview with `npx expo export --platform web`.
