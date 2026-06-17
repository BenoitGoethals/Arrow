# Arrow Front WPF

.NET 9 + WPF reimplementation of the Python `front/` desktop COP application.

Replaces PyQt6 + QWebEngineView with WPF + WebView2, preserving the same
operational architecture: REST + WebSocket against the Arrow backend, with
Leaflet running inside an embedded browser.

---

## Requirements

- **Windows 10 / 11** (this is a WPF project — won't run on macOS/Linux)
- **.NET 9 SDK** — install from https://dotnet.microsoft.com/download/dotnet/9.0
- **WebView2 runtime** — preinstalled on Windows 11, on Windows 10 install the
  Evergreen runtime from https://developer.microsoft.com/microsoft-edge/webview2/

## Build & run

```powershell
cd front-wpf
dotnet restore
dotnet build
dotnet run --project src/Arrow.Wpf
```

The app expects the Arrow backend on `http://localhost:6001` by default. Change
it in the login dialog.

---

## Architecture

```
front-wpf/
├─ Arrow.Wpf.sln                       solution
├─ global.json                          pins .NET 9
└─ src/
   ├─ Arrow.Core/                       no WPF dependencies — pure C# library
   │  ├─ Models/                        DTOs for Operator, Alert, Message…
   │  ├─ Services/
   │  │  ├─ IArrowApiClient + impl      REST surface (HttpClient)
   │  │  ├─ IAuthStore + impl           Windows Credential Manager backed
   │  ├─ Realtime/
   │  │  ├─ IArrowWebSocket + impl      reconnecting ClientWebSocket reader
   │  │  └─ ArrowWsEvents.cs            channel constants + event record
   │  └─ Configuration/
   │     └─ ArrowOptions.cs             server URL + token + WS URI
   └─ Arrow.Wpf/                        WPF application
      ├─ App.xaml.cs                    DI host + auto-login + launch flow
      ├─ Map/index.html                 Leaflet COP page (WebView2 host)
      ├─ Resources/Theme.xaml           Dark tactical theme
      ├─ Services/
      │  ├─ AppState.cs                 session-wide state (operator, mission)
      │  ├─ DialogService.cs            MessageBox wrapper
      │  └─ MapBridge.cs                WebView2 ↔ ViewModel two-way bridge
      ├─ ViewModels/
      │  ├─ LoginViewModel.cs           login + persist to credential vault
      │  ├─ MainViewModel.cs            ties everything together
      │  ├─ OrbatViewModel.cs           hierarchy refresh + WS subscriptions
      │  ├─ AlertsViewModel.cs          alerts with WS push + toast hook
      │  ├─ MessagesViewModel.cs        chat list + broadcast send
      │  ├─ ReportsViewModel.cs         report queue
      │  └─ MissionsViewModel.cs        mission selector → AppState.ActiveMission
      └─ Views/
         ├─ MainWindow.xaml             3-column splitter + tab control
         ├─ LoginWindow.xaml            modal login
         ├─ Controls/MapControl.xaml    WebView2 host
         └─ Panels/                     UserControls bound to the VMs above
```

## What's implemented

| Feature | Status |
|---------|--------|
| Login + auto-login from Windows Credential vault | ✅ |
| Auth-aware REST client (`Bearer` JWT) | ✅ |
| Reconnecting WebSocket reader (12+ channels) | ✅ |
| Main 3-column shell (ORBAT / map / tabs / status bar / toolbar) | ✅ |
| Leaflet map embedded via WebView2 + virtual host mapping | ✅ |
| Two-way map bridge: coords, click, radial, track-click, symbol-place | ✅ |
| ORBAT live hierarchy tree (online indicators) | ✅ |
| Alerts panel with WS push, location + zoom on trigger | ✅ |
| Messages panel with broadcast send | ✅ |
| Reports panel (live feed) | ✅ |
| Missions panel (active mission selector) | ✅ |
| Toolbar: Fit / base-layer switching / TIC + MEDICAL emergency buttons | ✅ |
| Status bar: MGRS cursor + connection state | ✅ |
| Tactical theme | ✅ |

## What's stubbed (placeholder tabs)

| Panel | Notes |
|-------|-------|
| Draw   | Wire to `IMapBridge` draw commands (phase line, boundary, NFA, FFA, objective…) |
| Strike | `IArrowApiClient.GetStrikePackagesAsync` to add + UI |
| OPORD  | Editor window + snapshot gallery |
| Streams | Live tabs for Android / Octopus / external; spawn StreamViewerWindow |
| Media  | Photo/video gallery with Bearer-auth fetch + caching |
| Mumble | Voice comms — likely via NAudio + Mumble client lib |
| Log    | Real-time tail of `arrow-.log` (Serilog file sink already configured) |
| Routes | Polyline draw + GPX import + navigation HUD |

## Extending — add a new panel in 5 steps

1. **ViewModel** — copy `ReportsViewModel.cs`, replace the type + endpoint
2. **DI** — register `services.AddSingleton<YourViewModel>()` in `App.xaml.cs`
3. **View** — copy `Views/Panels/ReportsPanel.xaml` + code-behind
4. **MainViewModel** — add a property exposing the new VM
5. **MainWindow.xaml** — add a `<TabItem>` binding to that property

WebSocket events: subscribe inside the VM constructor to `_ws.EventReceived`
and filter on `e.Channel` (see `ArrowChannels.*` for the constant list).

## Storage

| Resource | Path |
|----------|------|
| Credentials | Windows Credential Manager (target: `Arrow.Wpf.Credentials`) |
| Logs | `%LOCALAPPDATA%\Arrow\logs\arrow-{date}.log` |
| WebView2 data | `%LOCALAPPDATA%\Arrow\WebView2\` |

## Notes

- **No file:// for the map** — same issue the Python version hit on macOS with
  the Metal compositor. We use WebView2's `SetVirtualHostNameToFolderMapping`
  to serve the Leaflet HTML under `https://arrow-map.invalid/` so it has a
  proper origin without spinning up an HTTP server.
- **MVVM** — CommunityToolkit.Mvvm provides `[ObservableProperty]` /
  `[RelayCommand]` source generators. No INotifyPropertyChanged boilerplate.
- **DI** — Microsoft.Extensions.Hosting hosts the DI container so the
  ViewModels can take services through constructor injection naturally.
- **Async** — all REST and WS work is async; UI updates marshal through
  `Application.Current.Dispatcher.Invoke`.
