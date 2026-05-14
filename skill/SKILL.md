---
name: ppt-remix-master
description: Use when remixing PPTX files by extracting slide images, creating AI-derived replacement images, rewriting slide text with similar meaning and length, generating an approval preview, and assembling a new PPTX while preserving layout and animation bindings.
metadata:
  short-description: Remix PPTX images and text with AI
---

# PPT Remix Master

Use the bundled CLI for PPTX remix work. The CLI edits PPTX packages in place by unpacking Open XML, replacing media assets and text nodes, then repacking. Do not rebuild slides from scratch unless the user explicitly asks for a redesign.

## Workflow

1. Prepare the job:
   ```bash
   ppt-remix prepare input.pptx --out jobs/job_id --config config.yaml
   ```
2. Remix images in a loop with bounded concurrency:
   ```bash
   ppt-remix remix-images jobs/job_id --concurrency 3 --config config.yaml
   ```
3. Rewrite text:
   ```bash
   ppt-remix rewrite-text jobs/job_id --config config.yaml
   ```
4. Create an approval preview:
   ```bash
   ppt-remix preview jobs/job_id
   ```
5. After approval, assemble:
   ```bash
   ppt-remix assemble jobs/job_id --approved
   ```
   The assembled file must be named from the source PPTX stem plus `_remixed`, for example `jobs/job_id/output/input_remixed.pptx`.

For a single local run, `run` always stops at preview and never assembles:

```bash
ppt-remix run input.pptx --out jobs --config config.yaml
```

## AI Provider Rules

Configure image analysis, image generation, and text rewriting separately. Never assume one API key or one model serves all three.

- `VISION_API_KEY` for `vision_provider`
- `IMAGE_API_KEY` for `image_provider`
- `TEXT_API_KEY` for `text_provider`

Use `local_mock` for dry runs. It copies original images and applies simple local text substitutions so PPTX extraction, manifests, preview, and assembly can be tested without model access.

## Batch Asset Cache

When multiple split PPTX files share a project-style filename, reuse image remix assets through an automatic batch cache. Derive the cache name from the PPT/job name by stripping a trailing number or part marker:

- `我是值日生1.pptx` -> `我是值日生`
- `我是值日生 1.pptx` -> `我是值日生`
- `我是值日生-1.pptx` -> `我是值日生`
- `我是值日生（1）.pptx` -> `我是值日生`

Cache path:

```bash
jobs/cache/<cache_name>/<image_sha256>/
```

On image remix, check only this cache for the current cache name. If `prompt.json`, `generated.<ext>`, and `metadata.json` exist, copy them into the current job and mark the image as `cached`. Otherwise run vision plus image generation and store the result in the cache. Do not use a global cache outside the matching project cache name.

## Remix Rules

- People: swap gender and adjust visible gendered traits naturally; preserve age range, profession, emotion, and story role.
- Actions: mirror meaningful left/right actions, such as changing a left-hand object hold to the right hand.
- Scenes: mirror spatial direction when it makes sense, without breaking scene logic.
- Text inside images: do not mirror readable text; avoid garbled generated text.
- Output images must fit the source image's aspect ratio and replacement role.

## Review

Default to producing `preview/index.html`, `preview/summary.json`, `image_manifest.json`, and `text_manifest.json`, then stop. Assemble only after the user gives an explicit confirmation such as “确认”, “同意”, or “通过”, and then run `ppt-remix assemble jobs/job_id --approved`.

Final PPTX naming standard: assemble outputs `output/<source_filename_stem>_remixed.pptx`; preserve the original source filename stem, including Chinese characters and part numbers.
