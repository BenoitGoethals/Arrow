using System.Windows;
using System.Windows.Controls;

namespace Arrow.Wpf.Views.Panels;

public partial class PlaceholderPanel : UserControl
{
    public static readonly DependencyProperty PanelNameProperty =
        DependencyProperty.Register(nameof(PanelName), typeof(string), typeof(PlaceholderPanel),
            new PropertyMetadata("PANEL"));

    public static readonly DependencyProperty DescriptionProperty =
        DependencyProperty.Register(nameof(Description), typeof(string), typeof(PlaceholderPanel),
            new PropertyMetadata("Not yet implemented in the WPF port. Add a ViewModel + UserControl following the OrbatViewModel template."));

    public string PanelName
    {
        get => (string)GetValue(PanelNameProperty);
        set => SetValue(PanelNameProperty, value);
    }

    public string Description
    {
        get => (string)GetValue(DescriptionProperty);
        set => SetValue(DescriptionProperty, value);
    }

    public PlaceholderPanel() { InitializeComponent(); }
}
