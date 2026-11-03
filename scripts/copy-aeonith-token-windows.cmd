@echo off
setlocal DisableDelayedExpansion
rem Double-click from Explorer as the SAME Windows account that launched Aeonith.
rem Only calls the checked-in DPAPI clipboard helper. Does not start a service.
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0copy-aeonith-token-windows.ps1"
if errorlevel 1 (
    echo.
    echo Aeonith could not recover this account's token. The clipboard may still contain an older value.
    echo Confirm you are signed into the original Windows account.
    pause
    exit /b 1
)
echo.
echo In Aeonith, paste with Ctrl+V into the Service access token field.
echo If that field is hidden, your browser is already signed in: use Sign out first only if needed.
echo Never paste your token into a chat, screenshot, or issue tracker.
pause
exit /b 0
