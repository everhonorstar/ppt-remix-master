# PPT Remix Master 中文说明

PPT Remix Master 是一个本地优先的 PPTX 二创工具。它可以把 PPTX 拆包，提取图片和文字，调用 AI 模型生成替换图片、改写文字，再生成审核预览。用户确认后，工具会把替换后的图片和文字重新写回 PPTX，尽量保留原始版式、媒体引用和动画绑定。

## 适合做什么

- 批量改造课件或演示文稿里的图片和文字
- 保留 PPT 原始布局，只替换素材和文本
- 先生成审核预览，再人工确认是否组装最终 PPTX
- 对一组拆分 PPT 复用相同图片的二创结果，减少重复生图
- 配合 Codex Skill 或 n8n 工作流自动执行

## 项目结构

- `cli/`：Python 命令行工具，命令名为 `ppt-remix`
- `skill/SKILL.md`：Codex Skill 说明文件
- `n8n/`：自托管 n8n 工作流示例
- `examples/`：示例 PPTX
- `jobs/`：任务输出目录，默认不提交真实任务结果
- `config.yaml.example`：模型配置模板
- `.env.example`：API Key 环境变量模板

## 安装

```bash
git clone https://github.com/everhonorstar/ppt-remix-master.git
cd ppt-remix-master
python3 -m pip install -e ./cli
```

如果要在 Codex 里使用这个 skill：

```bash
mkdir -p ~/.codex/skills/ppt-remix-master
cp skill/SKILL.md ~/.codex/skills/ppt-remix-master/SKILL.md
```

然后重启 Codex。

## 配置

复制配置模板：

```bash
cp .env.example .env
cp config.yaml.example config.yaml
```

`.env` 里填写自己的 key：

```bash
VISION_API_KEY=你的图片解构模型key
IMAGE_API_KEY=你的生图模型key
TEXT_API_KEY=你的文字改写模型key
```

`config.yaml` 里可以分别配置三类模型：

- `vision_provider`：负责分析原图，生成结构化图片提示词
- `image_provider`：负责根据提示词生成替换图片
- `text_provider`：负责改写 PPT 文本

没有真实模型 key 时，可以使用默认的 `local_mock`。它不会真正生图，只会复制原图并做简单文本替换，适合测试流程是否跑通。

## 快速开始

```bash
cd cli
python3 -m ppt_remix run ../examples/demo.pptx --out ../jobs --config ../config.yaml.example
```

`run` 命令会执行：

1. 拆包 PPTX
2. 生成图片和文字 manifest
3. 生成或复用替换图片
4. 改写文字
5. 生成审核预览

它默认只停在审核预览，不会自动生成最终 PPTX。

预览文件通常在：

```bash
jobs/demo/preview/index.html
```

确认预览后，再组装最终 PPTX：

```bash
python3 -m ppt_remix assemble ../jobs/demo --approved
```

输出文件通常在：

```bash
jobs/demo/output/remixed.pptx
```

## 常用命令

分步执行：

```bash
python3 -m ppt_remix prepare input.pptx --out jobs/job_id --config config.yaml
python3 -m ppt_remix remix-images jobs/job_id --concurrency 3 --config config.yaml
python3 -m ppt_remix rewrite-text jobs/job_id --config config.yaml
python3 -m ppt_remix preview jobs/job_id
python3 -m ppt_remix assemble jobs/job_id --approved
```

测试模型连通性：

```bash
python3 -m ppt_remix test-provider vision --config config.yaml
python3 -m ppt_remix test-provider image --config config.yaml
python3 -m ppt_remix test-provider text --config config.yaml
```

指定其他 `.env` 文件：

```bash
python3 -m ppt_remix --env-file /path/to/.env test-provider vision --config config.yaml
```

## 批次图片缓存

工具会根据 job 名自动建立批次缓存。例如：

- `我是值日生1.pptx`
- `我是值日生2.pptx`
- `我是值日生3.pptx`

会共用：

```bash
jobs/cache/我是值日生/
```

同一批次里，如果图片的 `sha256` 一样，工具会直接复用之前的 `prompt.json` 和生成图，避免重复调用模型。

## HTTP 服务模式

如果要配合 n8n Cloud 或远程自动化系统，可以启动本地 HTTP 服务：

```bash
cd cli
python3 -m ppt_remix server --root .. --config ../config.yaml
```

接口：

- `GET /health`
- `POST /run`
- `POST /assemble`

示例：

```json
{"input_pptx":"examples/demo.pptx","output_dir":"jobs","concurrency":3}
```

组装示例：

```json
{"job_dir":"jobs/demo","approved":true}
```

## 不要提交的文件

这些文件通常包含本地配置、密钥或任务结果，不应提交到公开仓库：

- `.env`
- `config.yaml`
- `jobs/`
- 真实客户 PPT 或课程素材

仓库里的 `.gitignore` 已经默认忽略这些内容。

## 测试

```bash
python3 -m unittest discover -s tests
```

当前测试覆盖：

- 透明 PNG 处理
- 透明背景提示词规则
- portable `.env` 查找
- 图片类型识别和尺寸读取
