@echo off
echo ============================================
echo   WebCam Controller Pro - Build Script
echo ============================================
echo.

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Building executable...
pyinstaller --onefile --windowed --name WebCamControllerPro webcam_controller.py

echo.
echo ============================================
if exist "dist\WebCamControllerPro.exe" (
    echo   BUILD SUCCESS!
    echo   Output: dist\WebCamControllerPro.exe
) else (
    echo   BUILD FAILED!
)
echo ============================================
pause
