using System.Collections.ObjectModel;
using System.Windows;
using Arrow.Core.Models;
using Arrow.Core.Realtime;
using Arrow.Core.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace Arrow.Wpf.ViewModels;

public sealed partial class MessagesViewModel : ObservableObject
{
    private readonly IArrowApiClient _api;
    private readonly IArrowWebSocket _ws;

    public ObservableCollection<Message> Messages { get; } = new();
    [ObservableProperty] private string _draftContent = "";

    public MessagesViewModel(IArrowApiClient api, IArrowWebSocket ws)
    {
        _api = api;
        _ws  = ws;
        _ws.EventReceived += OnWsEvent;
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        try
        {
            var list = await _api.GetMessagesAsync();
            Application.Current?.Dispatcher.Invoke(() =>
            {
                Messages.Clear();
                foreach (var m in list) Messages.Add(m);
            });
        }
        catch { }
    }

    [RelayCommand]
    private async Task SendBroadcastAsync()
    {
        var text = DraftContent.Trim();
        if (string.IsNullOrEmpty(text)) return;
        try
        {
            await _api.SendMessageAsync(new MessageDraft(text, MessageType: "BROADCAST"));
            DraftContent = "";
        }
        catch { }
    }

    private void OnWsEvent(object? _, ArrowWsEvent e)
    {
        if (e.Channel == ArrowChannels.Chat) _ = RefreshAsync();
    }
}
