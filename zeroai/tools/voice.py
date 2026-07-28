"""语音交互工具

迁移来源：tui_agent.py 行 6288-6820

提供以下纯函数：
- _download_sense_voice_model：下载 SenseVoice 语音识别模型
- _init_pygame_mixer：初始化 pygame 音频播放器（延迟初始化）
- _split_text_into_segments：长文本按句末标点分割为多段（用于 TTS 分段朗读）
- speak_tts：文本转语音并播放（同步阻塞，分段朗读版，edge-tts）
- listen_asr：录音并识别为文字（同步阻塞，sherpa-onnx + SenseVoice）

依赖：
- 标准库：os, sys, re, asyncio, tempfile, threading, time, wave, urllib.request
- 可选第三方库：edge-tts（TTS）、pygame（音频播放）、sounddevice + numpy（录音）、
  sherpa-onnx（SenseVoice 识别）、faster-whisper（回退识别）
- zeroai.core.paths：_ZEROAI_USER_DIR, _find_resource_dir（模型路径解析）
"""
import os
import sys

from zeroai.core.paths import _ZEROAI_USER_DIR, _find_resource_dir


# ════════════════════════════════════════════════════════════════════
# 语音识别模型路径与全局状态
# 迁移来源：tui_agent.py 行 6288-6300
# ════════════════════════════════════════════════════════════════════

# ASR 模型单例（首次调用 listen_asr 时懒加载，全局复用，避免重复加载模型耗时）
_ASR_MODEL = None

# SenseVoice 模型路径（智能查找：开发模式脚本目录 / 环境变量 / 用户主目录 ~/.zeroai/）
_SENSE_VOICE_MODEL_DIR = os.path.join(_find_resource_dir("models"), "sense-voice")
_SENSE_VOICE_MODEL = os.path.join(_SENSE_VOICE_MODEL_DIR, "model.int8.onnx")
_SENSE_VOICE_TOKENS = os.path.join(_SENSE_VOICE_MODEL_DIR, "tokens.txt")

# SenseVoice 模型下载地址（HuggingFace 国内镜像 hf-mirror.com，避免被墙）
_SENSE_VOICE_DOWNLOAD_URLS = {
    "model.int8.onnx": "https://hf-mirror.com/pengzhendong/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx",
    "tokens.txt": "https://hf-mirror.com/pengzhendong/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt",
}


def _download_sense_voice_model() -> bool:
    """下载 SenseVoice 语音识别模型到用户目录 ~/.zeroai/models/sense-voice/

    模型来源：HuggingFace 国内镜像（hf-mirror.com）
    模型大小：约 220MB（model.int8.onnx）+ 几KB（tokens.txt）

    返回 True 表示下载成功，False 表示失败。

    迁移来源：tui_agent.py 行 6302-6354
    """
    # 下载到用户目录（pip 安装模式的标准位置）
    target_dir = os.path.join(_ZEROAI_USER_DIR, "models", "sense-voice")
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as e:
        print(f"无法创建模型目录: {e}", file=sys.stderr)
        return False

    import urllib.request

    for filename, url in _SENSE_VOICE_DOWNLOAD_URLS.items():
        target_path = os.path.join(target_dir, filename)
        if os.path.isfile(target_path) and os.path.getsize(target_path) > 1024:
            continue  # 已下载，跳过

        print(f"正在下载 {filename} ...", file=sys.stderr)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZeroAI/1.0"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 1024 * 64  # 64KB
                with open(target_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = downloaded * 100 // total
                            print(f"\r  进度: {pct}% ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)", end="", file=sys.stderr)
                print(file=sys.stderr)  # 换行
            print(f"  {filename} 下载完成", file=sys.stderr)
        except Exception as e:
            print(f"  下载失败: {e}", file=sys.stderr)
            return False

    # 更新全局路径指向用户目录
    global _SENSE_VOICE_MODEL_DIR, _SENSE_VOICE_MODEL, _SENSE_VOICE_TOKENS
    _SENSE_VOICE_MODEL_DIR = target_dir
    _SENSE_VOICE_MODEL = os.path.join(target_dir, "model.int8.onnx")
    _SENSE_VOICE_TOKENS = os.path.join(target_dir, "tokens.txt")
    print("SenseVoice 模型下载完成！", file=sys.stderr)
    return True


def _init_pygame_mixer():
    """初始化 pygame 音频播放器（延迟初始化）

    迁移来源：tui_agent.py 行 6357-6365
    """
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        return True
    except Exception:
        return False


def _split_text_into_segments(text: str, max_chars: int = 200) -> list:
    """把长文本按句末标点分割为多段（用于 TTS 分段朗读）

    策略：
    1. 先按强句末标点（。！？!?；;\\n）切分
    2. 短句累积成长段（避免单段过短触发太多 edge-tts 调用）
    3. 单段不超过 max_chars 字符
    4. 避免产生空段

    迁移来源：tui_agent.py 行 6368-6427
    """
    import re
    if not text or not text.strip():
        return []
    # 用正则切分：保留分隔符（让朗读更自然）
    parts = re.split(r"([。！？!?；;\n])", text)
    # 重组：[句子+标点, 句子+标点, ...]
    sentences = []
    i = 0
    while i < len(parts):
        s = parts[i].strip()
        if s:
            # 如果下一项是标点，拼回去
            if i + 1 < len(parts) and parts[i + 1] in "。！？!?；;\n":
                s = s + parts[i + 1]
                i += 2
            else:
                i += 1
            if s:
                sentences.append(s)
        else:
            i += 1
    # 累积短句成段（每段不超过 max_chars）
    segments = []
    buf = ""
    for s in sentences:
        if len(buf) + len(s) <= max_chars:
            buf += s
        else:
            if buf:
                segments.append(buf)
            # 如果单句本身就超过 max_chars，强制切分
            if len(s) > max_chars:
                # 按逗号再切
                sub_parts = re.split(r"([，,、：:])", s)
                sub_buf = ""
                for sp in sub_parts:
                    if len(sub_buf) + len(sp) <= max_chars:
                        sub_buf += sp
                    else:
                        if sub_buf:
                            segments.append(sub_buf)
                        sub_buf = sp
                if sub_buf:
                    buf = sub_buf
                else:
                    buf = ""
            else:
                buf = s
    if buf:
        segments.append(buf)
    return segments


def speak_tts(
    text: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
    volume: str = "+0%",
    interrupt_check=None,
    segment_max_chars: int = 200,
) -> str:
    """文本转语音并播放（同步阻塞，分段朗读版）

    使用 edge-tts（微软免费 TTS，无需 API Key）

    长文本会自动按句末标点（。！？!?；;）分割成多段，逐段生成+播放。
    优势：
      1. 启动延迟短（先听到第一段，后台继续生成后续段）
      2. 任意一段播放中检测到 interrupt_check() 返回 True，立即停止后续段
      3. 避免单次生成过长导致 edge-tts 超时

    Args:
        text: 要朗读的文本（支持中英文混合）
        voice: 音色（zh-CN-XiaoxiaoNeural 女/zh-CN-YunxiNeural 男/zh-CN-YunyangNeural 新闻）
        rate: 语速（+0% 正常/+10% 加速/-10% 减速）
        volume: 音量（+0% 正常/+10% 更大/-10% 更小）
        interrupt_check: 可调用对象，每段播放前后/中检查，返回 True 时立即停止
        segment_max_chars: 每段最大字符数（默认 200）

    Returns:
        成功返回空字符串，失败返回错误信息

    迁移来源：tui_agent.py 行 6430-6593
    """
    if not text or not text.strip():
        return "（空文本，无需朗读）"
    # 移除 Markdown 标记和代码块，避免朗读符号
    import re
    clean = re.sub(r"```[\s\S]*?```", "（代码块）", text)  # 代码块
    clean = re.sub(r"`([^`]+)`", r"\1", clean)  # 行内代码
    clean = re.sub(r"!\[[^\]]*\]\([^)]+\)", "（图片）", clean)  # 图片
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)  # 链接
    clean = re.sub(r"^#{1,6}\s+", "", clean, flags=re.MULTILINE)  # 标题
    clean = re.sub(r"^>\s+", "", clean, flags=re.MULTILINE)  # 引用
    clean = re.sub(r"^[-*+]\s+", "", clean, flags=re.MULTILINE)  # 列表
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)  # 粗体
    clean = re.sub(r"\*([^*]+)\*", r"\1", clean)  # 斜体
    clean = clean.strip()
    if not clean:
        return "（无可朗读内容）"

    # 分割为多段
    segments = _split_text_into_segments(clean, max_chars=segment_max_chars)
    if not segments:
        return "（无可朗读内容）"

    try:
        import asyncio
        import edge_tts
        import tempfile
        import os
        import time
        import threading

        def _is_interrupted() -> bool:
            """统一中断检查（异常吞掉，保证不影响主流程）"""
            if interrupt_check is None:
                return False
            try:
                return bool(interrupt_check())
            except Exception:
                return False

        def _gen_one_sync(seg_text: str) -> str:
            """同步生成单段 MP3，返回路径（出错返回错误字符串）"""
            try:
                async def _gen():
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    tmp_path = tmp.name
                    tmp.close()
                    communicate = edge_tts.Communicate(seg_text, voice, rate=rate, volume=volume)
                    await communicate.save(tmp_path)
                    return tmp_path

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        result = [None]

                        def _run():
                            try:
                                new_loop = asyncio.new_event_loop()
                                result[0] = new_loop.run_until_complete(_gen())
                                new_loop.close()
                            except Exception as e:
                                result[0] = f"错误：{e}"
                        t = threading.Thread(target=_run)
                        t.start()
                        t.join()
                        return result[0]
                    else:
                        return loop.run_until_complete(_gen())
                except RuntimeError:
                    return asyncio.run(_gen())
            except Exception as e:
                return f"错误：{e}"

        # 初始化 pygame.mixer（如果还没初始化）
        if not _init_pygame_mixer():
            return "错误：无法初始化音频播放器（pygame.mixer）"

        import pygame

        # 逐段生成 + 播放
        for idx, seg in enumerate(segments):
            # 段间打断检查
            if _is_interrupted():
                return "（已打断）"
            # 生成当前段
            tmp_path = _gen_one_sync(seg)
            if not tmp_path:
                continue
            if isinstance(tmp_path, str) and tmp_path.startswith("错误"):
                # 生成失败，跳过此段，继续下一段
                continue
            # 播放前再次检查中断（避免在生成 MP3 期间用户已退出）
            if _is_interrupted():
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                return "（已打断）"
            # 加载并播放
            try:
                pygame.mixer.music.load(tmp_path)
                pygame.mixer.music.play()
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                continue
            # 等待播放完成（最长 60 秒，并周期性检查打断）
            start = time.time()
            interrupted = False
            while pygame.mixer.music.get_busy() and time.time() - start < 60:
                time.sleep(0.1)
                if _is_interrupted():
                    try:
                        pygame.mixer.music.stop()
                    except Exception:
                        pass
                    interrupted = True
                    break
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            if interrupted:
                return "（已打断）"
        return ""
    except ImportError:
        return "错误：edge-tts 未安装，请运行 pip install edge-tts"
    except Exception as e:
        return f"错误：{e}"


def listen_asr(max_seconds: int = 10, silence_seconds: float = 1.0) -> str:
    """录音并识别为文字（同步阻塞）

    使用 sherpa-onnx + SenseVoice（阿里达摩院开源，本地离线，无需 API Key）
    准确率远超 whisper-tiny，支持中英日韩粤5种语言，自带标点符号

    改进版 VAD 方案：
    1. 录音前 0.3 秒采集环境噪声，动态计算静音阈值
    2. 前置静音过滤：等到检测到语音才开始录入（最多等 3 秒）
    3. 滑动窗口静音检测：最近 3 帧平均音量低于阈值才算静音
    4. 音量归一化：录音后归一化到 [-1, 1] 提升识别率
    5. 最小录音时长 0.3 秒，避免误触发

    Args:
        max_seconds: 最长录音秒数（默认 10 秒）
        silence_seconds: 静音检测秒数（连续静音超过此值则停止，默认 1.0 秒）

    Returns:
        识别到的文字，失败返回错误信息

    迁移来源：tui_agent.py 行 6596-6784
    """
    global _ASR_MODEL
    try:
        import sounddevice as sd
        import numpy as np
        import tempfile
        import wave
    except ImportError as e:
        return f"错误：缺少音频库（{e}），请运行 pip install sounddevice numpy"

    # ════════════════ 录音阶段（专业 VAD） ════════════════
    try:
        sample_rate = 16000
        channels = 1
        block_size = 1024  # 每帧 1024 采样 ≈ 64ms

        # ── 1. 采集 0.3 秒环境噪声，计算动态阈值 ──
        noise_frames = []
        noise_duration = 0.3  # 0.3 秒噪声采样（缩短响应时间）
        noise_blocks_needed = int(noise_duration * sample_rate / block_size)
        try:
            with sd.InputStream(samplerate=sample_rate, channels=channels, blocksize=block_size) as stream:
                for _ in range(noise_blocks_needed):
                    data, _ = stream.read(block_size)
                    noise_frames.append(data.copy())
            noise_audio = np.concatenate(noise_frames, axis=0)
            noise_level = float(np.abs(noise_audio).mean())
            # 动态阈值 = 噪声基线 × 3，至少 0.02（避免太敏感）
            silence_threshold = max(noise_level * 3.0, 0.02)
        except Exception:
            # 噪声采样失败，使用默认阈值
            silence_threshold = 0.03

        # ── 2. 正式录音：前置静音过滤 + 滑动窗口 VAD ──
        frames = []
        speech_started = False  # 是否检测到语音开始
        silence_count = 0  # 连续静音帧数
        max_silence_frames = int(silence_seconds * sample_rate / block_size)
        # 前置静音最长等待 3 秒（用户可能需要反应时间）
        max_pre_wait = int(3.0 * sample_rate / block_size)
        pre_wait_count = 0
        # 滑动窗口（最近 3 帧的音量）
        volume_window = []

        def callback(indata, frame_count, time_info, status):
            frames.append(indata.copy())

        with sd.InputStream(samplerate=sample_rate, channels=channels, callback=callback, blocksize=block_size):
            import time
            start = time.time()
            while time.time() - start < max_seconds:
                if frames:
                    last = frames[-1]
                    volume = float(np.abs(last).mean())
                    # 滑动窗口（保留最近 3 帧）
                    volume_window.append(volume)
                    if len(volume_window) > 3:
                        volume_window.pop(0)
                    avg_volume = sum(volume_window) / len(volume_window) if volume_window else 0

                    if not speech_started:
                        # 前置静音过滤：等到检测到语音才开始计时
                        if avg_volume > silence_threshold:
                            speech_started = True
                        else:
                            pre_wait_count += 1
                            if pre_wait_count > max_pre_wait:
                                # 等了 5 秒还没说话，返回空
                                return "（未录到声音）"
                    else:
                        # 语音已开始，检测静音
                        if avg_volume < silence_threshold:
                            silence_count += 1
                        else:
                            silence_count = 0
                        # 连续静音超过阈值 → 停止
                        if silence_count >= max_silence_frames:
                            break
                time.sleep(0.03)

        if not frames:
            return "（未录到声音）"
        if not speech_started:
            return "（未录到声音）"

        audio = np.concatenate(frames, axis=0)
        # 至少 0.3 秒有效音频
        if len(audio) < int(0.3 * sample_rate):
            return "（录音太短）"

        # ── 3. 音量归一化（提升小声说话的识别率）──
        max_amplitude = float(np.abs(audio).max())
        if max_amplitude > 0 and max_amplitude < 0.5:
            # 音量过小，归一化到 [-1, 1]
            audio = audio / max_amplitude

        # 保存为临时 wav 文件（faster-whisper 回退方案需要）
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            # 确保 audio 在 [-1, 1] 范围内
            audio_clipped = np.clip(audio, -1.0, 1.0)
            wf.writeframes((audio_clipped * 32767).astype(np.int16).tobytes())
    except Exception as e:
        return f"错误：录音失败（{e}）"

    # ════════════════ 识别阶段 ════════════════
    try:
        # 优先使用 sherpa-onnx + SenseVoice（本地离线，准确率最高，自带标点）
        sherpa_err = None
        try:
            import sherpa_onnx
            if _ASR_MODEL is None:
                if not os.path.isfile(_SENSE_VOICE_MODEL) or not os.path.isfile(_SENSE_VOICE_TOKENS):
                    # 尝试自动下载模型（首次使用语音功能时）
                    print("SenseVoice 模型未找到，正在自动下载（约 220MB）...", file=sys.stderr)
                    if not _download_sense_voice_model():
                        raise FileNotFoundError(
                            f"SenseVoice 模型下载失败。请手动下载并放到:\n  {_SENSE_VOICE_MODEL_DIR}\n"
                            f"或运行: pip install faster-whisper 作为替代方案"
                        )
                _ASR_MODEL = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=_SENSE_VOICE_MODEL,
                    tokens=_SENSE_VOICE_TOKENS,
                    num_threads=2,
                    use_itn=True,  # 启用逆文本归一化（自动添加标点符号）
                )
            # 创建识别流，喂入音频数据
            stream = _ASR_MODEL.create_stream()
            # sounddevice 录制的是 float32，范围 [-1, 1]，sherpa-onnx 需要同样的 float32
            audio_float32 = audio.flatten().astype(np.float32)
            stream.accept_waveform(sample_rate, audio_float32)
            _ASR_MODEL.decode_stream(stream)
            text = stream.result.text.strip()
            return text if text else "（未识别到内容）"
        except ImportError:
            sherpa_err = "sherpa-onnx 未安装（pip install sherpa-onnx）"
        except Exception as e:
            sherpa_err = str(e)

        # 回退 1：faster-whisper（本地离线，准确率一般）
        faster_whisper_err = None
        try:
            from faster_whisper import WhisperModel
            # 设置 HuggingFace 国内镜像（避免模型下载被墙）
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            _fw_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, _ = _fw_model.transcribe(tmp_path, language="zh", beam_size=1)
            text = "".join(seg.text for seg in segments).strip()
            if text:
                return text
        except ImportError:
            faster_whisper_err = "faster-whisper 未安装"
        except Exception as e:
            faster_whisper_err = str(e)

        # 所有方案均失败
        return f"错误：语音识别失败\n  sherpa-onnx: {sherpa_err}\n  faster-whisper: {faster_whisper_err}\n建议：\n  1. 确保 sherpa-onnx 已安装（pip install sherpa-onnx）\n  2. 确保模型文件存在于 {_SENSE_VOICE_MODEL_DIR}\n  3. 或安装 faster-whisper 作为回退（pip install faster-whisper）"
    finally:
        # 识别完成后才删除临时文件
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
