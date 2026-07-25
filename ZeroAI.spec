# -*- mode: python ; coding: utf-8 -*-
"""
ZeroAI 打包配置文件
生成单文件 exe，包含所有依赖、SVG 图标资源、应用图标、语音模型
"""

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# 项目根目录
PROJECT_DIR = os.path.abspath('.')

# 收集 textual 和 rich 的所有数据文件和子模块（包含 CSS/模板等资源）
datas = []
binaries = []
hiddenimports = []

# SVG 图标资源（打包到 assets/icons 目录）
datas += [
    (os.path.join(PROJECT_DIR, 'assets', 'icons'), os.path.join('assets', 'icons')),
]

# 语音模型文件（SenseVoice 本地离线 ASR 模型，228MB）
_models_dir = os.path.join(PROJECT_DIR, 'models', 'sense-voice')
if os.path.isdir(_models_dir):
    datas += [
        (_models_dir, os.path.join('models', 'sense-voice')),
    ]

# libs 目录：sherpa_onnx / faster_whisper / av / speech_recognition 等
# 这些库通过 pip install --target 安装到 libs/，运行时通过 sys.path 加载
_libs_dir = os.path.join(PROJECT_DIR, 'libs')
if os.path.isdir(_libs_dir):
    datas += [
        (_libs_dir, 'libs'),
    ]

# textual: TUI 框架，需要完整的资源文件
tmp_d, tmp_b, tmp_h = collect_all('textual')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# rich: 终端渲染库
tmp_d, tmp_b, tmp_h = collect_all('rich')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# openai: SDK，动态导入部分模块
tmp_d, tmp_b, tmp_h = collect_all('openai')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# python-docx: Word 文档生成
tmp_d, tmp_b, tmp_h = collect_all('docx')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# openpyxl: Excel 生成
tmp_d, tmp_b, tmp_h = collect_all('openpyxl')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# reportlab: PDF 生成
tmp_d, tmp_b, tmp_h = collect_all('reportlab')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# uiautomation: Windows UI 自动化（伴随模式）
hiddenimports += ['uiautomation', 'uiautomation.uiautomation']

# pywintypes: pywin32 的动态导入模块
hiddenimports += ['win32com', 'win32com.client', 'pythoncom', 'pywintypes']

# psutil: 进程/系统信息
tmp_d, tmp_b, tmp_h = collect_all('psutil')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# PIL/Pillow: 图片处理（运行时缓存中使用）
tmp_d, tmp_b, tmp_h = collect_all('PIL')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# ====== 语音功能依赖 ======

# numpy: 语音录制音频数据处理
tmp_d, tmp_b, tmp_h = collect_all('numpy')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# sounddevice: 麦克风录音（依赖 PortAudio）
tmp_d, tmp_b, tmp_h = collect_all('sounddevice')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# pygame: 音频播放（TTS 朗读）
tmp_d, tmp_b, tmp_h = collect_all('pygame')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# edge_tts: 微软免费 TTS
tmp_d, tmp_b, tmp_h = collect_all('edge_tts')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# onnxruntime: SenseVoice 模型推理引擎
tmp_d, tmp_b, tmp_h = collect_all('onnxruntime')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# asyncssh: SSH 远程部署（纯 Python 异步 SSH 客户端）
# 依赖 cryptography（已被其他库间接引入），但需显式收集 asyncssh 子模块
tmp_d, tmp_b, tmp_h = collect_all('asyncssh')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# cryptography: asyncssh 依赖的加密库，显式收集确保完整
tmp_d, tmp_b, tmp_h = collect_all('cryptography')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# cffi: cryptography 的底层 C 绑定
tmp_d, tmp_b, tmp_h = collect_all('cffi')
datas += tmp_d
binaries += tmp_b
hiddenimports += tmp_h

# 显式声明其他可能被延迟导入的模块
hiddenimports += [
    'socket',
    'inspect',
    'platform',
    'shutil',
    'base64',
    'tempfile',
    'atexit',
    'traceback',
    'urllib.request',
    'urllib.parse',
    'urllib.error',
    'asyncio',
    # 语音功能延迟导入的模块
    'ctypes',
    'ctypes.wintypes',
    'wave',
    'struct',
    'threading',
]

a = Analysis(
    ['tui_agent.py'],
    pathex=[_libs_dir],  # 让 PyInstaller 能找到 libs/ 中的模块
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块，减小体积
        'matplotlib',
        'scipy',
        'pandas',
        'tkinter',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        # 以下大型 ML 库被 onnxruntime 间接依赖，但 ZeroAI 不需要
        'torch',
        'torchvision',
        'torchaudio',
        'transformers',
        'tensorflow',
        'tensorboard',
        'triton',
        # IPython 不需要
        'IPython',
        # jupyter 不需要
        'jupyter',
        'notebook',
        'ipykernel',
        'ipywidgets',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ZeroAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_DIR, 'assets', 'icons', 'app_icon.ico'),
)
