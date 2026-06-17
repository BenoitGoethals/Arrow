using System.Windows;
using Arrow.Core.Configuration;
using Arrow.Core.Realtime;
using Arrow.Core.Services;
using Arrow.Wpf.Services;
using Arrow.Wpf.ViewModels;
using Arrow.Wpf.Views;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Serilog;

namespace Arrow.Wpf;

public partial class App : Application
{
    private IHost? _host;

    public static IServiceProvider Services => ((App)Current)._host!.Services;

    [STAThread]
    public static void Main()
    {
        var app = new App();
        app.InitializeComponent();
        app.Run();
    }

    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        Log.Logger = new LoggerConfiguration()
            .MinimumLevel.Debug()
            .Enrich.FromLogContext()
            .WriteTo.Console()
            .WriteTo.File(
                Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Arrow", "logs", "arrow-.log"),
                rollingInterval: RollingInterval.Day,
                retainedFileCountLimit: 7)
            .CreateLogger();

        _host = Host.CreateDefaultBuilder()
            .ConfigureLogging(b => b.ClearProviders().AddSerilog())
            .ConfigureServices((ctx, services) =>
            {
                // Configuration
                services.AddOptions<ArrowOptions>();

                // Core
                services.AddSingleton<IAuthStore, WindowsCredentialAuthStore>();
                services.AddSingleton<IArrowApiClient, ArrowApiClient>();
                services.AddSingleton<IArrowWebSocket, ArrowWebSocket>();

                // UI services
                services.AddSingleton<IDialogService, DialogService>();
                services.AddSingleton<IMapBridge, MapBridge>();
                services.AddSingleton<AppState>();

                // ViewModels
                services.AddTransient<LoginViewModel>();
                services.AddSingleton<MainViewModel>();
                services.AddSingleton<OrbatViewModel>();
                services.AddSingleton<AlertsViewModel>();
                services.AddSingleton<MessagesViewModel>();
                services.AddSingleton<ReportsViewModel>();
                services.AddSingleton<MissionsViewModel>();

                // Views
                services.AddTransient<LoginWindow>();
                services.AddTransient<MainWindow>();
            })
            .Build();

        await _host.StartAsync();

        // Try auto-login from stored credentials, otherwise show LoginWindow.
        await BootAsync();
    }

    private async Task BootAsync()
    {
        var store   = Services.GetRequiredService<IAuthStore>();
        var opts    = Services.GetRequiredService<Microsoft.Extensions.Options.IOptions<ArrowOptions>>().Value;
        var api     = Services.GetRequiredService<IArrowApiClient>();
        var logger  = Services.GetRequiredService<ILogger<App>>();

        var stored = store.Load();
        if (stored is not null)
        {
            try
            {
                opts.ServerUrl = stored.ServerUrl;
                opts.Token     = stored.Token;
                var me = await api.MeAsync();
                logger.LogInformation("Auto-login OK as {Callsign} ({Role})", me.Callsign, me.Role);
                LaunchMain();
                return;
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Stored credentials invalid, falling back to login");
                store.Clear();
            }
        }

        ShowLogin();
    }

    private void ShowLogin()
    {
        var dlg = Services.GetRequiredService<LoginWindow>();
        dlg.Closed += (_, _) =>
        {
            if (dlg.DialogResult == true) LaunchMain();
            else                          Shutdown();
        };
        dlg.Show();
    }

    private void LaunchMain()
    {
        var win = Services.GetRequiredService<MainWindow>();
        win.Show();
    }

    protected override async void OnExit(ExitEventArgs e)
    {
        if (_host is not null)
        {
            var ws = Services.GetRequiredService<IArrowWebSocket>();
            await ws.DisposeAsync();
            await _host.StopAsync();
            _host.Dispose();
        }
        Log.CloseAndFlush();
        base.OnExit(e);
    }
}
