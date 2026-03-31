namespace Squid4Win.Tray.Services;

public static class SquidServiceStateExtensions
{
    public static string ToDisplayText(this SquidServiceState state)
    {
        return state switch
        {
            SquidServiceState.NotInstalled => "Not installed",
            SquidServiceState.Stopped => "Stopped",
            SquidServiceState.Starting => "Starting",
            SquidServiceState.Running => "Running",
            SquidServiceState.Stopping => "Stopping",
            SquidServiceState.Paused => "Paused",
            _ => "Unavailable"
        };
    }
}
