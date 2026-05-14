@echo off
REM AI 퀀트 추천 시스템 실행 스크립트
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [에러] .venv 가상환경이 없습니다.
    echo install.bat 을 먼저 실행하세요.
    pause
    exit /b 1
)

REM 한글 출력을 위한 UTF-8 강제
set PYTHONIOENCODING=utf-8
chcp 65001 >nul

REM SEC EDGAR User-Agent (fair-use 정책상 필수). 본인 이메일로 변경 권장.
set SEC_USER_AGENT=FinanceResearch your-email@example.com

echo ============================================================
echo  AI 퀀트 추천 시스템
echo ============================================================
echo  서버 주소: http://127.0.0.1:8000
echo  종료: Ctrl+C
echo ============================================================
echo.

REM 브라우저 자동 오픈 (3초 후)
start "" /B cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8000"

".venv\Scripts\python.exe" run.py

endlocal
