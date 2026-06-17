using System.Globalization;
using System.Windows.Data;

namespace Arrow.Wpf.Services;

public sealed class BoolNegationConverter : IValueConverter
{
    public static readonly BoolNegationConverter Instance = new();

    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        => value is bool b ? !b : true;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => value is bool b ? !b : false;
}
