using System.ComponentModel;
using System.Windows;
using Squid4Win.Tray.Features;
using Squid4Win.Tray.Services;
using Squid4Win.Tray.ViewModels;

namespace Squid4Win.Tray;

public partial class MainWindow : Window
{
    private bool isShuttingDown;

    public MainWindow(MainWindowViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
    }

    public MainWindowViewModel ViewModel => (MainWindowViewModel)DataContext;

    public void ShowDashboard()
    {
        ViewModel.RefreshDashboard();

        if (!IsVisible)
        {
            Show();
        }

        ShowInTaskbar = true;

        if (WindowState == WindowState.Minimized)
        {
            WindowState = WindowState.Normal;
        }

        Activate();
        Topmost = true;
        Topmost = false;
        Focus();
    }

    private void RefreshButton_Click(object sender, RoutedEventArgs e)
    {
        ViewModel.RefreshDashboard();
    }

    private async void StartServiceButton_Click(object sender, RoutedEventArgs e)
    {
        await ExecuteServiceActionAsync(ViewModel.StartServiceAsync);
    }

    private async void StopServiceButton_Click(object sender, RoutedEventArgs e)
    {
        await ExecuteServiceActionAsync(ViewModel.StopServiceAsync);
    }

    private async void RestartServiceButton_Click(object sender, RoutedEventArgs e)
    {
        await ExecuteServiceActionAsync(ViewModel.RestartServiceAsync);
    }

    private async void FeatureActionButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.Button { Tag: TrayFeature feature })
        {
            return;
        }

        try
        {
            await feature.ExecuteAsync(CancellationToken.None);
            ViewModel.RefreshPathState();
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                $"The {feature.DisplayName} action failed to launch:{Environment.NewLine}{ex.Message}",
                "Squid4Win",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    public void HideToTray()
    {
        ShowInTaskbar = false;
        Hide();
    }

    private static async Task ExecuteServiceActionAsync(Func<CancellationToken, Task<ServiceActionResult>> action)
    {
        try
        {
            var result = await action(CancellationToken.None);
            System.Windows.MessageBox.Show(
                result.Message,
                "Squid4Win",
                MessageBoxButton.OK,
                result.Succeeded ? MessageBoxImage.Information : MessageBoxImage.Warning);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                $"The tray app hit an unexpected error while talking to Windows services:{Environment.NewLine}{ex.Message}",
                "Squid4Win",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    public void BeginShutdown()
    {
        isShuttingDown = true;
    }

    protected override void OnStateChanged(EventArgs e)
    {
        base.OnStateChanged(e);

        if (WindowState == WindowState.Minimized)
        {
            HideToTray();
        }
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        if (!isShuttingDown)
        {
            e.Cancel = true;
            HideToTray();
            return;
        }

        base.OnClosing(e);
    }
}
