using System;
using System.IO;
using System.Text;

namespace AleWorkbench.Launcher.Services;

/// <summary>
/// Rotating launcher log. Never logs credentials; caps per-file size and file count.
/// </summary>
public sealed class LauncherLog
{
    private readonly object _lock = new();
    private readonly string _directory;
    private readonly string _path;
    private const long MaxBytes = 2 * 1024 * 1024;
    private const int MaxFiles = 5;

    public LauncherLog(string directory)
    {
        _directory = directory;
        try { Directory.CreateDirectory(_directory); } catch { }
        _path = System.IO.Path.Combine(_directory, "launcher.log");
    }

    public string Path => _path;

    public void Info(string message) => Write("INFO", message);
    public void Warn(string message) => Write("WARN", message);
    public void Error(string message) => Write("ERROR", message);
    public void Line(string message) => Write("LOG", message);

    private void Write(string level, string message)
    {
        var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} [{level}] {Sanitize(message)}";
        lock (_lock)
        {
            try
            {
                RotateIfNeeded();
                File.AppendAllText(_path, line + Environment.NewLine, Encoding.UTF8);
            }
            catch
            {
                // Logging must never crash the launcher.
            }
        }
    }

    private void RotateIfNeeded()
    {
        try
        {
            if (!File.Exists(_path)) return;
            if (new FileInfo(_path).Length < MaxBytes) return;
            for (int i = MaxFiles - 1; i >= 1; i--)
            {
                var src = System.IO.Path.Combine(_directory, $"launcher.{i}.log");
                var dst = System.IO.Path.Combine(_directory, $"launcher.{i + 1}.log");
                if (File.Exists(dst)) File.Delete(dst);
                if (File.Exists(src)) File.Move(src, dst);
            }
            File.Move(_path, System.IO.Path.Combine(_directory, "launcher.1.log"));
        }
        catch { }
    }

    private static string Sanitize(string message)
    {
        if (string.IsNullOrEmpty(message)) return message;
        return System.Text.RegularExpressions.Regex.Replace(message,
            @"(?i)(password|passwd|pwd|secret|token|apikey|api_key|authorization|cookie|jwt)\s*[=:]\s*[^\s,;]+",
            "$1=***");
    }
}
