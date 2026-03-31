namespace Squid4Win.Tray.Services;

public readonly record struct ServiceStatusSnapshot(
    SquidServiceState State,
    string Summary,
    string Detail,
    bool IsInstalled,
    bool CanStart,
    bool CanStop,
    bool CanRestart);
