@echo off
:: Batch file to rename Virtual Camera to 'reycam' across all Windows apps (Discord, Zoom, Meet, Teams)
:: Requires Administrator privileges

echo =======================================================
echo   Reycamview - Register Virtual Camera Name 'reycam'
echo =======================================================
echo.

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges to register 'reycam'...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Registering 'reycam' in 64-bit Windows Registry...
reg add "HKLM\SOFTWARE\Classes\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}" /v FriendlyName /t REG_SZ /d "reycam" /f

echo Registering 'reycam' in 32-bit Windows Registry (WOW64)...
reg add "HKLM\SOFTWARE\Classes\WOW6432Node\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}" /v FriendlyName /t REG_SZ /d "reycam" /f

echo Registering 'reycam' in User Profile (HKCU)...
reg add "HKCU\Software\Classes\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}" /v FriendlyName /t REG_SZ /d "reycam" /f

echo.
echo =======================================================
echo   SUCCESS! Virtual camera is now officially 'reycam'!
echo   Please restart Discord / Zoom / Chrome to see 'reycam'.
echo =======================================================
timeout /t 3
