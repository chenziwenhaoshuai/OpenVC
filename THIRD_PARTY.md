# 第三方组件与许可证

OpenVC 本身是这层封装（界面、音频路由、打包），核心算法全部来自下列开源项目。

| 组件 | 用途 | 许可证 | 全文 |
|---|---|---|---|
| [MeanVC2](https://github.com/ASLP-lab/MeanVC2) | 变声模型权重与流式推理管线 | Apache-2.0 | `packaging/licenses/` |
| [MeanVC2-ONNX](https://huggingface.co/kiarina/MeanVC2-ONNX) | 模型 ONNX 导出（enc/dit/vocos/asr/gtm） | Apache-2.0 | `packaging/licenses/NOTICE` |
| [WavLM-Large + ECAPA-TDNN](https://huggingface.co/microsoft/UniSpeech) | 说话人编码器（按需下载） | CC BY-SA 3.0 | `packaging/licenses/CC-BY-SA-3.0-UniSpeech.txt` |
| [Vocos](https://github.com/charactr-platform/vocos) | 声码器架构 | MIT | `packaging/licenses/` |
| [WeNet](https://github.com/wenet-e2e/wenet) | Fast-U2++ ASR 架构 | Apache-2.0 | `packaging/licenses/` |
| [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) | 降噪（libDF 原生库 + 官方模型） | MIT / Apache-2.0 | `denoise/licenses/` |
| [VB-CABLE](https://vb-audio.com/Cable/) | 虚拟声卡驱动 | VB-Audio 免费软件，原版未修改 | `packaging/driver/` |

## 说明

- **MeanVC2 / MeanVC2-ONNX / Vocos / WeNet**：只随发布包分发转换后的 ONNX 图，
  不包含训练代码。
- **说话人编码器**是 Microsoft WavLM-Large + ECAPA-TDNN 的 ONNX 转换版本，
  属于 CC BY-SA 3.0 的衍生作品，因此保持该许可证。它只在用户主动添加新音色时
  下载，默认不随包分发。
- **DeepFilterNet**：使用官方 `libDF`（Rust 实现的 C 接口）而非 PyTorch 版，
  构建方式见 `build_denoise.ps1`。对官方源码只改了构建配置（去掉内嵌模型、
  开启 strip），未改动算法代码。
- **VB-CABLE**：随包为官方原始安装包（Driver Pack 45），未做任何修改。

本仓库自身代码的许可证由作者决定，尚未声明。