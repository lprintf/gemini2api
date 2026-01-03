# Gemini 图片编辑 API

自动化 Gemini 图片编辑功能的 Python 库。

## 功能特性

- 自动登录和会话管理（基于持久化浏览器上下文）
- 多账户支持
- 自动上传图片并编辑
- 自动下载生成的图片（支持 WebP/PNG 格式）
- 支持中英文界面
- 智能去重（处理 Google 特殊的图片 URL 格式）
- **增强功能**（`enhanced_editor.py`）：
  - 事件监听和日志记录
  - 智能模型选择（Pro/Fast）
  - 临时对话支持
  - 基于真实DOM的稳定选择器

## 文件结构

### 核心文件

```text
gemini2api/
├── gemini_browser.py      # 浏览器会话管理器
├── image_editor.py         # 基础图片编辑器
├── enhanced_editor.py      # 增强版编辑器（推荐）
├── example.py              # 使用示例
└── test_enhanced.py        # 完整测试套件
```

### 文档

```text
├── README.md               # 项目主文档（本文件）
├── ENHANCED_GUIDE.md       # 增强版编辑器详细使用指南
├── TEST_REPORT.md          # 测试报告
├── CODEGEN_GUIDE.md        # Playwright Codegen 使用指南
├── CODEGEN_SUCCESS.md      # Codegen 成功案例分析
├── README_LOGIN.md         # 登录机制详解
└── CHANGELOG.md            # 更新日志
```

### 数据目录

```text
└── browser_data/           # 浏览器持久化数据（自动创建）
    └── 0/                  # 账户 0 的数据目录
```

## 安装依赖

```bash
uv add playwright
playwright install chromium
```

## 快速开始

### 1. 首次登录设置

```bash
cd gemini2api
uv run python gemini_browser.py login 0
```

浏览器会打开，按照提示：

1. 手动登录 Google 账户
2. 确认 Gemini 可以正常使用
3. 按 Enter 键保存状态

### 2. 基础图片编辑

```python
import asyncio
from image_editor import GeminiImageEditor

async def main():
    # 创建编辑器实例（账户 0，非无头模式）
    editor = GeminiImageEditor(account_id=0, headless=False)

    try:
        # 启动浏览器
        await editor.launch()

        # 编辑图片（WebP 无损格式，默认）
        result_paths = await editor.edit_image(
            input_image="test/lamp.webp",
            prompt="把这个灯变成蓝色的",
            output_dir="output/lamp_blue",
            wait_time=30,  # 等待生成时间（秒）
            output_format="webp",  # 输出 WebP 格式（默认）
            webp_lossless=True  # 无损压缩（默认）
        )

        if result_paths:
            print(f"成功生成 {len(result_paths)} 张图片:")
            for path in result_paths:
                print(f"  - {path}")

    finally:
        await editor.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### 3. 增强版编辑器（推荐）

增强版编辑器支持模型选择、临时对话等高级功能：

```python
import asyncio
from enhanced_editor import EnhancedGeminiImageEditor

async def main():
    # 创建增强版编辑器
    editor = EnhancedGeminiImageEditor(
        account_id=0,
        headless=False,
        enable_logging=True  # 启用事件日志
    )

    try:
        # 启动浏览器
        await editor.launch()

        # 使用增强版编辑方法
        result_paths = await editor.edit_image_enhanced(
            input_image="test/lamp.webp",
            prompt="把这个灯变成蓝色的",
            output_dir="output/lamp_blue_pro",
            model="Pro",  # 使用 Pro 模型（或 "Fast"）
            temporary_chat=True,  # 使用临时对话保护隐私
            output_format="webp",
            webp_lossless=True,
            save_log=True,  # 保存事件日志到 output_dir/event_log.json
        )

        if result_paths:
            print(f"成功生成 {len(result_paths)} 张图片")

    finally:
        await editor.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**增强版特性**：

- ✅ 智能模型选择（Pro/Fast 自动切换）
- ✅ 临时对话支持（隐私保护）
- ✅ 事件日志记录（调试和分析）
- ✅ 更稳定的选择器（基于 `data-test-id`）
- ✅ 完整的验证机制

详细文档：[ENHANCED_GUIDE.md](ENHANCED_GUIDE.md)

### 4. 运行测试

```bash
# 测试所有增强功能
uv run python test_enhanced.py

# 测试单个功能
uv run python test_enhanced.py model          # 模型选择
uv run python test_enhanced.py temp_chat      # 临时对话
uv run python test_enhanced.py activate       # 图片生成激活
uv run python test_enhanced.py full           # 完整工作流程
```

## API 文档

### GeminiImageEditor（基础版）

基础的图片编辑类。

**初始化参数:**

- `account_id` (int): 账户 ID，用于多账户管理，默认 0
- `headless` (bool): 是否使用无头模式，默认 False
- `proxy` (Optional[str]): 代理服务器地址，例如 `http://10.42.0.1:20171`

**主要方法:**

#### `async launch(timeout: int = 60000) -> Page`

启动浏览器并登录 Gemini。

#### `async edit_image(...) -> Optional[List[str]]`

完整的图片编辑流程。

**参数:**

- `input_image` (str): 输入图片路径
- `prompt` (str): 编辑指令
- `output_dir` (str): 输出目录，默认 "output"
- `wait_time` (int): 等待生成的时间（秒），默认 30
- `upload_method` (str): 上传方式 - "paste"（粘贴，推荐）、"button"（按钮）、"manual"（手动），默认 "paste"
- `upload_timeout` (int): 手动上传模式的超时时间（秒），默认 60
- `output_format` (str): 输出格式 - "webp"（推荐，文件小）、"png"（原始格式），默认 "webp"
- `webp_lossless` (bool): WebP 无损压缩，默认 True（推荐）；False 为有损压缩 quality=80

**返回:**

- 成功: 生成图片的路径列表
- 失败: None

#### `async close()`

关闭浏览器。

---

### EnhancedGeminiImageEditor（增强版，推荐）

增强版图片编辑类，继承自 `GeminiImageEditor`，添加了高级功能。

**初始化参数:**

- `account_id` (int): 账户 ID，默认 0
- `headless` (bool): 是否使用无头模式，默认 False
- `proxy` (Optional[str]): 代理服务器地址
- `enable_logging` (bool): 是否启用事件日志，默认 True

**增强方法:**

#### `async ensure_model_selection(model: Literal["Pro", "Fast"]) -> bool`

确保选择了指定的模型。

**参数:**
- `model`: 目标模型 "Pro" 或 "Fast"

**返回:**
- 是否成功选择模型

#### `async enable_temporary_chat() -> bool`

启用临时对话模式。

**返回:**
- 是否成功启用

#### `async edit_image_enhanced(...) -> Optional[List[str]]`

增强版图片编辑方法，支持模型选择和临时对话。

**参数:**（除了基础参数外）

- `model` (Literal["Pro", "Fast"]): 使用的模型，默认 "Fast"
- `temporary_chat` (bool): 是否使用临时对话，默认 False
- `save_log` (bool): 是否保存事件日志，默认 True

**返回:**

- 成功: 生成图片的路径列表
- 失败: None

#### `save_event_log(path: str)`

保存事件日志到文件。

## 工作原理

### 1. 浏览器会话管理

使用 Playwright 的 `launch_persistent_context` 维护登录状态，无需每次重新登录。

### 2. 自动上传

支持三种上传方式：

1. **粘贴上传（默认，推荐）**：通过模拟 Ctrl+V 粘贴操作上传，最快最可靠
2. **按钮上传**：通过点击上传按钮并拦截文件选择器
3. **手动上传**：等待用户手动拖拽上传

特性：

- 支持中英文界面自动适配
- 使用结构化 DOM 导航（优先搜索菜单容器）
- 并发等待元素就绪（优化性能）

### 3. 精确图片定位与智能去重

**容器定位策略**：

为避免下载到页面其他位置的图片（侧边栏、历史记录等），使用对话容器定位：

1. 定位最新的模型回复容器（`model-response`、`message-content`、`response-container`）
2. 只在该容器内搜索图片
3. 如果定位失败，回退到全局搜索

**智能去重**：

Google 的图片 URL 格式特殊，尺寸参数在路径中：

```text
https://...googleusercontent.com/...=w160-h160-rj  # 缩略图
https://...googleusercontent.com/...=s1024-rj      # 高清图
```

解决方案：

- 等待 5 秒让图片完全加载（缩略图 → 高清图）
- 过滤掉明确的缩略图（w160, h160）
- 使用正则表达式移除尺寸参数后去重
- 优先使用高清图URL

### 4. 下载格式

支持两种输出格式：

1. **WebP 格式（默认，推荐）**：
   - **无损压缩**（默认）：文件大小约为 PNG 的 60%（压缩率 ~40%）
   - **有损压缩**：文件大小约为 PNG 的 1.6%（压缩率 ~98%），quality=80
   - 使用 Pillow 库将下载的 PNG 自动转换为 WebP

2. **PNG 格式**：
   - 原始格式，文件较大但兼容性好
   - 通过 JavaScript 模拟 hover 触发下载按钮
   - 回退方式：使用 fetch API 在浏览器上下文中下载

**文件大小对比示例（1024x1024）：**

| 格式 | 文件大小 | 压缩率 |
| --- | --- | --- |
| PNG（原始） | 511.8 KB | - |
| WebP 无损 | 308.3 KB | 39.8% |
| WebP 有损 | 8.0 KB | 98.4% |

## 注意事项

1. **首次使用需要手动登录**: 第一次运行时会打开浏览器，需要手动登录 Gemini，之后会话会被保存
2. **等待时间**: `wait_time` 参数需要根据网络状况调整，建议 30-60 秒
3. **代理配置**: 如果需要代理，在初始化时传入 `proxy` 参数
4. **多账户**: 使用不同的 `account_id` 可以管理多个 Gemini 账户

## 已知限制

- 图片粘贴上传的文件名必须带扩展名（.webp、.jpg、.png），否则 Gemini 无法识别
- 生成时间取决于 Gemini 服务器响应速度
- 图片数量由 Gemini 决定（通常 1-4 张）

## 多账户管理

### 命令参考

| 命令 | 说明 | 示例 |
| ------ | ------ | ------ |
| `login [账户编号]` | 首次手动登录并保存状态 | `python gemini_browser.py login 0` |
| `run <账户编号> [--headless]` | 运行浏览器会话 | `python gemini_browser.py run 0 --headless` |
| `list` | 列出所有已保存的账户 | `python gemini_browser.py list` |

### 为什么使用持久化浏览器上下文？

简单的 cookies 注入不够可靠，Google 的认证需要：

- 完整的 cookie 链（不只是几个关键 cookies）
- localStorage 和 sessionStorage 数据
- 浏览器指纹和 session 信息
- 正确的请求序列

使用 Playwright 的持久化上下文可以完整保存这些状态，实现真正的自动登录。
