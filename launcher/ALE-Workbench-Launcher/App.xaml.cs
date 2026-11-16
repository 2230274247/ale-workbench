using System;
using System.Threading;
using System.Windows;
using System.Windows.Forms;
using AleWorkbench.Launcher.Services;
using MessageBox = System.Windows.MessageBox;

namespace AleWorkbench.Launcher;

public partial class App : System.Windows.Application
{
    private const string MutexName = "ALE-Workbench-Launcher-SingleInstance";
    private Mutex? _mutex;
    private NotifyIcon? _tray;
    private MainWindow? _mainWindow;
    private AppConfig _config = null!;
    private LauncherLog _log = null!;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        _mutex = new Mutex(true, MutexName, out bool createdNew);
        if (!createdNew)
        {
            MessageBox.Show("ALE Workbench 启动器已经在运行。", "ALE Workbench",
                MessageBoxButton.OK, MessageBoxImage.Information);
            Shutdown();
            return;
        }

        _config = AppConfig.Load();
        _log = new LauncherLog(_config.LogDirectory);
        _log.Info("Launcher started.");

        _mainWindow = new MainWindow(_config, _log);
        _mainWindow.ExitApproved += OnExitApproved;
        _mainWindow.Closed += (_, _) => _mainWindow = null;

        BuildTray();

        if (_config.AutoStartOnLaunch && _config.IsLocalProjectValid)
        {
            _mainWindow.Show();
            _ = _mainWindow.TriggerAutoStartAsync();
        }
        else
        {
            _mainWindow.Show();
        }
    }

    private void BuildTray()
    {
        _tray = new NotifyIcon
        {
            Icon = LoadTrayIcon(),
            Text = "ALE Workbench Launcher",
            Visible = true,
        };
        var menu = new ContextMenuStrip();
        menu.Items.Add("打开启动器", null, (_, _) => ShowMainWindow());
        menu.Items.Add("打开工作站", null, (_, _) => _mainWindow?.OpenWorkbench());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("退出", null, (_, _) => RequestExit());
        _tray.ContextMenuStrip = menu;
        _tray.DoubleClick += (_, _) => ShowMainWindow();
    }

    private static System.Drawing.Icon LoadTrayIcon()
    {
        try
        {
            var exe = Environment.ProcessPath;
            if (!string.IsNullOrEmpty(exe))
            {
                var ic = System.Drawing.Icon.ExtractAssociatedIcon(exe);
                if (ic != null) return ic;
            }
        }
        catch { }
        return System.Drawing.SystemIcons.Application;
    }

    public void ShowMainWindow()
    {
        if (_mainWindow == null)
        {
            _mainWindow = new MainWindow(_config, _log);
            _mainWindow.ExitApproved += OnExitApproved;
            _mainWindow.Closed += (_, _) => _mainWindow = null;
        }
        _mainWindow.Show();
        if (_mainWindow.WindowState == WindowState.Minimized) _mainWindow.WindowState = WindowState.Normal;
        _mainWindow.Activate();
    }

    public void ShowTrayTip(string message)
    {
        try { _tray?.ShowBalloonTip(2500, "ALE Workbench", message, ToolTipIcon.Info); }
        catch { }
    }

    public void RequestExit()
    {
        if (_mainWindow != null)
        {
            _mainWindow.RequestExit();
        }
        else
        {
            OnExitApproved();
        }
    }

    private void OnExitApproved()
    {
        _log.Info("退出前停止工作站与隧道…");
        try
        {
            var controller = new WorkbenchController(_config, _log);
            controller.ShutdownAll();
        }
        catch (Exception ex)
        {
            _log.Error("停止服务失败：" + ex.Message);
        }
        _log.Info("Launcher exited.");
        _tray?.Dispose();
        Shutdown();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        try { _tray?.Dispose(); } catch { }
        try { _mutex?.Dispose(); } catch { }
        base.OnExit(e);
    }
}
