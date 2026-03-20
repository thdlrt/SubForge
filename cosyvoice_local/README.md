## CosyVoice Local Service

本目录在 `config.json` 中将 **`tts_provider`** 设为 **`cosyvoice`** 时由主程序自动管理。

### 首次使用时会发生什么

1. 在 `cosyvoice_local/.venv` 创建独立 Python 虚拟环境  
2. 将官方仓库克隆到 `cosyvoice_local/vendor/CosyVoice`  
3. 安装 CosyVoice 依赖（主项目的 PyTorch 不受影响；此处会按 `cosyvoice_device` 安装 **PyTorch 2.7.1**，NVIDIA GPU 使用 **cu128** 索引，否则为 CPU 轮子）  
4. 下载预设说话人 SFT 模型与 `ttsfrd` 资源  
5. 启动本地 HTTP 服务供主程序调用 TTS  

体积与耗时主要集中在克隆与模型下载，请预留磁盘空间并保持网络畅通。

### 配置说明（主项目 `config.json`）

- **`cosyvoice_mode`**：`preset`（`cosyvoice_voice`）、`zero_shot`（参考音频 + `cosyvoice_prompt_text`）、`cross_lingual`（依服务端支持而定）  
- **`cosyvoice_device`**：`cpu` / `cuda` / `auto`  
- 服务端同一时间只处理一路推理；修改设备或模型相关选项后需重启 CosyVoice（退出主程序或结束对应进程后重试）  

更完整的参数表见仓库根目录 **README.md** 中「CosyVoice 本地服务」一节。

### Git 与本地文件

运行时产生的 venv、vendor、模型、日志、`server.pid`、`runtime.requirements.txt` 等已在根目录 **`.gitignore`** 中排除，请勿手动提交。
