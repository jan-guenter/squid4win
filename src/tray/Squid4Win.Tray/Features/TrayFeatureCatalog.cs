using System.Diagnostics;
using System.IO;
using Squid4Win.Tray.Services;

namespace Squid4Win.Tray.Features;

public sealed class TrayFeatureCatalog
{
    private readonly ApplicationPaths paths;

    public TrayFeatureCatalog(ApplicationPaths paths)
    {
        this.paths = paths;
    }

    public IReadOnlyList<TrayFeature> CreateFeatures()
    {
        return
        [
            new TrayFeature(
                "install-root",
                "Open install folder",
                $"Open the resolved Squid4Win install directory at {paths.InstallRoot}.",
                _ => OpenDirectoryOrExplainAsync(paths.InstallRoot, "install folder")),
            new TrayFeature(
                "config-directory",
                "Open config folder",
                $"Open the expected configuration directory at {paths.ConfigDirectory}.",
                _ => OpenDirectoryOrExplainAsync(paths.ConfigDirectory, "config folder")),
            new TrayFeature(
                "logs",
                "Open logs folder",
                $"Open the expected Squid log location at {paths.LogDirectory}.",
                _ => OpenDirectoryOrExplainAsync(paths.LogDirectory, "log folder"))
        ];
    }

    private static Task OpenDirectoryOrExplainAsync(string path, string featureName)
    {
        if (Directory.Exists(path))
        {
            OpenShellItem(path);
            return Task.CompletedTask;
        }

        System.Windows.MessageBox.Show(
            $"The expected {featureName} does not exist yet:{Environment.NewLine}{path}{Environment.NewLine}{Environment.NewLine}This is normal until Squid4Win has been installed or run for the first time.",
            "Squid4Win",
            System.Windows.MessageBoxButton.OK,
            System.Windows.MessageBoxImage.Information);

        return Task.CompletedTask;
    }

    private static void OpenShellItem(string path)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = path,
            UseShellExecute = true
        });
    }
}
