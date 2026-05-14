# PPT Remix Master

[中文版说明](README.zh-CN.md)

本地优先的 PPTX 二创工具。核心流程由 CLI 负责，n8n 负责上传、审核、通知和编排。

## 分享/安装给其他人

这个项目包含两部分：

- `cli/`：真正处理 PPTX 的 Python 命令行工具
- `skill/SKILL.md`：给 Codex 使用的 Skill 说明

别人拿到仓库后，可以按下面步骤安装：

macOS / Linux:

```bash
git clone https://github.com/everhonorstar/ppt-remix-master.git
cd ppt-remix-master

python3 -m pip install -e ./cli

mkdir -p ~/.codex/skills/ppt-remix-master
cp skill/SKILL.md ~/.codex/skills/ppt-remix-master/SKILL.md

cp .env.example .env
cp config.yaml.example config.yaml
```

Windows PowerShell:

```powershell
git clone https://github.com/everhonorstar/ppt-remix-master.git
cd ppt-remix-master

py -3 -m pip install -e ./cli

New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills\ppt-remix-master"
Copy-Item skill\SKILL.md "$env:USERPROFILE\.codex\skills\ppt-remix-master\SKILL.md"

Copy-Item .env.example .env
Copy-Item config.yaml.example config.yaml
```

然后编辑 `.env` 和 `config.yaml`，填入自己的模型供应商、模型名和 API Key。完成后重启 Codex，即可使用 `ppt-remix-master` skill。

不要提交这些本地文件：

- `.env`
- `config.yaml`
- `jobs/`
- 真实客户/课程 PPT 素材

## 目录

- `cli/`：Python CLI，命令名 `ppt-remix`
- `skill/`：Codex Skill 使用说明
- `n8n/`：自托管 n8n 工作流示例和环境变量示例
- `jobs/`：任务输出目录
- `examples/`：样例文件目录

## 快速开始

macOS / Linux:

```bash
cd ppt-remix-master/cli
python3 -m ppt_remix run ../examples/demo.pptx --out ../jobs --config ../config.yaml.example
```

Windows PowerShell:

```powershell
cd ppt-remix-master\cli
py -3 -m ppt_remix run ..\examples\demo.pptx --out ..\jobs --config ..\config.yaml.example
```

`run` 默认只生成审核预览，不会自动组装最终 PPTX。用户明确确认后，再单独执行 `assemble --approved`。没有真实模型 key 时，`local_mock` 会复制原图片并做简单文本替换，用来验证 PPTX 处理链路。

最终 PPTX 会按源文件名命名：源文件名去掉 `.pptx` 后追加 `_remixed.pptx`。例如 `demo.pptx` 输出 `demo_remixed.pptx`，`我是班级值日生3.pptx` 输出 `我是班级值日生3_remixed.pptx`。

## Windows 使用说明

这个项目的 CLI 使用 Python 标准库、`requests`、`PyYAML` 和 `Pillow`，没有依赖 macOS 专用功能，适合在 Windows 上安装使用。Windows 用户建议在 PowerShell 中执行命令，并注意：

- 使用 `py -3` 或 `python` 替代 `python3`
- 使用 `New-Item` 替代 `mkdir -p`
- 使用 `Copy-Item` 替代 `cp`
- 路径分隔符可以使用 `\`，例如 `..\jobs`
- 如果 n8n 也跑在 Windows，Execute Command 节点里的命令和路径也要改成 PowerShell/Windows 格式
- 老旧 Windows 环境可能受路径长度限制影响，建议把项目放在较短路径下，例如 `C:\tools\ppt-remix-master`

## 批次图片缓存

CLI 会按 PPT/job 文件名自动建立批次缓存区，用来在同一组拆分 PPT 之间复用相同图片的二创结果。例如：

- `我是值日生1.pptx`
- `我是值日生2.pptx`
- `我是值日生3.pptx`

都会使用同一个缓存区：

```bash
jobs/cache/我是值日生/
```

每张图片按原图 `sha256` 查缓存。命中时直接复用 `prompt.json` 和生成图；未命中时正常执行 vision 解构和生图，并写入该缓存区。

透明背景素材会在生图或缓存恢复后自动做质量稳定化检查：如果发现尺寸/比例不一致、透明通道缺失、疑似棋盘格假透明背景，或主体覆盖明显异常，CLI 会自动生成一个保留原始 alpha 通道的安全二创版本，并在 `image_manifest.json` 的 `quality` 字段记录处理动作。

## 分模型 API Key

`config.yaml` 里三类模型独立配置：

- `vision_provider`：图片解构 JSON prompt
- `image_provider`：二创生图
- `text_provider`：文字改写

对应环境变量：

- `VISION_API_KEY`
- `IMAGE_API_KEY`
- `TEXT_API_KEY`

三者可以接不同厂商、不同模型、不同 base URL。

把真实 key 放到项目根目录 `.env`，CLI 会自动加载：

```bash
cp .env.example .env
```

`.env` 内容：

```bash
VISION_API_KEY=你的图片解构模型key
IMAGE_API_KEY=你的生图模型key
TEXT_API_KEY=你的文字改写模型key
```

如需指定其他 env 文件：

```bash
python3 -m ppt_remix --env-file /path/to/.env test-provider vision --config config.yaml
```

Gemini vision 示例：

```yaml
vision_provider:
  provider: gemini
  base_url: https://generativelanguage.googleapis.com
  api_key_env: VISION_API_KEY
  model: gemini-3.1-pro-preview
  timeout: 120
  retry: 2
```

测试 vision 连通性：

```bash
cd ppt-remix-master/cli
python3 -m ppt_remix test-provider vision --config ../config.yaml
```

## 常用命令

```bash
python3 -m ppt_remix prepare input.pptx --out jobs/job_id --config config.yaml
python3 -m ppt_remix remix-images jobs/job_id --concurrency 3 --config config.yaml
python3 -m ppt_remix rewrite-text jobs/job_id --config config.yaml
python3 -m ppt_remix preview jobs/job_id
python3 -m ppt_remix assemble jobs/job_id --approved
```

## n8n

第一版面向自托管 n8n。导入 `n8n/ppt-remix-self-hosted.workflow.json` 后，需要在上传节点和 Execute Command 节点之间补一个“保存上传文件到本地路径”的节点，并设置：

```bash
PPT_REMIX_ROOT=/path/to/ppt-remix-master
N8N_DEFAULT_BINARY_DATA_MODE=filesystem
```

如果使用 n8n Cloud 或远程 n8n，可以在本机启动轻量 HTTP 服务：

```bash
cd ppt-remix-master/cli
python3 -m ppt_remix server --root .. --config ../config.yaml
```

然后让 n8n 用 HTTP Request 调用：

- `GET /health`
- `POST /run`，JSON：`{"input_pptx":"examples/demo.pptx","output_dir":"jobs","concurrency":3}`，只生成审核预览
- `POST /assemble`，JSON：`{"job_dir":"jobs/demo","approved":true}`
