namespace Arrow.Wpf.Services;

public interface IDialogService
{
    void Info(string message, string? title = null);
    void Error(string message, string? title = null);
    bool Confirm(string message, string? title = null);
}

public sealed class DialogService : IDialogService
{
    public void Info(string m, string? t = null) =>
        System.Windows.MessageBox.Show(m, t ?? "Arrow",
            System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Information);

    public void Error(string m, string? t = null) =>
        System.Windows.MessageBox.Show(m, t ?? "Arrow — Error",
            System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Error);

    public bool Confirm(string m, string? t = null) =>
        System.Windows.MessageBox.Show(m, t ?? "Arrow",
            System.Windows.MessageBoxButton.YesNo,
            System.Windows.MessageBoxImage.Question) == System.Windows.MessageBoxResult.Yes;
}
