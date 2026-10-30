# 数据来源

OpenVC 自己不含任何模型。下面每一个文件都是从别人那里下载或编译来的，
这里把**确切地址、大小、许可证**全部列清楚，方便核对与自行获取。

## 一、变声模型（70.4 MB）

| 文件 | 大小 | 用途 |
|---|---|---|
| `fbank.onnx` | 0.9 MB | 400 采样点 → Kaldi log-mel 80 维 |
| `asr.int8.onnx` | 27.3 MB | Fast-U2++ 声学编码器（int8） |
| `gtm.onnx` | 16.6 MB | 说话人嵌入 → 音色记忆 |
| `dit.int8.onnx` | 13.2 MB | DiT 单步去噪（int8） |
| `vocos.int8.onnx` | 12.4 MB | Vocos 声码器（int8） |

**来源**：<https://huggingface.co/kiarina/MeanVC2-ONNX>
**镜像**：<https://hf-mirror.com/kiarina/MeanVC2-ONNX>
**获取**：`powershell -ExecutionPolicy Bypass -File .\download_models.ps1`
**许可证**：Apache-2.0（由 [ASLP-lab/MeanVC2](https://github.com/ASLP-lab/MeanVC2) 转换而来）

原始 PyTorch 权重在 <https://huggingface.co/ASLP-lab/MeanVC2>，本仓库不使用。

## 二、说话人编码器（369.2 MB，按需下载）

| 文件 | 大小 | 用途 |
|---|---|---|
| `speaker.int8.onnx` | 369.2 MB | 参考音频 → 256 维音色指纹 |

**来源**：<https://huggingface.co/kiarina/MeanVC2-ONNX/resolve/main/speaker/speaker.int8.onnx>
**镜像**：<https://hf-mirror.com/kiarina/MeanVC2-ONNX/resolve/main/speaker/speaker.int8.onnx>
**获取**：程序内自动下载（添加第一个自定义音色时提示），带断点续传与镜像回退
**许可证**：CC BY-SA 3.0（Microsoft WavLM-Large + ECAPA-TDNN，来自 [microsoft/UniSpeech](https://huggingface.co/microsoft/UniSpeech)）

> 不随发布包分发，因为只有「上传自己的参考音频」时才需要它。

## 三、降噪（35.4 MB）

| 文件 | 大小 | 用途 |
|---|---|---|
| `df.dll` | 27.8 MB | libDF 编译产物（tract 推理 + DSP） |
| `DeepFilterNet3_onnx.tar.gz` | 7.6 MB | 官方预训练模型（enc/erb_dec/df_dec） |

**源码**：<https://github.com/Rikorose/DeepFilterNet>（tarball：`https://codeload.github.com/Rikorose/DeepFilterNet/tar.gz/refs/heads/main`，约 92 MB）
**模型**：官方仓库内 `models/DeepFilterNet3_onnx.tar.gz`
**获取**：`powershell -ExecutionPolicy Bypass -File .\build_denoise.ps1`
**许可证**：MIT / Apache-2.0

编译命令（官方文档写法）：

```
cargo build --release --features capi
```

我们只改了两处**构建配置**，没有改算法代码：
- 去掉 `default-model` 特性（模型改为运行时从 tar.gz 加载，可换模型且省 7.6 MB）
- 开启 `strip`（38.7 MB → 27.8 MB）

## 四、虚拟声卡驱动（1.26 MB）

| 文件 | 用途 |
|---|---|
| `VBCABLE_Driver_Pack45.zip` | VB-CABLE 官方安装包，未做任何修改 |

**来源**：<https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip>
**主页**：<https://vb-audio.com/Cable/>
**获取**：已随仓库提供（`packaging/driver/`），无需下载
**许可证**：VB-Audio 免费软件（赞助制）

## 五、构建依赖

| 依赖 | 大小 | 来源 | 获取 |
|---|---|---|---|
| Python 3.11.9 embeddable | 10.7 MB | <https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip><br>镜像：<https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip> | `build_portable.ps1` 自动下载 |
| numpy / onnxruntime / PySide6-Essentials / sounddevice / soundfile / soxr | 约 315 MB | PyPI | `setup.ps1`（默认清华镜像） |
| Rust crates（tract 等） | — | crates.io | `cargo` |
| mingw-w64 | — | 任意发行版 | 手动安装 |

## 国内网络提示

所有下载脚本都带镜像回退，不用改代码：

| 服务 | 主地址 | 镜像 |
|---|---|---|
| 模型 | huggingface.co | hf-mirror.com |
| Python | python.org | mirrors.huaweicloud.com |
| PyPI | pypi.org | pypi.tuna.tsinghua.edu.cn |

需要代理时，各脚本都支持 `-Proxy http://127.0.0.1:7897`：

```powershell
.\download_models.ps1 -Proxy http://127.0.0.1:7897
.\build_denoise.ps1   -Proxy http://127.0.0.1:7897
.\setup.ps1           -Proxy http://127.0.0.1:7897
```

## 完整的第三方清单与许可证全文

见 [THIRD_PARTY.md](THIRD_PARTY.md)。