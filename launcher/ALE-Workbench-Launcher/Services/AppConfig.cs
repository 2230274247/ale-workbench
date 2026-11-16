using System;
using System.IO;
using System.Text.Json;

namespace AleWorkbench.Launcher.Services;

public sealed class AppConfig
{
    public string ProjectRoot { get; set; } = "";
    public string BackendHost { get; set; } = "127.0.0.1";
    public int BackendPort { get; set; } = 8002;
    public int DbPort { get; set; } = 3307;
    public string Mode { get; set; } = "local"; // "local" | "remote"
    public string RemoteUrl { get; set; } = "";
    public bool AutoStartOnLaunch { get; set; } = true;
    public bool OpenBrowserAfterStart { get; set; } = true;
    public bool MinimizeToTrayOnClose { get; set; } = true;
    public bool TunnelAutoStart { get; set; } = true;

    public bool IsLocal => Mode != "remote";

    public string BaseUrl => IsLocal
        ? $"http://{BackendHost}:{BackendPort}"
        : (string.IsNullOrWhiteSpace(RemoteUrl) ? "" : RemoteUrl.TrimEnd('/'));

    public string LoginUrl => IsLocal ? $"{BaseUrl}/login" : BaseUrl;

    public static string ConfigDirectory { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "ALE Workbench Launcher");

    public static string ConfigPath => Path.Combine(ConfigDirectory, "config.json");

    public string LogDirectory => Path.Combine(ConfigDirectory, "logs");

    public string StartScript => Path.Combine(ProjectRoot, "start-workbench.ps1");
    public string ControlScript => Path.Combine(ProjectRoot, "ale-ctl.ps1");
    public string FrontendIndex => Path.Combine(ProjectRoot, "frontend", "dist", "index.html");
    public string TunnelScript => Path.Combine(ProjectRoot, "tunnel.ps1");

    public bool IsLocalProjectValid =>
        !IsLocal || (!string.IsNullOrWhiteSpace(ProjectRoot) && File.Exists(StartScript) && File.Exists(ControlScript));

    public static AppConfig Load()
    {
        try
        {
            if (File.Exists(ConfigPath))
            {
                var cfg = JsonSerializer.Deserialize<AppConfig>(File.ReadAllText(ConfigPath));
                if (cfg != null)
                {
                    AutoDetectProjectRoot(cfg);
                    return cfg;
                }
            }
        }
        catch
        {
            // Corrupt config: fall back to defaults so the launcher still opens for repair.
        }
        var fresh = new AppConfig();
        AutoDetectProjectRoot(fresh);
        return fresh;
    }

    /// <summary>
    /// When the project root is unset, fall back to the launcher's own directory
    /// (the installer places the launcher exe next to the project files).
    /// </summary>
    private static void AutoDetectProjectRoot(AppConfig cfg)
    {
        if (!string.IsNullOrWhiteSpace(cfg.ProjectRoot) && File.Exists(cfg.StartScript)) return;
        var baseDir = AppContext.BaseDirectory.TrimEnd('\\', '/');
        if (File.Exists(Path.Combine(baseDir, "start-workbench.ps1")))
        {
            cfg.ProjectRoot = baseDir;
        }
    }

    public void Save()
    {
        Directory.CreateDirectory(ConfigDirectory);
        var json = JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(ConfigPath, json);
    }
}
