# GPU性能测试工具

本目录包含多个GPU性能对比测试工具，用于评估启用/禁用GPU加速对Chromium浏览器的性能和资源消耗影响。

## 测试工具概览

### 1. `simple_gpu_test.py` - 快速基础测试 ⚡
**推荐用于快速验证**

最简单的测试脚本，快速对比GPU加速和软件渲染的性能差异。

```bash
python tests/simple_gpu_test.py
```

**特点：**
- 无需额外依赖
- 测试速度快（约1-2分钟）
- 提供基础性能对比
- 输出清晰直观

**输出指标：**
- 启动时间
- 页面加载时间
- 渲染测试时间
- DOM性能指标

---

### 2. `gpu_resource_monitor.py` - 资源监控测试 📊
**推荐用于详细分析**

带系统资源监控的完整测试，可以实时监控CPU和内存使用情况。

```bash
# 需要先安装依赖
pip install psutil

# 运行测试
python tests/gpu_resource_monitor.py
```

**特点：**
- 实时监控CPU和内存使用
- 详细的资源统计（平均值、峰值）
- 包含浏览器性能API指标
- 生成完整的对比报告

**输出指标：**
- 启动/导航/渲染时间
- CPU使用率（平均/峰值）
- 内存使用量（平均/峰值）
- 首次绘制时间
- DOM加载指标

---

### 3. `benchmark_gpu.py` - 完整基准测试 🔬
**推荐用于生产环境评估**

最完整的基准测试工具，支持多次迭代、统计分析和结果导出。

```bash
# 需要安装依赖
pip install psutil

# 基础用法
python tests/benchmark_gpu.py

# 自定义测试参数
python tests/benchmark_gpu.py \
    --url https://gemini.google.com \
    --iterations 20 \
    --delay 3.0 \
    --output my_benchmark.json
```

**参数说明：**
- `--url`: 测试URL（默认：https://gemini.google.com）
- `--iterations`: 每种模式测试次数（默认：10）
- `--delay`: 测试间隔秒数（默认：2.0）
- `--output`: 结果JSON文件路径

**特点：**
- 多次迭代取平均值
- 详细的统计分析
- 导出JSON格式结果
- 包含所有原始数据

**输出指标：**
- 所有时间和资源指标的统计（平均/最大/最小）
- 成功率统计
- 性能改善百分比
- 完整的原始测试数据

---

## 测试结果解读

### 性能指标

1. **启动时间（Launch Time）**
   - 浏览器启动到可用的时间
   - GPU通常不影响启动时间

2. **导航时间（Navigation Time）**
   - 从开始导航到页面网络空闲的时间
   - 包含网络请求和初始渲染

3. **渲染时间（Render Time）**
   - 执行复杂渲染任务的时间
   - GPU加速对此影响最大

4. **总时间（Total Time）**
   - 整个测试的总耗时

### 资源指标

1. **CPU使用率**
   - GPU加速可能降低CPU使用（GPU分担渲染）
   - 或可能增加（GPU驱动开销）

2. **内存使用**
   - GPU模式通常会增加一些内存占用
   - 用于GPU缓冲区和上下文

### 浏览器性能指标

1. **DOM内容加载（domContentLoaded）**
   - HTML解析和DOM构建完成时间

2. **页面加载完成（loadComplete）**
   - 所有资源加载完成时间

3. **首次内容绘制（firstContentfulPaint）**
   - 首次渲染可见内容的时间

---

## 使用建议

### 选择测试工具

```
📌 快速验证 → simple_gpu_test.py
📌 详细分析 → gpu_resource_monitor.py
📌 正式评估 → benchmark_gpu.py
```

### 测试环境建议

1. **关闭其他程序**
   - 减少干扰因素
   - 获得更准确的资源使用数据

2. **运行多次测试**
   - 首次运行可能包含冷启动开销
   - 建议至少运行3次取平均值

3. **测试真实场景**
   - 使用项目实际要访问的URL
   - 模拟真实的使用负载

### 结果判断标准

✅ **建议启用GPU（满足任一条件）：**
- 总时间提升 > 10%
- 渲染时间提升 > 15%
- CPU使用降低 > 20%
- 内存增加 < 100MB

⚠️ **建议禁用GPU（满足任一条件）：**
- 总时间降低 > 5%
- 测试频繁失败或崩溃
- 内存增加 > 500MB
- 运行环境无GPU硬件

ℹ️ **差异不明显（±5%）：**
- 根据服务器资源情况决定
- 优先考虑稳定性

---

## GPU配置说明

### GPU加速参数
```python
args = [
    "--use-gl=egl",                    # 使用EGL OpenGL，有核显自动加速
    "--enable-gpu-rasterization",      # 启用GPU光栅化
    "--enable-accelerated-2d-canvas",  # 2D画布加速
    "--enable-accelerated-video-decode", # 视频解码加速
    "--no-sandbox",                    # 必需：兼容非root用户
]
```

### 禁用GPU参数
```python
args = [
    "--disable-gpu",                # 完全禁用GPU
    "--disable-software-rasterizer", # 禁用软件光栅化后备
    "--disable-dev-shm-usage",      # 禁用/dev/shm（容器环境）
    "--no-sandbox",                 # 必需：兼容非root用户
]
```

---

## 常见问题

### Q: 测试显示GPU模式反而更慢？
**可能原因：**
1. 运行环境没有GPU硬件或驱动
2. 在虚拟化/容器环境中，GPU passthrough未配置
3. 测试负载太轻，GPU初始化开销抵消了性能收益

**解决方案：**
- 检查 `chrome://gpu` 确认GPU状态
- 使用软件渲染模式
- 增加测试负载（更多渲染任务）

### Q: 为什么需要 `--no-sandbox`？
在某些环境（Docker、非root用户）中，Chrome沙箱需要特殊权限。`--no-sandbox` 禁用沙箱以避免权限问题。

**安全注意：** 生产环境中访问不可信内容时，考虑使用其他隔离方案。

### Q: `--use-gl=egl` 是什么？
EGL是OpenGL ES的接口，用于在没有完整X11的环境（如headless服务器）中启用GPU加速。如果没有GPU硬件，会自动失效。

### Q: 如何查看Chrome的GPU状态？
在GUI模式下访问：`chrome://gpu`

在测试中添加：
```python
gpu_info = await page.evaluate("() => navigator.gpu ? 'WebGPU支持' : 'WebGPU不支持'")
```

---

## 生产环境建议

### Docker容器中使用GPU

**1. 检查宿主机GPU：**
```bash
lspci | grep -i vga
```

**2. 安装GPU驱动（宿主机）：**
```bash
# Intel核显
sudo apt install intel-media-va-driver

# NVIDIA
# 需要安装nvidia-docker2
```

**3. Docker启动参数：**
```yaml
services:
  app:
    devices:
      - /dev/dri:/dev/dri  # GPU设备
    security_opt:
      - seccomp=unconfined
```

### 性能调优

**推荐配置（有GPU）：**
```python
args = [
    "--use-gl=egl",
    "--enable-gpu-rasterization",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]
```

**推荐配置（无GPU/容器）：**
```python
args = [
    "--disable-gpu",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
]
```

---

## 示例输出

### simple_gpu_test.py 输出示例
```
==================================================
测试配置: GPU加速模式
==================================================
✓ 浏览器启动耗时: 2.34s
✓ 页面加载耗时: 1.85s
✓ 渲染测试耗时: 1.12s
✓ DOM加载: 456ms
✓ 总耗时: 5.52s

📊 性能对比总结
==================================================
⏱️  总耗时对比:
  GPU加速: 5.52s
  软件渲染: 6.18s
  性能提升: +10.7%

💡 建议:
  ✅ GPU加速带来明显性能提升，建议启用
```

### gpu_resource_monitor.py 输出示例
```
📈 性能对比报告
==================================================
⏱️  时间对比:
指标                 GPU加速         软件渲染        差异
-----------------------------------------------------------------
启动时间             2.34s          2.41s          +2.9%
导航时间             1.85s          2.03s          +8.9%
渲染时间             1.12s          1.54s          +27.3%
总时间               5.52s          6.18s          +10.7%

💻 资源使用对比:
指标                 GPU加速         软件渲染        差异
-----------------------------------------------------------------
CPU平均使用          45.2%          78.6%          -33.4%
内存平均使用         285.3MB        256.7MB        +28.6MB
内存峰值使用         312.8MB        289.4MB        +23.4MB

💡 结论:
  ✅ GPU加速带来显著性能提升（>10%），强烈建议启用
```

---

## 集成到项目

如果测试结果表明GPU加速有益，可以在 `gemini_browser.py` 或 `browser_pool.py` 中应用：

```python
# 在 GeminiBrowser.__init__ 或相关位置
if self.enable_gpu:  # 添加GPU开关
    browser_args.extend([
        "--use-gl=egl",
        "--enable-gpu-rasterization",
        "--enable-accelerated-2d-canvas",
    ])
else:
    browser_args.extend([
        "--disable-gpu",
        "--disable-software-rasterizer",
    ])
```

---

## 相关资源

- [Chromium GPU Flags](https://peter.sh/experiments/chromium-command-line-switches/)
- [Playwright Browsers](https://playwright.dev/python/docs/browsers)
- [Chrome Headless GPU](https://developers.google.com/web/updates/2017/04/headless-chrome)
