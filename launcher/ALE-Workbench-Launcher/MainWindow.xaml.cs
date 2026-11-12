using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using AleWorkbench.Launcher.Models;
using AleWorkbench.Launcher.Services;
using Microsoft.Web.WebView2.Core;
using Application = System.Windows.Application;
using Brush = System.Windows.Media.Brush;
using MessageBox = System.Windows.MessageBox;

namespace AleWorkbench.Launcher;

public partial class MainWindow : Window
{
    private readonly AppConfig _config;
    private readonly LauncherLog _log;
    private readonly WorkbenchController _controller;
    private readonly CancellationTokenSource _pollCts = new();

    private WorkbenchState _currentState = WorkbenchState.Unknown;
    private bool _operationInProgress;
    private bool _allowExit;
    private bool _initialized;
    private bool _trayTipShown;
    private bool _webViewReady;
    private string? _pendingUrl;

    public event Action? ExitApproved;

    public MainWindow(AppConfig config, LauncherLog log)
    {
        InitializeComponent();
        _config = config;
        _log = log;
        _controller = new WorkbenchController(config, log);

        VersionText.Text = "桌面 v" + (typeof(MainWindow).Assembly.GetName().Version?.ToString(3) ?? "1.0.0");
        UrlValue.Text = string.IsNullOrWhiteSpace(_controller.LoginUrl) ? "（未配置）" : _controller.LoginUrl;
        FooterText.Text = $"配置：{AppConfig.ConfigPath}    日志：{_log.Path}";

        PopulateSettings();
        ApplyStatus(new StatusInfo { State = WorkbenchState.Stopped, Message = "正在检测…", AccessUrl = _controller.AccessUrl });

        Loaded += async (_, _) =>
        {
            if (!_config.IsLocalProjectValid)
            {
                ConfigHint.Visibility = Visibility.Visible;
                SettingsPanel.Visibility = Visibility.Visible;
            }
            await InitializeWebViewAsync();
            await RefreshNowAsync();
            _ = PollLoopAsync(_pollCts.Token);
        };
        Closed += (_, _) => _pollCts.Cancel();
    }

    // ---- WebView2 ----

    private async Task InitializeWebViewAsync()
    {
        try
        {
            var env = await CoreWebView2Environment.CreateAsync();
            await WebView.EnsureCoreWebView2Async(env);
            _webViewReady = true;
            if (_pendingUrl != null)
            {
                var u = _pendingUrl;
                _pendingUrl = null;
                WebView.CoreWebView2.Navigate(u);
            }
            else
            {
                RefreshWebViewNavigation();
            }
        }
        catch (Exception ex)
        {
            _log.Error("WebView2 初始化失败：" + ex.Message);
        }
    }

    private void RefreshWebViewNavigation()
    {
        if (_controller.IsLocal && _currentState == WorkbenchState.Running)
        {
            NavigateUrl(_controller.LoginUrl);
        }
        else if (!_controller.IsLocal)
        {
            NavigateUrl(_config.RemoteUrl);
        }
        else
        {
            NavigateHint("工作站未启动。请点击上方「启动工作站」，或点「设置」切换到云端模式。");
        }
    }

    private void NavigateUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        if (!_webViewReady) { _pendingUrl = url; return; }
        try { WebView.CoreWebView2.Navigate(url); }
        catch (Exception ex) { _log.Error("导航失败：" + ex.Message); }
    }

    private void NavigateHint(string message)
    {
        var html = $"<!DOCTYPE html><html><head><meta charset='utf-8'><style>" +
                   "body{font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8fafc;color:#334155}" +
                   ".box{text-align:center;max-width:420px;padding:32px}" +
                   ".t{font-size:20px;font-weight:600;margin-bottom:8px;color:#0f172a}" +
                   "</style></head><body><div class='box'><div class='t'>ALE Workbench</div>" +
                   "<div>" + System.Net.WebUtility.HtmlEncode(message) + "</div></div></body></html>";
        if (!_webViewReady) { _pendingUrl = null; return; }
        try { WebView.CoreWebView2.NavigateToString(html); }
        catch (Exception ex) { _log.Error("提示页加载失败：" + ex.Message); }
    }

    // ---- Polling ----

    private async Task RefreshNowAsync()
    {
        var info = await Task.Run(() => _controller.QueryStatus());
        if (!_operationInProgress) ApplyStatus(info);
        RefreshWebViewNavigation();
    }

    private async Task PollLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try { await Task.Delay(2500, ct); }
            catch (OperationCanceledException) { return; }

            if (_operationInProgress) continue;

            StatusInfo info;
            try { info = await Task.Run(() => _controller.QueryStatus(), ct); }
            catch (OperationCanceledException) { return; }
            catch { continue; }

            if (_operationInProgress) continue;
            ApplyStatus(info);
        }
    }

    // ---- UI updates ----

    private void ApplyStatus(StatusInfo info)
    {
        _currentState = info.State;
        (string label, Brush color, string backend, string db, string frontend) = MapState(info);
        StateDot.Fill = color;
        StateLabel.Text = label;
        StateDetail.Text = BuildDetail(info);
        BackendDot.Fill = color;
        BackendValue.Text = backend;
        DbDot.Fill = info.Database == "ok" ? B("SuccessBrush") : (info.State == WorkbenchState.Degraded ? B("ErrorBrush") : B("GrayBrush"));
        DbValue.Text = db;
        FrontendDot.Fill = info.FrontendReady ? B("SuccessBrush") : B("GrayBrush");
        FrontendValue.Text = frontend;
        if (!string.IsNullOrWhiteSpace(info.AccessUrl)) UrlValue.Text = _controller.IsLocal ? _controller.LoginUrl : _config.RemoteUrl;
        UpdateProgress(info);
        UpdateButtons();
    }

    private void UpdateProgress(StatusInfo info)
    {
        try
        {
            if (info.State == WorkbenchState.Starting && _operationInProgress)
            {
                double value = info.ProgressValue < 0 ? 2 : Math.Clamp(info.ProgressValue, 0, 100);
                StartProgress.Value = value;
                StartProgressPercent.Text = $"{(int)Math.Round(value)}%";
                StartProgressText.Text = string.IsNullOrWhiteSpace(info.ProgressMessage) ? "正在启动…" : info.ProgressMessage;
                ProgressPanel.Visibility = Visibility.Visible;
            }
            else
            {
                ProgressPanel.Visibility = Visibility.Collapsed;
            }
        }
        catch (Exception ex)
        {
            _log.Warn("进度显示更新失败：" + ex.Message);
        }
    }

    private string BuildDetail(StatusInfo info)
    {
        var pid = info.Pid.HasValue ? $"（PID {info.Pid}）" : "";
        var msg = string.IsNullOrWhiteSpace(info.Message) ? "" : info.Message;
        return string.IsNullOrWhiteSpace(msg) ? pid : $"{msg}{pid}";
    }

    private (string label, Brush color, string backend, string db, string frontend) MapState(StatusInfo info)
    {
        switch (info.State)
        {
            case WorkbenchState.Running:
                return ("正常运行", B("SuccessBrush"), "运行中", "已连接",
                    info.FrontendReady ? "运行中（后端托管）" : "未构建（缺 dist）");
            case WorkbenchState.Starting:
                return ("正在启动", B("WarnBrush"), "正在启动", "检查中", "未就绪");
            case WorkbenchState.Degraded:
                return ("数据库连接失败", B("ErrorBrush"), "运行中（异常）", "连接失败",
                    info.FrontendReady ? "运行中（后端托管）" : "未就绪");
            case WorkbenchState.Foreign:
                return ("端口被占用", B("ErrorBrush"), "端口被占用", "未知", "未就绪");
            case WorkbenchState.Stopping:
                return ("正在停止", B("WarnBrush"), "正在停止", "—", "未就绪");
            case WorkbenchState.Failed:
                return ("启动失败", B("ErrorBrush"), "启动失败", "未连接", "未就绪");
            case WorkbenchState.Stopped:
            default:
                return (_controller.IsLocal ? "未启动" : "未连接", B("GrayBrush"),
                    _controller.IsLocal ? "未启动" : "远程", "未检查", "未就绪");
        }
    }

    private void UpdateButtons()
    {
        bool remote = !_controller.IsLocal;
        if (_operationInProgress)
        {
            StartButton.IsEnabled = StopButton.IsEnabled = RestartButton.IsEnabled = OpenButton.IsEnabled = false;
            return;
        }
        bool running = _currentState is WorkbenchState.Running;
        bool canStop = _currentState is WorkbenchState.Running or WorkbenchState.Degraded;
        bool canStart = _currentState is WorkbenchState.Stopped or WorkbenchState.Failed or WorkbenchState.Unknown;
        StartButton.IsEnabled = !remote && canStart;
        OpenButton.IsEnabled = running || remote;
        StopButton.IsEnabled = !remote && canStop;
        RestartButton.IsEnabled = !remote && canStop;
        BrowserButton.IsEnabled = !string.IsNullOrWhiteSpace(_controller.LoginUrl);
    }

    private Brush B(string key) => (Brush)FindResource(key);

    // ---- Actions ----

    private async void Start_Click(object sender, RoutedEventArgs e)
    {
        if (_operationInProgress) return;
        await StartWithPreCheckAsync();
    }

    private async Task StartWithPreCheckAsync()
    {
        var quick = await Task.Run(() => _controller.QueryStatus());
        if (!_operationInProgress && quick.State == WorkbenchState.Running)
        {
            ApplyStatus(quick);
            RefreshWebViewNavigation();
            return;
        }
        await RunOperationAsync(() => _controller.StartAsync(new Progress<StatusInfo>(ApplyStatus), CancellationToken.None));
    }

    public async Task TriggerAutoStartAsync()
    {
        await StartWithPreCheckAsync();
    }

    private async void Stop_Click(object sender, RoutedEventArgs e)
    {
        if (_operationInProgress) return;
        await RunOperationAsync(() => _controller.StopAsync(new Progress<StatusInfo>(ApplyStatus), CancellationToken.None));
    }

    private async void Restart_Click(object sender, RoutedEventArgs e)
    {
        if (_operationInProgress) return;
        await RunOperationAsync(() => _controller.RestartAsync(new Progress<StatusInfo>(ApplyStatus), CancellationToken.None));
    }

    private async Task RunOperationAsync(Func<Task<StatusInfo>> op)
    {
        _operationInProgress = true;
        UpdateButtons();
        try
        {
            var result = await op();
            ApplyStatus(result);
            RefreshWebViewNavigation();
            RefreshFooterWithBackendVersion();
            if (!string.IsNullOrWhiteSpace(result.TunnelUrl))
            {
                try { Process.Start(new ProcessStartInfo(result.TunnelUrl) { UseShellExecute = true }); }
                catch (Exception ex) { _log.Error("打开隧道网址失败：" + ex.Message); }
            }
        }
        catch (Exception ex)
        {
            _log.Error("操作失败：" + ex.Message);
            ApplyStatus(new StatusInfo { State = WorkbenchState.Failed, Message = "操作失败：" + ex.Message, AccessUrl = _controller.AccessUrl });
            RefreshWebViewNavigation();
        }
        finally
        {
            _operationInProgress = false;
            UpdateButtons();
        }
    }

    public void OpenWorkbench()
    {
        RefreshWebViewNavigation();
    }

    private void Open_Click(object sender, RoutedEventArgs e) => OpenWorkbench();

    private void Browser_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_controller.LoginUrl)) return;
        try
        {
            Process.Start(new ProcessStartInfo(_controller.LoginUrl) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            _log.Error("打开浏览器失败：" + ex.Message);
            MessageBox.Show("无法打开浏览器：" + ex.Message, "ALE Workbench", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void Log_Click(object sender, RoutedEventArgs e)
    {
        var files = new System.Collections.Generic.List<string> { _log.Path };
        var backendErr = Path.Combine(_config.ProjectRoot, "backend", ".runtime", $"server-{_config.BackendPort}.stderr.log");
        if (File.Exists(backendErr)) files.Add(backendErr);
        foreach (var f in files)
        {
            try { Process.Start(new ProcessStartInfo(f) { UseShellExecute = true }); } catch { }
        }
    }

    private async void RefreshFooterWithBackendVersion()
    {
        if (_controller.IsLocal && _currentState == WorkbenchState.Running)
        {
            var backend = await Task.Run(() => _controller.QueryBackendVersion());
            FooterText.Text = $"后端 API v{backend ?? "未知"} · " + $"桌面 v{typeof(MainWindow).Assembly.GetName().Version?.ToString(3) ?? "1.0.0"} · 日志：{_log.Path}";
        }
        else
        {
            FooterText.Text = $"配置：{AppConfig.ConfigPath}    日志：{_log.Path}";
        }
    }

    private void Version_Click(object sender, RoutedEventArgs e)
    {
        var desktop = typeof(MainWindow).Assembly.GetName().Version?.ToString(3) ?? "1.0.0";
        var backend = _controller.IsLocal ? (_controller.QueryBackendVersion() ?? "未连接") : "云端";
        var compat = _controller.IsLocal && backend == WorkbenchController.CompatibleApiVersion ? "兼容" : "—";
        var mode = _config.IsLocal ? "本地模式" : "远程模式";
        MessageBox.Show(
            $"桌面客户端版本：{desktop}\n" +
            $"后端 / API 版本：{backend}\n" +
            $"API 兼容性：{(backend == WorkbenchController.CompatibleApiVersion ? $"兼容（{WorkbenchController.CompatibleApiVersion}）" : (backend == "未连接" ? "未连接" : $"不匹配（期望 {WorkbenchController.CompatibleApiVersion}）"))}\n\n" +
            $"运行模式：{mode}\n" +
            $"访问地址：{(_config.IsLocal ? _config.LoginUrl : _config.RemoteUrl)}\n" +
            $"项目目录：{(_config.IsLocal ? _config.ProjectRoot : "（远程模式无本地项目）")}\n" +
            $"配置文件：{AppConfig.ConfigPath}\n" +
            $"日志目录：{_config.LogDirectory}",
            "关于 / 版本", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    // ---- Settings ----

    private void Settings_Click(object sender, RoutedEventArgs e)
    {
        PopulateSettings();
        SettingsPanel.Visibility = SettingsPanel.Visibility == Visibility.Visible ? Visibility.Collapsed : Visibility.Visible;
    }

    private void PopulateSettings()
    {
        _initialized = false;
        ProjectRootBox.Text = _config.ProjectRoot;
        RemoteUrlBox.Text = _config.RemoteUrl;
        AutoStartBox.IsChecked = _config.AutoStartOnLaunch;
        TrayBox.IsChecked = _config.MinimizeToTrayOnClose;
        SelectMode(_config.Mode);
        _initialized = true;
        ApplyModeVisibility();
    }

    private void SelectMode(string mode)
    {
        foreach (var item in ModeBox.Items)
        {
            if (item is ComboBoxItem cbi && (string)cbi.Tag == mode) { ModeBox.SelectedItem = item; return; }
        }
        ModeBox.SelectedIndex = 0;
    }

    private void ModeBox_SelectionChanged(object sender, System.Windows.Controls.SelectionChangedEventArgs e)
    {
        if (!_initialized) return;
        ApplyModeVisibility();
    }

    private void ApplyModeVisibility()
    {
        bool isLocal = SelectedMode() == "local";
        ProjectRootBox.IsEnabled = isLocal;
        RemoteUrlBox.IsEnabled = !isLocal;
    }

    private string SelectedMode() => (ModeBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "local";

    private void BrowseProject_Click(object sender, RoutedEventArgs e)
    {
        using var dlg = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "选择 ALE Workbench 项目目录（包含 start-workbench.ps1）",
            SelectedPath = Directory.Exists(ProjectRootBox.Text) ? ProjectRootBox.Text : "",
            ShowNewFolderButton = true,
        };
        if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
        {
            ProjectRootBox.Text = dlg.SelectedPath;
        }
    }

    private void SaveSettings_Click(object sender, RoutedEventArgs e)
    {
        var mode = SelectedMode();
        var root = ProjectRootBox.Text.Trim();

        if (mode == "local")
        {
            if (string.IsNullOrWhiteSpace(root) || !File.Exists(Path.Combine(root, "start-workbench.ps1")))
            {
                MessageBox.Show("项目目录无效：未找到 start-workbench.ps1。请选择正确的项目目录。",
                    "设置", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
        }
        else if (string.IsNullOrWhiteSpace(RemoteUrlBox.Text.Trim()))
        {
            MessageBox.Show("云端模式需要填写云端地址（HTTPS）。", "设置", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _config.Mode = mode;
        _config.ProjectRoot = mode == "local" ? root.TrimEnd('\\', '/') : "";
        _config.RemoteUrl = RemoteUrlBox.Text.Trim();
        _config.AutoStartOnLaunch = AutoStartBox.IsChecked == true;
        _config.MinimizeToTrayOnClose = TrayBox.IsChecked == true;
        _config.Save();

        UrlValue.Text = _controller.IsLocal ? _controller.LoginUrl : _config.RemoteUrl;
        SettingsPanel.Visibility = Visibility.Collapsed;
        ConfigHint.Visibility = Visibility.Collapsed;
        _log.Info($"配置已保存：mode={mode}");
        UpdateButtons();
        _ = RefreshNowAsync();
    }

    private void CancelSettings_Click(object sender, RoutedEventArgs e)
    {
        PopulateSettings();
        SettingsPanel.Visibility = Visibility.Collapsed;
    }

    // ---- Close / exit ----

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        if (_allowExit) return;

        if (_config.MinimizeToTrayOnClose)
        {
            e.Cancel = true;
            Hide();
            if (!_trayTipShown)
            {
                _trayTipShown = true;
                (Application.Current as App)?.ShowTrayTip("启动器已最小化到系统托盘，双击图标可重新打开。");
            }
            return;
        }

        e.Cancel = true;
        ConfirmExit();
    }

    public void RequestExit() => ConfirmExit();

    private void ConfirmExit()
    {
        bool backendRunning = _controller.IsLocal &&
            (_currentState is WorkbenchState.Running or WorkbenchState.Degraded or WorkbenchState.Starting or WorkbenchState.Stopping);
        if (backendRunning)
        {
            var r = MessageBox.Show(
                "退出启动器将停止工作站与公网隧道（MySQL 数据服务保持运行）。\n\n确定要退出吗？",
                "退出启动器", MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (r != MessageBoxResult.Yes) return;
        }
        _allowExit = true;
        ExitApproved?.Invoke();
    }
}
