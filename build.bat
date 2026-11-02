@echo off
rem Builds dist\LB3DBoxCreator-<version>.exe: one file, no console window, no UPX.
rem Needs Python with Pillow and PyInstaller. The case templates of "box model" are built in and copied next to the exe.
cd /d "%~dp0"
python -c "import PIL" >nul 2>&1 || python -m pip install pillow
python -m PyInstaller --version >nul 2>&1 || python -m pip install pyinstaller
for /f "delims=" %%v in ('python -c "import lb_box3d_creator as m; print(m.APP_VERSION)"') do set VERSION=%%v
if "%VERSION%"=="" goto :error
set EXE=LB3DBoxCreator-%VERSION%
python -c "import lb_box3d_creator as m; m.app_icon(256).save('lb3d.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])" || goto :error
python -m PyInstaller --onefile --windowed --noupx --clean --noconfirm --name %EXE% --icon lb3d.ico ^
  --add-data "box model;box model" --exclude-module numpy lb_box3d_creator.py || goto :error
if not exist "dist\box model" mkdir "dist\box model"
xcopy /y /q "box model\*.*" "dist\box model\" >nul
start "" /wait dist\%EXE%.exe --selftest dist\selftest.txt
type dist\selftest.txt
echo.
echo Built: dist\%EXE%.exe
pause
exit /b 0
:error
echo Build failed.
pause
exit /b 1
