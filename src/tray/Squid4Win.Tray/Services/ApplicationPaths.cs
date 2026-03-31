using System.IO;

namespace Squid4Win.Tray.Services;

public sealed class ApplicationPaths
{
    private ApplicationPaths(string installRoot, string dataRoot)
    {
        InstallRoot = installRoot;
        DataRoot = dataRoot;
    }

    public string InstallRoot { get; }

    public string DataRoot { get; }

    public string ConfigDirectory => ResolveDirectory(
        Environment.GetEnvironmentVariable("SQUID4WIN_CONFIG_ROOT"),
        Path.Combine(DataRoot, "config"),
        Path.Combine(InstallRoot, "etc"));

    public string ConfigFilePath => ResolveFile(
        Environment.GetEnvironmentVariable("SQUID4WIN_CONFIG_FILE"),
        Path.Combine(DataRoot, "config", "squid.conf"),
        Path.Combine(InstallRoot, "etc", "squid.conf"));

    public string LogDirectory => ResolveDirectory(
        Environment.GetEnvironmentVariable("SQUID4WIN_LOG_ROOT"),
        Path.Combine(DataRoot, "logs"),
        Path.Combine(InstallRoot, "var", "logs"),
        Path.Combine(InstallRoot, "logs"));

    public string DiagnosticsDirectory => ResolveDirectory(
        Environment.GetEnvironmentVariable("SQUID4WIN_DIAGNOSTICS_ROOT"),
        Path.Combine(DataRoot, "diagnostics"),
        Path.Combine(InstallRoot, "var", "run"));

    public string ServiceExecutablePath => ResolveServiceExecutablePath();

    public static ApplicationPaths CreateDefault()
    {
        var installRootOverride = Environment.GetEnvironmentVariable("SQUID4WIN_ROOT");
        var installRoot = string.IsNullOrWhiteSpace(installRootOverride)
            ? AppContext.BaseDirectory
            : installRootOverride;

        installRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(installRoot));

        var dataRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "Squid4Win");

        return new ApplicationPaths(installRoot, dataRoot);
    }

    private static string NormalizePath(string path)
    {
        return Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
    }

    private static string ResolveDirectory(string? overridePath, params string[] candidates)
    {
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            return NormalizePath(overridePath);
        }

        foreach (var candidate in candidates)
        {
            if (Directory.Exists(candidate))
            {
                return NormalizePath(candidate);
            }
        }

        return NormalizePath(candidates[0]);
    }

    private static string ResolveFile(string? overridePath, params string[] candidates)
    {
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            return NormalizePath(overridePath);
        }

        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return NormalizePath(candidate);
            }
        }

        return NormalizePath(candidates[0]);
    }

    private string ResolveServiceExecutablePath()
    {
        var binPath = Path.Combine(InstallRoot, "bin", "squid.exe");
        if (File.Exists(binPath))
        {
            return binPath;
        }

        var sbinPath = Path.Combine(InstallRoot, "sbin", "squid.exe");
        return File.Exists(sbinPath) ? sbinPath : binPath;
    }
}
