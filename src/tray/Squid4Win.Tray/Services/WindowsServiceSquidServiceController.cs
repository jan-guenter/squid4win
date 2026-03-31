using System.ComponentModel;
using System.ServiceProcess;

namespace Squid4Win.Tray.Services;

public sealed class WindowsServiceSquidServiceController : ISquidServiceController
{
    private static readonly TimeSpan DefaultActionTimeout = TimeSpan.FromSeconds(15);
    private readonly TimeSpan actionTimeout;

    public WindowsServiceSquidServiceController(string serviceName, TimeSpan? actionTimeout = null)
    {
        if (string.IsNullOrWhiteSpace(serviceName))
        {
            throw new ArgumentException("A Windows service name is required.", nameof(serviceName));
        }

        ServiceName = serviceName.Trim();
        this.actionTimeout = actionTimeout is { } timeout && timeout > TimeSpan.Zero
            ? timeout
            : DefaultActionTimeout;
    }

    public string ServiceName { get; }

    public ServiceStatusSnapshot GetStatus()
    {
        using var controller = CreateController();

        try
        {
            controller.Refresh();
            return CreateSnapshot(controller);
        }
        catch (InvalidOperationException ex) when (IsServiceMissing(ex))
        {
            return CreateNotInstalledStatus();
        }
        catch (Exception ex) when (IsServiceOperationException(ex))
        {
            return CreateUnknownStatus($"Windows could not query the {ServiceName} service. {GetFriendlyExceptionMessage(ex)}");
        }
    }

    public Task<ServiceActionResult> StartAsync(CancellationToken cancellationToken = default)
    {
        return Task.Run(() => StartCore(cancellationToken), cancellationToken);
    }

    public Task<ServiceActionResult> StopAsync(CancellationToken cancellationToken = default)
    {
        return Task.Run(() => StopCore(cancellationToken), cancellationToken);
    }

    public Task<ServiceActionResult> RestartAsync(CancellationToken cancellationToken = default)
    {
        return Task.Run(() => RestartCore(cancellationToken), cancellationToken);
    }

    public void Dispose()
    {
    }

    private ServiceActionResult StartCore(CancellationToken cancellationToken)
    {
        using var controller = CreateController();

        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            controller.Refresh();

            return controller.Status switch
            {
                ServiceControllerStatus.Running => CreateResult(true, CreateSnapshot(controller), $"{ServiceName} is already running."),
                ServiceControllerStatus.Paused => ContinueService(controller, cancellationToken),
                ServiceControllerStatus.Stopped => StartStoppedService(controller, $"{ServiceName} started successfully.", cancellationToken),
                ServiceControllerStatus.StartPending or ServiceControllerStatus.ContinuePending or ServiceControllerStatus.StopPending or ServiceControllerStatus.PausePending => CreateBusyResult("start"),
                _ => CreateUnexpectedStateResult("start")
            };
        }
        catch (InvalidOperationException ex) when (IsServiceMissing(ex))
        {
            return CreateResult(false, CreateNotInstalledStatus(), $"{ServiceName} is not installed as a Windows service yet.");
        }
        catch (Exception ex) when (IsServiceOperationException(ex))
        {
            return CreateResult(false, GetStatus(), BuildActionFailureMessage("start", ex));
        }
    }

    private ServiceActionResult StopCore(CancellationToken cancellationToken)
    {
        using var controller = CreateController();

        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            controller.Refresh();

            return controller.Status switch
            {
                ServiceControllerStatus.Running or ServiceControllerStatus.Paused => StopRunningService(controller, cancellationToken),
                ServiceControllerStatus.Stopped => CreateResult(true, CreateSnapshot(controller), $"{ServiceName} is already stopped."),
                ServiceControllerStatus.StartPending or ServiceControllerStatus.ContinuePending or ServiceControllerStatus.StopPending or ServiceControllerStatus.PausePending => CreateBusyResult("stop"),
                _ => CreateUnexpectedStateResult("stop")
            };
        }
        catch (InvalidOperationException ex) when (IsServiceMissing(ex))
        {
            return CreateResult(false, CreateNotInstalledStatus(), $"{ServiceName} is not installed as a Windows service yet.");
        }
        catch (Exception ex) when (IsServiceOperationException(ex))
        {
            return CreateResult(false, GetStatus(), BuildActionFailureMessage("stop", ex));
        }
    }

    private ServiceActionResult RestartCore(CancellationToken cancellationToken)
    {
        using var controller = CreateController();

        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            controller.Refresh();

            return controller.Status switch
            {
                ServiceControllerStatus.Running or ServiceControllerStatus.Paused => RestartRunningService(controller, cancellationToken),
                ServiceControllerStatus.Stopped => StartStoppedService(controller, $"{ServiceName} was stopped and has now been started.", cancellationToken),
                ServiceControllerStatus.StartPending or ServiceControllerStatus.ContinuePending or ServiceControllerStatus.StopPending or ServiceControllerStatus.PausePending => CreateBusyResult("restart"),
                _ => CreateUnexpectedStateResult("restart")
            };
        }
        catch (InvalidOperationException ex) when (IsServiceMissing(ex))
        {
            return CreateResult(false, CreateNotInstalledStatus(), $"{ServiceName} is not installed as a Windows service yet.");
        }
        catch (Exception ex) when (IsServiceOperationException(ex))
        {
            return CreateResult(false, GetStatus(), BuildActionFailureMessage("restart", ex));
        }
    }

    private ServiceActionResult ContinueService(ServiceController controller, CancellationToken cancellationToken)
    {
        if (!controller.CanPauseAndContinue)
        {
            return CreateResult(false, CreateSnapshot(controller), $"{ServiceName} is paused, but Windows does not allow it to resume through the service controller.");
        }

        controller.Continue();
        WaitForStatus(controller, ServiceControllerStatus.Running, cancellationToken);
        return CreateResult(true, GetStatus(), $"{ServiceName} resumed successfully.");
    }

    private ServiceActionResult StartStoppedService(
        ServiceController controller,
        string successMessage,
        CancellationToken cancellationToken)
    {
        controller.Start();
        WaitForStatus(controller, ServiceControllerStatus.Running, cancellationToken);
        return CreateResult(true, GetStatus(), successMessage);
    }

    private ServiceActionResult StopRunningService(ServiceController controller, CancellationToken cancellationToken)
    {
        if (!controller.CanStop)
        {
            return CreateResult(false, CreateSnapshot(controller), $"{ServiceName} is running, but Windows reports that it cannot be stopped.");
        }

        controller.Stop();
        WaitForStatus(controller, ServiceControllerStatus.Stopped, cancellationToken);
        return CreateResult(true, GetStatus(), $"{ServiceName} stopped successfully.");
    }

    private ServiceActionResult RestartRunningService(ServiceController controller, CancellationToken cancellationToken)
    {
        if (!controller.CanStop)
        {
            return CreateResult(false, CreateSnapshot(controller), $"{ServiceName} cannot be stopped, so the tray app cannot restart it.");
        }

        controller.Stop();
        WaitForStatus(controller, ServiceControllerStatus.Stopped, cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        controller.Start();
        WaitForStatus(controller, ServiceControllerStatus.Running, cancellationToken);
        return CreateResult(true, GetStatus(), $"{ServiceName} restarted successfully.");
    }

    private ServiceActionResult CreateBusyResult(string action)
    {
        return CreateResult(
            false,
            GetStatus(),
            $"{ServiceName} is already changing state. Wait for the current transition to finish before trying to {action} it again.");
    }

    private ServiceActionResult CreateUnexpectedStateResult(string action)
    {
        return CreateResult(
            false,
            GetStatus(),
            $"Windows reported an unexpected state for {ServiceName}, so the tray app could not {action} it safely.");
    }

    private ServiceStatusSnapshot CreateSnapshot(ServiceController controller)
    {
        var state = controller.Status switch
        {
            ServiceControllerStatus.Stopped => SquidServiceState.Stopped,
            ServiceControllerStatus.StartPending or ServiceControllerStatus.ContinuePending => SquidServiceState.Starting,
            ServiceControllerStatus.Running => SquidServiceState.Running,
            ServiceControllerStatus.StopPending or ServiceControllerStatus.PausePending => SquidServiceState.Stopping,
            ServiceControllerStatus.Paused => SquidServiceState.Paused,
            _ => SquidServiceState.Unknown
        };

        return new ServiceStatusSnapshot(
            State: state,
            Summary: state.ToDisplayText(),
            Detail: CreateStateDetail(state),
            IsInstalled: true,
            CanStart: state is SquidServiceState.Stopped or SquidServiceState.Paused,
            CanStop: controller.CanStop && (state is SquidServiceState.Running or SquidServiceState.Paused),
            CanRestart: state is SquidServiceState.Running or SquidServiceState.Stopped or SquidServiceState.Paused);
    }

    private ServiceStatusSnapshot CreateNotInstalledStatus()
    {
        return new ServiceStatusSnapshot(
            State: SquidServiceState.NotInstalled,
            Summary: SquidServiceState.NotInstalled.ToDisplayText(),
            Detail: $"{ServiceName} is not installed as a Windows service yet. The tray app will keep showing the expected folders so you can verify the planned layout before the installer exists.",
            IsInstalled: false,
            CanStart: false,
            CanStop: false,
            CanRestart: false);
    }

    private static ServiceStatusSnapshot CreateUnknownStatus(string detail)
    {
        return new ServiceStatusSnapshot(
            State: SquidServiceState.Unknown,
            Summary: SquidServiceState.Unknown.ToDisplayText(),
            Detail: detail,
            IsInstalled: false,
            CanStart: false,
            CanStop: false,
            CanRestart: false);
    }

    private string CreateStateDetail(SquidServiceState state)
    {
        return state switch
        {
            SquidServiceState.Stopped => $"{ServiceName} is installed but currently stopped.",
            SquidServiceState.Starting => $"{ServiceName} is starting. Wait a moment for Windows to finish the transition.",
            SquidServiceState.Running => $"{ServiceName} is installed and currently running.",
            SquidServiceState.Stopping => $"{ServiceName} is stopping. Wait a moment for Windows to finish the transition.",
            SquidServiceState.Paused => $"{ServiceName} is paused. Use Start to resume it or Restart to cycle it.",
            _ => $"Windows reported an unknown state for {ServiceName}."
        };
    }

    private string BuildActionFailureMessage(string action, Exception ex)
    {
        return TryGetNativeErrorCode(ex) switch
        {
            5 => $"Windows denied access while trying to {action} {ServiceName}. Run the tray app as Administrator or use Services.msc.",
            1060 => $"{ServiceName} is not installed as a Windows service yet.",
            _ when ex is System.ServiceProcess.TimeoutException => $"{ServiceName} did not reach the expected state before the operation timed out.",
            _ => $"Windows could not {action} {ServiceName}. {GetFriendlyExceptionMessage(ex)}"
        };
    }

    private void WaitForStatus(
        ServiceController controller,
        ServiceControllerStatus desiredStatus,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        controller.WaitForStatus(desiredStatus, actionTimeout);
        cancellationToken.ThrowIfCancellationRequested();
    }

    private static ServiceActionResult CreateResult(bool succeeded, ServiceStatusSnapshot status, string message)
    {
        return new ServiceActionResult(succeeded, status, message);
    }

    private static string GetFriendlyExceptionMessage(Exception ex)
    {
        if (ex.InnerException is { Message.Length: > 0 } innerException)
        {
            return innerException.Message;
        }

        return ex.Message;
    }

    private static int? TryGetNativeErrorCode(Exception ex)
    {
        return ex switch
        {
            Win32Exception win32Exception => win32Exception.NativeErrorCode,
            InvalidOperationException { InnerException: Win32Exception win32Exception } => win32Exception.NativeErrorCode,
            _ => null
        };
    }

    private static bool IsServiceMissing(Exception ex)
    {
        return TryGetNativeErrorCode(ex) == 1060;
    }

    private static bool IsServiceOperationException(Exception ex)
    {
        return ex is InvalidOperationException
            or Win32Exception
            or System.ServiceProcess.TimeoutException;
    }

    private ServiceController CreateController()
    {
        return new ServiceController(ServiceName);
    }
}
