namespace AleWorkbench.Launcher.Models;

/// <summary>Overall workbench state, shown to the user in Chinese labels.</summary>
public enum WorkbenchState
{
    Unknown,
    Stopped,
    Starting,
    Running,
    Degraded,
    Foreign,
    Stopping,
    Failed,
}

public sealed class StatusInfo
{
    public WorkbenchState State { get; set; } = WorkbenchState.Unknown;
    public bool Healthy { get; set; }
    public string Database { get; set; } = "unknown";
    public int? Pid { get; set; }
    public string Message { get; set; } = "";
    public string Detail { get; set; } = "";
    public string AccessUrl { get; set; } = "";
    public bool FrontendReady { get; set; }
    /// <summary>Startup progress 0..100, or -1 when unknown/indeterminate.</summary>
    public double ProgressValue { get; set; } = -1;
    /// <summary>Human-readable step label reported while starting.</summary>
    public string ProgressMessage { get; set; } = "";
    /// <summary>Temporary public tunnel URL (https://*.trycloudflare.com), empty when not started.</summary>
    public string TunnelUrl { get; set; } = "";
}
