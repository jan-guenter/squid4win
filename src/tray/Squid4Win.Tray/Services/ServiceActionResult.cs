namespace Squid4Win.Tray.Services;

public readonly record struct ServiceActionResult(bool Succeeded, ServiceStatusSnapshot Status, string Message);
