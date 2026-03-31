using System.ComponentModel;
using System.Drawing;
using Squid4Win.Tray.Features;
using Squid4Win.Tray.Services;
using Squid4Win.Tray.ViewModels;
using Forms = System.Windows.Forms;

namespace Squid4Win.Tray.Tray;

public sealed class TrayIconHost : IDisposable
{
    private const int NotifyIconTextLimit = 63;
    private readonly MainWindow mainWindow;
    private readonly Forms.NotifyIcon notifyIcon;
    private readonly Forms.ToolStripMenuItem serviceStatusItem;
    private readonly Forms.ToolStripMenuItem startServiceItem;
    private readonly Forms.ToolStripMenuItem stopServiceItem;
    private readonly Forms.ToolStripMenuItem restartServiceItem;
    private bool disposed;

    public TrayIconHost(MainWindow mainWindow)
    {
        this.mainWindow = mainWindow;

        serviceStatusItem = new Forms.ToolStripMenuItem
        {
            Enabled = false
        };

        startServiceItem = new Forms.ToolStripMenuItem("Start service", null, async (_, _) => await ExecuteServiceActionAsync(mainWindow.ViewModel.StartServiceAsync));
        stopServiceItem = new Forms.ToolStripMenuItem("Stop service", null, async (_, _) => await ExecuteServiceActionAsync(mainWindow.ViewModel.StopServiceAsync));
        restartServiceItem = new Forms.ToolStripMenuItem("Restart service", null, async (_, _) => await ExecuteServiceActionAsync(mainWindow.ViewModel.RestartServiceAsync));

        notifyIcon = new Forms.NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = BuildNotifyIconText("Starting"),
            ContextMenuStrip = BuildContextMenu(),
            Visible = false
        };

        notifyIcon.DoubleClick += (_, _) => ShowDashboard();
        mainWindow.ViewModel.PropertyChanged += HandleViewModelPropertyChanged;
    }

    public void Initialize()
    {
        UpdateServiceStatus();
        notifyIcon.Visible = true;
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }

        disposed = true;
        mainWindow.ViewModel.PropertyChanged -= HandleViewModelPropertyChanged;
        notifyIcon.Visible = false;
        notifyIcon.Dispose();
    }

    private Forms.ContextMenuStrip BuildContextMenu()
    {
        var contextMenu = new Forms.ContextMenuStrip();
        contextMenu.Opening += (_, _) => UpdateServiceStatus();

        contextMenu.Items.Add(new Forms.ToolStripMenuItem("Open dashboard", null, (_, _) => ShowDashboard()));
        contextMenu.Items.Add(new Forms.ToolStripMenuItem("Refresh status", null, (_, _) => UpdateServiceStatus()));
        contextMenu.Items.Add(new Forms.ToolStripSeparator());
        contextMenu.Items.Add(serviceStatusItem);
        contextMenu.Items.Add(startServiceItem);
        contextMenu.Items.Add(stopServiceItem);
        contextMenu.Items.Add(restartServiceItem);
        contextMenu.Items.Add(new Forms.ToolStripSeparator());

        foreach (var feature in mainWindow.ViewModel.RegisteredFeatures)
        {
            contextMenu.Items.Add(new Forms.ToolStripMenuItem(feature.DisplayName, null, async (_, _) => await ExecuteFeatureAsync(feature)));
        }

        contextMenu.Items.Add(new Forms.ToolStripSeparator());
        contextMenu.Items.Add(new Forms.ToolStripMenuItem("Exit", null, (_, _) => ExitApplication()));
        return contextMenu;
    }

    private void ShowDashboard()
    {
        mainWindow.ShowDashboard();
        ApplyViewModelStateToTray();
    }

    private void UpdateServiceStatus()
    {
        mainWindow.ViewModel.RefreshDashboard();
        ApplyViewModelStateToTray();
    }

    private async Task ExecuteServiceActionAsync(Func<CancellationToken, Task<ServiceActionResult>> action)
    {
        try
        {
            var result = await action(CancellationToken.None);
            ApplyViewModelStateToTray();

            System.Windows.MessageBox.Show(
                result.Message,
                "Squid4Win",
                System.Windows.MessageBoxButton.OK,
                result.Succeeded ? System.Windows.MessageBoxImage.Information : System.Windows.MessageBoxImage.Warning);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                $"The tray app hit an unexpected error while talking to Windows services:{Environment.NewLine}{ex.Message}",
                "Squid4Win",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Error);
        }
    }

    private static async Task ExecuteFeatureAsync(TrayFeature feature)
    {
        try
        {
            await feature.ExecuteAsync(CancellationToken.None);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                $"The {feature.DisplayName} feature failed to launch:{Environment.NewLine}{ex.Message}",
                "Squid4Win",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Error);
        }
    }

    private void HandleViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(MainWindowViewModel.ServiceStatus)
            or nameof(MainWindowViewModel.CanStartService)
            or nameof(MainWindowViewModel.CanStopService)
            or nameof(MainWindowViewModel.CanRestartService))
        {
            ApplyViewModelStateToTray();
        }
    }

    private void ApplyViewModelStateToTray()
    {
        var viewModel = mainWindow.ViewModel;
        serviceStatusItem.Text = $"{viewModel.ServiceName}: {viewModel.ServiceStatus}";
        startServiceItem.Enabled = viewModel.CanStartService;
        stopServiceItem.Enabled = viewModel.CanStopService;
        restartServiceItem.Enabled = viewModel.CanRestartService;
        notifyIcon.Text = BuildNotifyIconText(viewModel.ServiceStatus);
    }

    private static string BuildNotifyIconText(string serviceStatus)
    {
        var text = $"Squid4Win Tray - {serviceStatus}";
        return text.Length <= NotifyIconTextLimit ? text : text[..NotifyIconTextLimit];
    }

    private void ExitApplication()
    {
        mainWindow.BeginShutdown();
        mainWindow.Close();
        System.Windows.Application.Current.Shutdown();
    }
}
