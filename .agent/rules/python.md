---
trigger: model_decision
description: 修改完python文件后
---

# After Modify .py File
- 修改完python代码后运行`docker compose exec gemini2api uv run python -c "import server.app"`