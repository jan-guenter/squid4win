namespace Squid4Win.Tray.Services;

public static class SquidServiceDefaults
{
    public const string DefaultServiceName = "Squid4Win";
    public const string ServiceNameEnvironmentVariable = "SQUID4WIN_SERVICE_NAME";

    public static string ResolveServiceName()
    {
        var serviceName = Environment.GetEnvironmentVariable(ServiceNameEnvironmentVariable);
        return string.IsNullOrWhiteSpace(serviceName) ? DefaultServiceName : serviceName.Trim();
    }
}
