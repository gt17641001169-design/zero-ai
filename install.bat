@echo off
chcp 65001 >nul 2>&1
title ZeroAI 安装程序

echo ════════════════════════════════════════════════════════════
echo   ZeroAI 终端 AI 编程助手 - 安装程序 v1.0.0
echo   多专家协作 · 语音对话 · 文档生成 · 安全审计
echo ════════════════════════════════════════════════════════════
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo   下载地址: https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [1/4] 检测到 Python:
python --version
echo.

:: 配置清华镜像源加速下载
echo [2/4] 配置清华 PyPI 镜像源...
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
echo   已配置清华镜像源
echo.

:: 安装 ZeroAI 核心包
echo [3/4] 安装 ZeroAI 核心包...
echo   包含: textual, openai, python-docx, openpyxl, reportlab, matplotlib 等
echo.
pip install zeroai-1.0.0-py3-none-any.whl
if errorlevel 1 (
    echo.
    echo [错误] 核心包安装失败，请检查网络连接
    pause
    exit /b 1
)
echo.
echo   核心包安装完成!
echo.

:: 询问是否安装语音功能
echo [4/4] 语音功能（可选）
echo   语音功能包含: 语音对话、语音识别、语音合成
echo   需要额外下载约 500MB 依赖和模型
echo.
set /p install_voice="是否安装语音功能? (y/n): "
if /i "%install_voice%"=="y" (
    echo.
    echo   正在安装语音依赖...
    pip install sherpa-onnx faster-whisper av
    if errorlevel 1 (
        echo   [警告] 部分语音依赖安装失败，语音功能可能不可用
        echo   可稍后手动运行: pip install sherpa-onnx faster-whisper av
    ) else (
        echo   语音依赖安装完成!
    )
    echo.
    echo   首次使用语音功能时，将自动下载 SenseVoice 模型（约 220MB）
) else (
    echo   跳过语音功能安装
    echo   如需后续安装，运行: pip install zeroai[voice]
)
echo.

:: 验证安装
echo ════════════════════════════════════════════════════════════
echo   安装验证
echo ════════════════════════════════════════════════════════════
where zeroai >nul 2>&1
if errorlevel 1 (
    echo [警告] zeroai 命令未找到，请重新打开终端后重试
) else (
    echo [成功] zeroai 命令已安装
    echo   在任意终端输入: zeroai  即可启动
)
echo.
echo ════════════════════════════════════════════════════════════
echo   安装完成!
echo   启动命令: zeroai
echo   帮助文档: 启动后输入 /help
echo ════════════════════════════════════════════════════════════
pause
