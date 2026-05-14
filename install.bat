@echo off
REM AI 퀀트 추천 시스템 초기 설치 스크립트
setlocal enabledelayedexpansion

cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
chcp 65001 >nul

echo ============================================================
echo  AI 퀀트 추천 시스템 - 설치
echo ============================================================
echo.

REM Python 런처 확인
where py >nul 2>nul
if errorlevel 1 (
    echo [에러] Python 런처(py.exe)를 찾을 수 없습니다.
    echo Python 3.9+ 를 https://www.python.org 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)

REM venv 생성
if exist ".venv\Scripts\python.exe" (
    echo [SKIP] .venv 이미 존재함
) else (
    echo [1/3] Python 가상환경 생성...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [에러] venv 생성 실패
        pause
        exit /b 1
    )
)

REM pip 업그레이드
echo [2/3] pip 업그레이드...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo [경고] pip 업그레이드 실패 (계속 진행)
)

REM 의존성 설치
echo [3/3] 의존성 패키지 설치 중... (수 분 소요)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [에러] 의존성 설치 실패
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  설치 완료
echo ============================================================
echo  다음 단계:
echo   1) ingest.bat - 데이터 적재 (~10분)
echo   2) train.bat  - 모델 학습 (~5-10분)
echo   3) run.bat    - 서버 실행
echo.
echo  중요: SEC EDGAR 사용 정책상 User-Agent에 본인 이메일 권장.
echo  run.bat 파일에서 SEC_USER_AGENT 줄을 수정하세요.
echo ============================================================
pause

endlocal
