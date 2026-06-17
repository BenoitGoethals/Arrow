using System.Windows;
using Arrow.Wpf.Services;
using Arrow.Wpf.ViewModels;

namespace Arrow.Wpf.Views;

public partial class MainWindow : Window
{
    private readonly MainViewModel _vm;
    private readonly IMapBridge    _bridge;

    public MainWindow(MainViewModel vm, IMapBridge bridge)
    {
        InitializeComponent();
        DataContext = _vm = vm;
        _bridge = bridge;

        Loaded += async (_, _) =>
        {
            MapView.AttachBridge(_bridge);
            await _vm.LoadAsync();
        };
    }
}
