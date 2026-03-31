using Squid4Win.Tray.Features;
using Squid4Win.Tray.Services;
using Squid4Win.Tray.Tray;
using Squid4Win.Tray.ViewModels;

namespace Squid4Win.Tray;

public partial class App : System.Windows.Application, IDisposable
{
    private bool disposed;
    private TrayIconHost? trayIconHost;
    private WindowsServiceSquidServiceController? serviceController;

    protected override void OnStartup(System.Windows.StartupEventArgs e)
    {
        base.OnStartup(e);

        var paths = ApplicationPaths.CreateDefault();
        serviceController = new WindowsServiceSquidServiceController(SquidServiceDefaults.ResolveServiceName());
        var featureCatalog = new TrayFeatureCatalog(paths);
        var features = featureCatalog.CreateFeatures();
        var viewModel = new MainWindowViewModel(paths, serviceController, features);
        var mainWindow = new MainWindow(viewModel);

        MainWindow = mainWindow;
        trayIconHost = new TrayIconHost(mainWindow);
        trayIconHost.Initialize();
    }

    protected override void OnExit(System.Windows.ExitEventArgs e)
    {
        Dispose();
        base.OnExit(e);
    }

    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    protected virtual void Dispose(bool disposing)
    {
        if (disposed)
        {
            return;
        }

        if (disposing)
        {
            trayIconHost?.Dispose();
            serviceController?.Dispose();
            trayIconHost = null;
            serviceController = null;
        }

        disposed = true;
    }
}
