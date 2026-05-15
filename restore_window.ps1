Add-Type -MemberDefinition '
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
' -Name WinAPI -Namespace Win32 2>$null

Start-Sleep -Milliseconds 200
$h = [Win32.WinAPI]::GetConsoleWindow()
# SW_RESTORE (9) un-minimizes; SetForegroundWindow brings to front if just de-focused
[Win32.WinAPI]::ShowWindow($h, 9) | Out-Null
[Win32.WinAPI]::SetForegroundWindow($h) | Out-Null
