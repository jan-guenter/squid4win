using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using Squid4Win.Tray.Features;
using Squid4Win.Tray.Services;

namespace Squid4Win.Tray.ViewModels;

public sealed class MainWindowViewModel : INotifyPropertyChanged
{
    private readonly ISquidServiceController serviceController;
    private string serviceStatus = "Checking status...";
    private string serviceStatusDetails = "Looking up the current Windows service state.";
    private string lastRefreshTime = string.Empty;
    private string installRootStatus = string.Empty;
    private string serviceExecutableStatus = string.Empty;
    private string dataRootStatus = string.Empty;
    private string configDirectoryStatus = string.Empty;
    private string configFileStatus = string.Empty;
    private string logDirectoryStatus = string.Empty;
    private bool canStartService;
    private bool canStopService;
    private bool canRestartService;

    public MainWindowViewModel(
        ApplicationPaths paths,
        ISquidServiceController serviceController,
        IReadOnlyList<TrayFeature> registeredFeatures)
    {
        Paths = paths;
        this.serviceController = serviceController;
        RegisteredFeatures = registeredFeatures;
        RefreshDashboard();
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public IReadOnlyList<TrayFeature> RegisteredFeatures { get; }

    public string ServiceName => serviceController.ServiceName;

    public string ServiceStatus
    {
        get => serviceStatus;
        private set => SetProperty(ref serviceStatus, value);
    }

    public string ServiceStatusDetails
    {
        get => serviceStatusDetails;
        private set => SetProperty(ref serviceStatusDetails, value);
    }

    public string LastRefreshTime
    {
        get => lastRefreshTime;
        private set => SetProperty(ref lastRefreshTime, value);
    }

    public bool CanStartService
    {
        get => canStartService;
        private set => SetProperty(ref canStartService, value);
    }

    public bool CanStopService
    {
        get => canStopService;
        private set => SetProperty(ref canStopService, value);
    }

    public bool CanRestartService
    {
        get => canRestartService;
        private set => SetProperty(ref canRestartService, value);
    }

    public string InstallRoot => Paths.InstallRoot;

    public string InstallRootStatus
    {
        get => installRootStatus;
        private set => SetProperty(ref installRootStatus, value);
    }

    public string DataRoot => Paths.DataRoot;

    public string DataRootStatus
    {
        get => dataRootStatus;
        private set => SetProperty(ref dataRootStatus, value);
    }

    public string ConfigDirectory => Paths.ConfigDirectory;

    public string ConfigDirectoryStatus
    {
        get => configDirectoryStatus;
        private set => SetProperty(ref configDirectoryStatus, value);
    }

    public string ConfigFilePath => Paths.ConfigFilePath;

    public string ConfigFileStatus
    {
        get => configFileStatus;
        private set => SetProperty(ref configFileStatus, value);
    }

    public string LogDirectory => Paths.LogDirectory;

    public string LogDirectoryStatus
    {
        get => logDirectoryStatus;
        private set => SetProperty(ref logDirectoryStatus, value);
    }

    public string ServiceExecutablePath => Paths.ServiceExecutablePath;

    public string ServiceExecutableStatus
    {
        get => serviceExecutableStatus;
        private set => SetProperty(ref serviceExecutableStatus, value);
    }

    private ApplicationPaths Paths { get; }

    public void RefreshDashboard()
    {
        ApplyStatus(serviceController.GetStatus());
        RefreshPathState();
    }

    public void RefreshPathState()
    {
        InstallRootStatus = DescribeDirectory(InstallRoot, "install root has not been created yet.");
        ServiceExecutableStatus = DescribeFile(ServiceExecutablePath, "squid.exe has not been staged here yet.");
        DataRootStatus = DescribeDirectory(DataRoot, "ProgramData may remain unused when Squid keeps runtime data under the install root.");
        ConfigDirectoryStatus = DescribeDirectory(ConfigDirectory, "configuration folder has not been created yet.");
        ConfigFileStatus = DescribeFile(ConfigFilePath, "squid.conf is not available yet.");
        LogDirectoryStatus = DescribeDirectory(LogDirectory, "log folder will appear after Squid runs.");
    }

    public Task<ServiceActionResult> StartServiceAsync(CancellationToken cancellationToken = default)
    {
        return ExecuteServiceActionAsync(serviceController.StartAsync, cancellationToken);
    }

    public Task<ServiceActionResult> StopServiceAsync(CancellationToken cancellationToken = default)
    {
        return ExecuteServiceActionAsync(serviceController.StopAsync, cancellationToken);
    }

    public Task<ServiceActionResult> RestartServiceAsync(CancellationToken cancellationToken = default)
    {
        return ExecuteServiceActionAsync(serviceController.RestartAsync, cancellationToken);
    }

    private async Task<ServiceActionResult> ExecuteServiceActionAsync(
        Func<CancellationToken, Task<ServiceActionResult>> action,
        CancellationToken cancellationToken)
    {
        var result = await action(cancellationToken);
        ApplyStatus(result.Status);
        RefreshPathState();
        return result;
    }

    private void ApplyStatus(ServiceStatusSnapshot status)
    {
        ServiceStatus = status.Summary;
        ServiceStatusDetails = status.Detail;
        CanStartService = status.CanStart;
        CanStopService = status.CanStop;
        CanRestartService = status.CanRestart;
        LastRefreshTime = $"Last checked {DateTime.Now:G}";
    }

    private static string DescribeDirectory(string path, string missingDescription)
    {
        return Directory.Exists(path) ? "Present" : $"Missing - {missingDescription}";
    }

    private static string DescribeFile(string path, string missingDescription)
    {
        return File.Exists(path) ? "Present" : $"Missing - {missingDescription}";
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
        {
            return;
        }

        storage = value;
        OnPropertyChanged(propertyName);
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
