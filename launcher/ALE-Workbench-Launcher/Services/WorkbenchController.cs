using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AleWorkbench.Launcher.Models;

namespace AleWorkbench.Launcher.Services;

/// <summary>
/// Orchestrates backend start / stop / restart / status. Reuses the existing
/// security-hardened start-workbench.ps1 for start and ale-ctl.ps1 (which shares
/// the same process-identity verification) for stop/status, so process management
/// is never reimplemented here.
/// </summary>
public sealed class WorkbenchController
{
    private readonly AppConfig _config;
    private readonly LauncherLog _log;
    private readonly SemaphoreSlim _busy = new(1, 1);

    public WorkbenchController(AppConfig config, LauncherLog log)
    {
        _config = config;
        _log = log;
    }

    public string AccessUrl => _config.BaseUrl;
    public string LoginUrl => _config.LoginUrl;
    public bool IsLocal => _config.IsLocal;

    /// <summary>API version this desktop client is built against.</summary>
    public const string CompatibleApiVersion = "1.9.0";

    /// <summary>Read-only backend/API version probe (from /openapi.json), or null when unavailable.</summary>
    public string? QueryBackendVersion()
    {
        if (!_config.IsLocal) return null;
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
            var json = client.GetStringAsync($"{_config.BaseUrl}/openapi.json").GetAwaiter().GetResult();
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.TryGetProperty("info", out var info) && info.TryGetProperty("version", out var v))
                return v.GetString();
        }
        catch { }
        return null;
    }

    // ---- Status ----

    public StatusInfo QueryStatus()
    {
        var info = new StatusInfo
        {
            AccessUrl = _config.BaseUrl,
            FrontendReady = _config.IsLocal && File.Exists(_config.FrontendIndex),
        };

        if (!_config.IsLocal)
        {
            var ok = ProbeRemoteHealth();
            info.State = ok ? WorkbenchState.Running : WorkbenchState.Stopped;
            info.Healthy = ok;
            info.Database = ok ? "ok" : "unknown";
            info.Message = ok ? "远程服务可访问" : "远程服务不可访问";
            return info;
        }

        var json = RunScriptSync(_config.ControlScript, $"-Action status -Port {_config.BackendPort}", out _);
        if (string.IsNullOrWhiteSpace(json))
        {
            info.State = WorkbenchState.Stopped;
            info.Message = "无法执行状态脚本（请检查项目路径与 PowerShell）";
            return info;
        }

        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var state = root.TryGetProperty("state", out var s) ? s.GetString() ?? "" : "";
            info.Pid = root.TryGetProperty("pid", out var p) && p.TryGetInt32(out var pid) ? pid : null;
            info.Healthy = root.TryGetProperty("healthy", out var h) && h.GetBoolean();
            info.Database = root.TryGetProperty("database", out var d) ? d.GetString() ?? "unknown" : "unknown";
            info.Message = root.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "";
            info.Detail = root.TryGetProperty("detail", out var det) ? det.GetString() ?? "" : "";

            info.State = state switch
            {
                "running" => info.Healthy ? WorkbenchState.Running : WorkbenchState.Degraded,
                "foreign" => WorkbenchState.Foreign,
                _ => WorkbenchState.Stopped,
            };
        }
        catch
        {
            info.State = WorkbenchState.Stopped;
            info.Message = "状态解析失败";
        }
        return info;
    }

    private bool ProbeRemoteHealth()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
            var resp = client.GetAsync(_config.BaseUrl + "/health").GetAwaiter().GetResult();
            return resp.IsSuccessStatusCode;
        }
        catch { return false; }
    }

    // ---- Start ----

    public async Task<StatusInfo> StartAsync(IProgress<StatusInfo> progress, CancellationToken ct)
    {
        await _busy.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var starting = new StatusInfo
            {
                State = WorkbenchState.Starting,
                Message = "正在启动…",
                ProgressValue = 0,
                ProgressMessage = "正在准备启动…",
                AccessUrl = _config.BaseUrl,
            };
            progress.Report(starting);

            if (!_config.IsLocal)
            {
                var ok = ProbeRemoteHealth();
                var r = new StatusInfo
                {
                    State = ok ? WorkbenchState.Running : WorkbenchState.Failed,
                    Healthy = ok,
                    Message = ok ? "远程服务可访问" : "远程服务不可访问",
                    AccessUrl = _config.BaseUrl,
                };
                progress.Report(r);
                return r;
            }

            var current = QueryStatus();
            switch (current.State)
            {
                case WorkbenchState.Running:
                    progress.Report(current);
                    return current;
                case WorkbenchState.Degraded:
                    current.Message = "后端进程在运行，但健康检查未通过（数据库可能不可用）。请检查数据库后使用「重启」。";
                    progress.Report(current);
                    return current;
                case WorkbenchState.Foreign:
                    current.Message = $"端口 {_config.BackendPort} 被其他程序占用，已取消启动。";
                    progress.Report(current);
                    return current;
            }

            // Backend stopped: run the proven launcher (hidden), then poll for readiness.
            _log.Info("Starting backend via start-workbench.ps1.");
            var startProcess = StartScriptBackground();
            if (startProcess == null)
            {
                var fail = new StatusInfo { State = WorkbenchState.Failed, Message = "无法启动 start-workbench.ps1，请查看日志。", AccessUrl = _config.BaseUrl };
                progress.Report(fail);
                return fail;
            }

            var deadline = DateTime.UtcNow.AddSeconds(600);
            while (!ct.IsCancellationRequested && DateTime.UtcNow < deadline)
            {
                await Task.Delay(1500, ct).ConfigureAwait(false);
                var st = QueryStatus();
                if (st.State == WorkbenchState.Running)
                {
                    _log.Info("Backend ready.");
                    st.ProgressValue = 100;
                    st.ProgressMessage = "启动完成";
                    if (_config.TunnelAutoStart)
                    {
                        st.ProgressMessage = "正在开启公网隧道…";
                        progress.Report(st);
                        var tunnelUrl = StartTunnel();
                        if (!string.IsNullOrWhiteSpace(tunnelUrl))
                        {
                            st.TunnelUrl = tunnelUrl;
                            _log.Info("Tunnel ready: " + tunnelUrl);
                        }
                        else
                        {
                            _log.Warn("公网隧道启动失败或未安装 cloudflared。");
                        }
                    }
                    progress.Report(st);
                    return st;
                }
                if (startProcess.HasExited)
                {
                    var msg = startProcess.ExitCode == 0 ? "启动脚本已结束，但服务未就绪" : "启动失败";
                    st.State = WorkbenchState.Failed;
                    st.Message = msg + "，请查看日志。";
                    st.ProgressValue = 100;
                    st.ProgressMessage = "";
                    _log.Error($"Start failed (exit {startProcess.ExitCode}).");
                    progress.Report(st);
                    return st;
                }
                var (pv, pm) = ReadStartProgress();
                st.State = WorkbenchState.Starting;
                st.ProgressValue = pv;
                st.ProgressMessage = pm;
                st.Message = string.IsNullOrWhiteSpace(pm) ? "正在启动（安装依赖或等待服务就绪）…" : pm;
                progress.Report(st);
            }

            var timeout = new StatusInfo { State = WorkbenchState.Failed, Message = "启动超时，请查看日志。", AccessUrl = _config.BaseUrl };
            _log.Error("Start timed out.");
            progress.Report(timeout);
            return timeout;
        }
        finally
        {
            _busy.Release();
        }
    }

    private Process? StartScriptBackground()
    {
        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"{_config.StartScript}\" -NoBrowser -Port {_config.BackendPort} -DbPort {_config.DbPort}",
            WorkingDirectory = _config.ProjectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
        p.OutputDataReceived += (_, e) => { if (e.Data != null) _log.Line(e.Data); };
        p.ErrorDataReceived += (_, e) => { if (e.Data != null) _log.Line(e.Data); };
        try
        {
            if (!p.Start()) return null;
            p.BeginOutputReadLine();
            p.BeginErrorReadLine();
            return p;
        }
        catch (Exception ex)
        {
            _log.Error("Failed to start powershell: " + ex.Message);
            return null;
        }
    }

    private (double Value, string Message) ReadStartProgress()
    {
        var path = Path.Combine(_config.ProjectRoot, "backend", ".runtime", $"server-{_config.BackendPort}.progress.json");
        try
        {
            if (!File.Exists(path)) return (-1, "");
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            var value = root.TryGetProperty("progress", out var p) && p.TryGetDouble(out var d) ? d : -1;
            var message = root.TryGetProperty("message", out var m) ? m.GetString() ?? "" : "";
            return (value, message);
        }
        catch
        {
            return (-1, "");
        }
    }

    // ---- Stop ----

    public async Task<StatusInfo> StopAsync(IProgress<StatusInfo> progress, CancellationToken ct)
    {
        await _busy.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var stopping = new StatusInfo { State = WorkbenchState.Stopping, Message = "正在停止…", AccessUrl = _config.BaseUrl };
            progress.Report(stopping);

            if (!_config.IsLocal)
            {
                var r = new StatusInfo { State = WorkbenchState.Stopped, Message = "远程模式无需停止本地进程", AccessUrl = _config.BaseUrl };
                progress.Report(r);
                return r;
            }

            var json = RunScriptSync(_config.ControlScript, $"-Action stop -Port {_config.BackendPort}", out _);
            var state = "error";
            var message = "停止失败，请查看日志";
            if (!string.IsNullOrWhiteSpace(json))
            {
                try
                {
                    using var doc = JsonDocument.Parse(json);
                    var root = doc.RootElement;
                    state = root.TryGetProperty("state", out var s) ? s.GetString() ?? "error" : "error";
                    message = root.TryGetProperty("message", out var m) ? m.GetString() ?? "" : message;
                }
                catch { }
            }

            var result = QueryStatus();
            result.State = state switch
            {
                "stopped" or "already_stopped" => WorkbenchState.Stopped,
                "refused" => WorkbenchState.Foreign,
                _ => result.State,
            };
            result.Message = message;
            if (result.State == WorkbenchState.Foreign)
            {
                result.Message = $"端口 {_config.BackendPort} 被其他程序占用，已拒绝停止，未结束任何进程。";
            }
            _log.Info($"Stop result: {state}");
            StopTunnel();
            progress.Report(result);
            return result;
        }
        finally
        {
            _busy.Release();
        }
    }

    // ---- Restart ----

    public async Task<StatusInfo> RestartAsync(IProgress<StatusInfo> progress, CancellationToken ct)
    {
        var stop = await StopAsync(progress, ct).ConfigureAwait(false);
        if (stop.State == WorkbenchState.Foreign)
        {
            return stop;
        }
        return await StartAsync(progress, ct).ConfigureAwait(false);
    }

    // ---- Tunnel ----

    /// <summary>Start the temporary public tunnel (cloudflared quick tunnel), returning its URL or null.</summary>
    public string? StartTunnel()
    {
        if (!_config.IsLocal) return null;
        if (!File.Exists(_config.TunnelScript))
        {
            _log.Warn("隧道脚本不存在：" + _config.TunnelScript);
            return null;
        }
        var json = RunScriptSync(_config.TunnelScript, $"-Action start -Port {_config.BackendPort}", out _);
        if (string.IsNullOrWhiteSpace(json)) return null;
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.TryGetProperty("ok", out var ok) && ok.GetBoolean() &&
                root.TryGetProperty("url", out var url))
                return url.GetString();
        }
        catch { }
        return null;
    }

    /// <summary>Stop the temporary public tunnel (idempotent).</summary>
    public void StopTunnel()
    {
        if (!_config.IsLocal) return;
        if (!File.Exists(_config.TunnelScript)) return;
        try { RunScriptSync(_config.TunnelScript, $"-Action stop -Port {_config.BackendPort}", out _); }
        catch (Exception ex) { _log.Warn("停止隧道失败：" + ex.Message); }
    }

    /// <summary>Best-effort stop of tunnel + backend for launcher exit; never throws.</summary>
    public void ShutdownAll()
    {
        try { StopTunnel(); } catch { }
        if (_config.IsLocal && File.Exists(_config.ControlScript))
        {
            try { RunScriptSync(_config.ControlScript, $"-Action stop -Port {_config.BackendPort}", out _); }
            catch { }
        }
    }

    // ---- helpers ----

    private string RunScriptSync(string scriptPath, string args, out int exitCode)
    {
        exitCode = -1;
        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-NoProfile -ExecutionPolicy Bypass -File \"{scriptPath}\" {args}",
            WorkingDirectory = _config.ProjectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        using var p = new Process { StartInfo = psi };
        try
        {
            var stdout = new StringBuilder();
            var stderr = new StringBuilder();
            p.OutputDataReceived += (_, e) => { if (e.Data != null) stdout.AppendLine(e.Data); };
            p.ErrorDataReceived += (_, e) => { if (e.Data != null) stderr.AppendLine(e.Data); };
            if (!p.Start()) return "";
            p.BeginOutputReadLine();
            p.BeginErrorReadLine();
            if (!p.WaitForExit(30000))
            {
                try { p.Kill(entireProcessTree: true); } catch { }
                _log.Error($"Script timed out: {scriptPath}");
                return "";
            }
            exitCode = p.ExitCode;
            if (stderr.Length > 0) _log.Warn(stderr.ToString());
            return stdout.ToString().Trim();
        }
        catch (Exception ex)
        {
            _log.Error($"Failed to run {scriptPath}: {ex.Message}");
            return "";
        }
    }
}
