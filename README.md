# Gemini2API

OpenAI 兼容的图片编辑 API，基于 Google Gemini 的浏览器自动化实现。

## 功能特性

- **多 API 兼容** - 同时支持 OpenAI 和 Gemini API 格式
- **浏览器池** - 多浏览器实例并行处理，支持负载均衡
- **多标签页** - 每个浏览器支持多标签页并发任务
- **速率限制** - 浏览器级别的请求频率控制
- **自动恢复** - 任务失败后自动重新初始化标签页
- **水印移除** - 自动去除生成图片的水印
- **无头模式** - 纯无头浏览器运行，无需 GUI

## 快速开始

### 环境要求

- Docker & Docker Compose
- 已登录 Google 账号的浏览器数据（首次需要手动登录）

### 部署

1. **克隆项目**

```bash
git clone https://github.com/yourname/gemini2api.git
cd gemini2api
```

2. **配置环境变量**

```bash
cp .env.example .env
# 编辑 .env 设置管理员密码等
```

3. **启动服务**

```bash
docker compose up -d
```

4. **访问管理面板**

打开 `http://localhost:8000/admin`，使用 `.env` 中配置的管理员账号登录。

5. **添加浏览器实例**

在管理面板中创建浏览器实例，首次需要手动完成 Google 账号登录。

## 项目结构

```
gemini2api/
├── engine/                  # 引擎层 (自动化核心)
│   ├── tasks/               # 任务定义 (run_task 模式)
│   ├── gemini/              # 浏览器配置和选择器
│   ├── actions.py           # 原子操作
│   ├── launcher.py          # 浏览器启动器
│   └── watermark_remover.py # 水印移除
├── services/                # 业务逻辑层 (资源管理与编排)
│   ├── browser_pool/        # 浏览器集群管理
│   ├── task_coordinator.py  # 任务协调者
│   └── ...
├── server/                  # 交付层 (API 接口)
│   ├── api/                 # API 路由
│   ├── db/                  # 数据库和模型
│   └── static/              # 静态文件
├── data/                    # 数据目录
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## API 接口

### OpenAI 兼容 API

```bash
# 图片编辑
POST /v1/images/edits
Content-Type: multipart/form-data

image: <图片文件>
prompt: "编辑指令"
model: "gemini-2.0-flash-exp"  # 可选: gemini-2.0-flash-exp, gemini-2.0-pro-exp-02-05
```

### Gemini 兼容 API

```bash
# 生成内容
POST /v1beta/models/{model_id}:generateContent
Content-Type: application/json

{
  "contents": [{
    "parts": [
      {"text": "编辑指令"},
      {"inline_data": {"mime_type": "image/png", "data": "base64..."}}
    ]
  }]
}
```

### 管理 API

| 端点                                  | 说明               |
| ------------------------------------- | ------------------ |
| `GET /api/admin/browsers`             | 获取所有浏览器状态 |
| `POST /api/admin/browsers`            | 创建浏览器实例     |
| `DELETE /api/admin/browsers/{id}`     | 删除浏览器实例     |
| `POST /api/admin/browsers/{id}/start` | 启动浏览器         |
| `POST /api/admin/browsers/{id}/stop`  | 停止浏览器         |
| `GET /api/admin/dashboard`            | 仪表盘数据         |

## 配置说明

### 环境变量

| 变量             | 默认值        | 说明         |
| ---------------- | ------------- | ------------ |
| `ADMIN_USERNAME` | admin         | 管理员用户名 |
| `ADMIN_PASSWORD` | changeme      | 管理员密码   |
| `TZ`             | Asia/Shanghai | 时区         |
| `DATA_DIR`       | ./data        | 数据目录     |

### 浏览器池配置

通过管理面板或 API 配置：

- **max_browsers** - 最大浏览器数量
- **max_tabs** - 每浏览器最大标签页数（默认 4）
- **rate_limit** - 每滑动窗口请求限制（默认 2 per 30s）
- **proxy** - 代理服务器（可选）

## 架构设计

```
请求 → API 路由 → 浏览器池 → 浏览器实例 → 标签页 → 原子操作 (Actions)
                    ↓
              负载均衡策略
              (最少负载/轮询/随机)
```

### 标签页生命周期

```
IDLE → BUSY → [成功] → IDLE
         ↓
      [失败] → 后台重新初始化 → IDLE
```

## 开发

### 本地运行 

通常 docker 运行

```bash
# 安装依赖
uv sync

# 安装浏览器
uv run playwright install chromium

# 启动服务
uv run uvicorn server.app:app --reload
```

### 测试

```bash
docker compose exec gemini2api uv run scripts/xxx.py
```

## 许可证

MIT License
