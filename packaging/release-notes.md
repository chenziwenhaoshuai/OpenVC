## OpenVC __VERSION__

实时零样本变声器：把麦克风声音换成任意人的音色，喂给腾讯会议 / Zoom / Teams / Discord。
全部本地运行，不需要 GPU、不需要 PyTorch、不需要装 Python。

**解压后先装 ``驱动\`` 里的虚拟声卡（右键 → 以管理员身份运行 → Install Driver → 重启），然后双击 ``OpenVC.exe``。**

### 包里有什么

| 目录 | 内容 |
|---|---|
| ``OpenVC.exe`` | 主程序，原生窗口 |
| ``runtime\`` | 内嵌 Python + Qt + ONNX Runtime |
| ``onnx\`` | 变声模型 70 MB |
| ``denoise\`` | DeepFilterNet3 降噪 |
| ``驱动\`` | VB-CABLE 虚拟声卡官方安装包 |
| ``voices\`` | 6 个内置音色 |

### 特性

- **不需要 GPU**：CPU 实时率 RTF 0.13（开着降噪 0.35）
- **不需要 PyTorch**：推理走 ONNX Runtime，整包 338 MB
- **不需要装 Python**：内嵌解释器，双击即用
- 内置 6 个音色，点 ▶ 可试听真实转换效果
- 支持上传自己的参考音频（首次会下载 369 MB 说话人编码器）
- 一键自检：播测试音进虚拟声卡再从 CABLE Output 录回来验证回环
- 可选 DeepFilterNet3 降噪，压掉键盘声 / 风扇声

### 已知限制

- 仅 Windows 10/11 x64
- 端到端延迟约 340–420 ms
- 只提供 120 ms 分块模型

### 校验

``````
SHA256: __SHA256__
``````

### 数据来源

包内模型全部来自第三方开源项目，确切地址与许可证见包内 ``SOURCES.md``。

### 许可证

转换图 Apache-2.0；说话人编码器 CC BY-SA 3.0；DeepFilterNet MIT/Apache-2.0；
VB-CABLE 为 VB-Audio 免费软件（原版未修改）。详见 ``THIRD_PARTY.md``。

请只在获得授权的场景使用。用他人声音冒充他人可能违法。