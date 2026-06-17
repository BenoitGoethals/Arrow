using System.IO;
using System.Windows.Controls;
using Arrow.Wpf.Services;
using Microsoft.Web.WebView2.Core;

namespace Arrow.Wpf.Views.Controls;

/// <summary>
/// Hosts the Leaflet-based tactical COP page in a WebView2.  We serve the page
/// using WebView2's virtual host name mapping so the HTML lives on disk under
/// <c>Map\</c> in the output folder and runs with a stable origin
/// (<c>https://arrow-map.invalid/</c>) — clean URLs and no local file:// quirks.
/// </summary>
public partial class MapControl : UserControl
{
    private IMapBridge? _bridge;

    public MapControl()
    {
        InitializeComponent();
        Loaded += async (_, _) => await InitWebAsync();
    }

    public void AttachBridge(IMapBridge bridge)
    {
        _bridge = bridge;
        if (WebView.CoreWebView2 is not null && _bridge is MapBridge mb)
            mb.Attach(WebView);
    }

    private async Task InitWebAsync()
    {
        var userData = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Arrow", "WebView2");
        Directory.CreateDirectory(userData);

        var env = await CoreWebView2Environment.CreateAsync(null, userData);
        await WebView.EnsureCoreWebView2Async(env);

        var mapDir = Path.Combine(AppContext.BaseDirectory, "Map");
        WebView.CoreWebView2.SetVirtualHostNameToFolderMapping(
            "arrow-map.invalid", mapDir, CoreWebView2HostResourceAccessKind.Allow);

        if (_bridge is MapBridge mb) mb.Attach(WebView);

        WebView.CoreWebView2.Navigate("https://arrow-map.invalid/index.html");
    }
}
