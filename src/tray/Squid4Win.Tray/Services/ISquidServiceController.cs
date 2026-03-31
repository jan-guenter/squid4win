namespace Squid4Win.Tray.Services;

public interface ISquidServiceController : IDisposable
{
    string ServiceName { get; }

    ServiceStatusSnapshot GetStatus();

    Task<ServiceActionResult> StartAsync(CancellationToken cancellationToken = default);

    Task<ServiceActionResult> StopAsync(CancellationToken cancellationToken = default);

    Task<ServiceActionResult> RestartAsync(CancellationToken cancellationToken = default);
}
