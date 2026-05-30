# Docker 使用说明

基础镜像用于运行 Tagent 主流程和评测：

```bash
docker build -t tagent:latest -f Dockerfile .
docker run --rm -it tagent:latest
```

运行意图评测：

```bash
docker run --rm -it tagent:latest python EvalTest/Eval_intent/run_eval.py --suite full_eval
```

如果需要读取本机配置或输出结果，可以挂载目录：

```bash
docker run --rm -it \
  -v "$PWD/data/generated:/app/data/generated" \
  tagent:latest \
  python EvalTest/Eval_intent/run_eval.py --suite full_eval
```

Playwright 镜像用于执行 Web UI/E2E 自动化脚本：

```bash
docker build -t tagent:playwright -f Dockerfile.playwright .
docker run --rm -it tagent:playwright npx playwright --version
```

项目里的 `.doc` 旧格式文档在 macOS 里使用 `textutil`，Docker 里使用 `libreoffice` 作为系统级文档处理工具。当前代码还没有专门调用 LibreOffice 解析 `.doc`，如果后续要求容器内完整解析旧 `.doc`，需要把解析入口从 `textutil` 迁移到 LibreOffice。
