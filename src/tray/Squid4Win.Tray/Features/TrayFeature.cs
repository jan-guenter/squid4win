namespace Squid4Win.Tray.Features;

public sealed class TrayFeature
{
    public TrayFeature(string key, string displayName, string description, Func<CancellationToken, Task> executeAsync)
    {
        Key = key;
        DisplayName = displayName;
        Description = description;
        ExecuteAsync = executeAsync;
    }

    public string Key { get; }

    public string DisplayName { get; }

    public string Description { get; }

    public Func<CancellationToken, Task> ExecuteAsync { get; }
}
