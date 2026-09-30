# Northstar NAS100 Dashboard

Flutter client for the trading bot's FastAPI service. The backend owns broker access and persistence; this frontend communicates with it through the HTTP API.

## Modules

- `lib/main.dart` starts the Flutter application.
- `lib/app.dart` configures the Material app and shared theme.
- `lib/screens/dashboard_page.dart` owns dashboard state, polling, and screen composition.
- `lib/services/api_client.dart` contains the HTTP requests to the backend.

The current product has one dashboard screen with account, risk, positions, and activity sections. These are dashboard sections, not independent deployable microservices; the API/backend remains the service boundary.

## Run

From this directory:

```powershell
flutter pub get
flutter run -d chrome --web-port=8080
```

Start the API from the repository root in another terminal:

```powershell
$env:TRADING_BOT_CORS_ORIGINS = "http://localhost:8080"
uv run --project trading_bot python -m trading_bot.main --api
```

The default API address is `http://127.0.0.1:8000`. On Android Emulator, change it in Connection settings to `http://10.0.2.2:8000`.
