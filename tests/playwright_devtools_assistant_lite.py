"""
Playwright 辅助 DevTools 调试工具 - 轻量级版本

功能：
1. 自动打开页面
2. 只在关键时刻监控（发送请求时）
3. 不做持续扫描，性能友好
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright


class PlaywrightDevToolsAssistantLite:
    """Playwright 辅助 DevTools 调试 - 轻量级版本"""

    def __init__(self, account_id: int = 0):
        self.account_id = account_id
        self.base_dir = Path(__file__).parent.parent / "data"
        data_dir = Path("/app/data") if Path("/app/data").exists() else self.base_dir
        self.user_data_dir = data_dir / "browser_data" / str(account_id)
        self.output_dir = Path(__file__).parent.parent / "data" / "devtools_assist"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.captured_tokens = []
        self.captured_requests = []

    async def assist_debugging(self):
        """启动辅助调试"""
        print("=" * 80)
        print("🤖 Playwright + DevTools 辅助调试工具（轻量级）")
        print("=" * 80)
        print("\n功能:")
        print("  1. 自动打开页面")
        print("  2. 拦截网络请求")
        print("  3. 只在发送请求时监控（不持续扫描）")
        print("  4. 在关键时刻暂停调试")
        print("=" * 80)

        async with async_playwright() as p:
            # 启动浏览器
            context = await p.chromium.launch_persistent_context(
                str(self.user_data_dir),
                headless=False,
                devtools=True,  # 自动打开 DevTools
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--auto-open-devtools-for-tabs",
                ],
                viewport={"width": 1400, "height": 900},
            )

            page = context.pages[0] if context.pages else await context.new_page()

            # 注入轻量级监控代码（只在请求时触发）
            await page.add_init_script("""
                // ========================================
                // 轻量级令牌监控系统
                // ========================================

                window._tokenTracker = {
                    tokens: [],

                    // 记录发现的令牌
                    recordToken: function(token, source) {
                        if (typeof token === 'string' && token.startsWith('!') && token.length > 1000) {
                            const record = {
                                token: token,
                                length: token.length,
                                source: source,
                                timestamp: Date.now()
                            };
                            this.tokens.push(record);
                            console.log('%c🎯 发现令牌!', 'color: #00ff00; font-size: 16px; font-weight: bold;');
                            console.log('来源:', source);
                            console.log('长度:', token.length);
                            console.log('开头:', token.substring(0, 80));

                            // 触发 debugger
                            debugger;
                        }
                    },

                    // 扫描对象查找令牌（按需调用，不自动）
                    scanObject: function(obj, path = 'root', maxDepth = 3, currentDepth = 0) {
                        if (!obj || typeof obj !== 'object' || currentDepth > maxDepth) return;

                        try {
                            for (let key in obj) {
                                const value = obj[key];
                                const fullPath = `${path}.${key}`;

                                if (typeof value === 'string' && value.startsWith('!') && value.length > 1000) {
                                    this.recordToken(value, fullPath);
                                } else if (typeof value === 'object' && value !== null && currentDepth < maxDepth) {
                                    this.scanObject(value, fullPath, maxDepth, currentDepth + 1);
                                }
                            }
                        } catch (e) {
                            // 忽略访问限制的属性
                        }
                    },

                    // 扫描字符串中的令牌
                    scanString: function(str, source) {
                        if (typeof str !== 'string') return;

                        // 查找以 ! 开头的长字符串
                        const matches = str.match(/![A-Za-z0-9_-]{1000,}/g);
                        if (matches) {
                            matches.forEach(token => {
                                this.recordToken(token, source);
                            });
                        }
                    }
                };

                // 拦截 fetch（轻量级）
                const originalFetch = window.fetch;
                window.fetch = async function(...args) {
                    const url = args[0];
                    const options = args[1] || {};

                    console.log('%c📤 Fetch Request', 'color: #00aaff; font-weight: bold;', url);

                    if (url && url.includes('StreamGenerate')) {
                        console.log('%c🎯 StreamGenerate 请求！', 'color: #ff0000; font-size: 16px; font-weight: bold;');
                        console.log('URL:', url);
                        console.log('Options:', options);

                        // 扫描 body 查找令牌
                        if (options.body) {
                            console.log('Body:', options.body);
                            window._tokenTracker.scanString(options.body, 'fetch.body');
                        }

                        // 暂停
                        debugger;
                    }

                    return originalFetch.apply(this, args);
                };

                // 拦截 XMLHttpRequest（轻量级）
                const originalOpen = XMLHttpRequest.prototype.open;
                const originalSend = XMLHttpRequest.prototype.send;

                XMLHttpRequest.prototype.open = function(method, url) {
                    this._url = url;
                    this._method = method;
                    console.log('%c📤 XHR Request', 'color: #00aaff; font-weight: bold;', method, url);
                    return originalOpen.apply(this, arguments);
                };

                XMLHttpRequest.prototype.send = function(data) {
                    if (this._url && this._url.includes('StreamGenerate')) {
                        console.log('%c🎯 StreamGenerate XHR！', 'color: #ff0000; font-size: 16px; font-weight: bold;');
                        console.log('URL:', this._url);
                        console.log('Method:', this._method);
                        console.log('Data:', data);

                        // 扫描 data 查找令牌
                        window._tokenTracker.scanString(data, 'xhr.data');

                        // 暂停
                        debugger;
                    }
                    return originalSend.apply(this, arguments);
                };

                console.log('%c✅ 轻量级令牌监控系统已启动', 'color: #00ff00; font-size: 14px; font-weight: bold;');
                console.log('提示:');
                console.log('  - 只在发送请求时监控，不持续扫描');
                console.log('  - 发现令牌时会自动暂停（debugger）');
                console.log('  - 如需手动扫描，执行: window._tokenTracker.scanObject(window, "window")');
            """)

            # 监听请求
            page.on("request", self._on_request)
            page.on("response", self._on_response)

            print("\n✅ 监控代码已注入")
            print("\n🌐 正在打开 Gemini...")

            await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await asyncio.sleep(3)

            print("\n" + "=" * 80)
            print("📋 使用指南")
            print("=" * 80)

            print("\n🎯 自动功能:")
            print("  ✅ 已注入轻量级监控代码")
            print("  ✅ 已设置 fetch/XHR 拦截")
            print("  ✅ 发现令牌时会自动 debugger")
            print("  ✅ Console 中会打印详细信息")

            print("\n📍 手动操作:")
            print("  1. 在 DevTools 中切换到 Console 标签")
            print("  2. 看到绿色的 '✅ 轻量级令牌监控系统已启动' 提示")
            print("  3. 执行图片编辑操作")
            print("  4. 当发现令牌时:")
            print("     - Console 会打印绿色的 '🎯 发现令牌!'")
            print("     - 代码会自动暂停 (debugger)")
            print("     - 查看 Call Stack 和 Scope")

            print("\n🔍 在 Console 中可以执行:")
            print("  window._tokenTracker.tokens              // 查看所有发现的令牌")
            print("  window._tokenTracker.tokens[0].token     // 查看第一个令牌")
            print("  window._tokenTracker.tokens[0].source    // 查看令牌来源")
            print("\n💡 手动扫描（按需执行）:")
            print("  window._tokenTracker.scanObject(window, 'window')  // 扫描 window 对象")

            print("\n" + "=" * 80)
            print("⏸️  等待你的操作...")
            print("=" * 80)
            print("\n提示:")
            print("  - 当前页面已打开，DevTools 已启动")
            print("  - 执行图片编辑操作")
            print("  - 观察 Console 输出")
            print("  - 在 debugger 暂停时查看变量")
            print("\n按 Enter 结束调试...")

            input()

            # 提取最终结果
            tokens = await page.evaluate("() => window._tokenTracker ? window._tokenTracker.tokens : []")

            print("\n" + "=" * 80)
            print("📊 调试结果")
            print("=" * 80)

            if tokens:
                print(f"\n✅ 发现 {len(tokens)} 个令牌:\n")
                for i, token_info in enumerate(tokens, 1):
                    print(f"{i}. 来源: {token_info['source']}")
                    print(f"   长度: {token_info['length']}")
                    print(f"   时间: {token_info['timestamp']}")
                    print(f"   开头: {token_info['token'][:80]}...")
                    print()

                # 保存结果
                await self._save_results(tokens)
            else:
                print("\n⚠️  未发现令牌")
                print("\n可能的原因:")
                print("  1. 还没有执行触发令牌的操作")
                print("  2. 令牌不在被监控的位置")
                print("  3. 需要手动在 DevTools 中查找")

                print("\n💡 建议:")
                print("  1. 检查 Console 中是否有红色的 StreamGenerate 提示")
                print("  2. 在 debugger 暂停时，手动查看 Scope 面板")
                print("  3. 在 Console 中执行: window._tokenTracker.scanObject(window, 'window')")

            await context.close()

    def _on_request(self, request):
        """请求监听"""
        if "StreamGenerate" in request.url:
            print(f"\n🎯 捕获到 StreamGenerate 请求")
            print(f"   URL: {request.url[:100]}...")

            if request.post_data:
                print(f"   Body 长度: {len(request.post_data)} 字节")

                # 尝试提取令牌
                try:
                    import urllib.parse
                    params = {}
                    for part in request.post_data.split('&'):
                        if '=' in part:
                            key, value = part.split('=', 1)
                            params[key] = urllib.parse.unquote(value)

                    if 'f.req' in params:
                        freq = json.loads(params['f.req'])
                        if len(freq) > 1:
                            inner = json.loads(freq[1])
                            if len(inner) > 3 and isinstance(inner[3], str) and inner[3].startswith('!'):
                                token = inner[3]
                                print(f"   ✅ 提取到令牌！")
                                print(f"      长度: {len(token)}")
                                print(f"      开头: {token[:80]}...")

                                self.captured_tokens.append({
                                    'token': token,
                                    'length': len(token),
                                    'source': 'request_body',
                                    'timestamp': asyncio.get_event_loop().time()
                                })
                except Exception as e:
                    pass

            self.captured_requests.append({
                'url': request.url,
                'method': request.method,
                'timestamp': asyncio.get_event_loop().time()
            })

    def _on_response(self, response):
        """响应监听"""
        if "StreamGenerate" in response.url:
            print(f"\n📥 StreamGenerate 响应: {response.status}")

    async def _save_results(self, tokens):
        """保存结果"""
        import time

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        data = {
            'tokens_from_monitoring': tokens,
            'tokens_from_requests': self.captured_tokens,
            'requests': self.captured_requests,
        }

        file = self.output_dir / f"debug_session_{timestamp}.json"
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\n✓ 结果已保存: {file}")


async def main():
    print("🤖 Playwright + DevTools 辅助调试工具（轻量级）")
    print("\n改进:")
    print("  1. 移除了持续扫描，CPU 占用低")
    print("  2. 只在发送请求时监控")
    print("  3. 按需手动扫描")
    print("  4. 性能友好，不影响页面操作")
    print("\n准备开始吗？(按 Enter 继续，Ctrl+C 取消)")
    input()

    assistant = PlaywrightDevToolsAssistantLite(account_id=0)
    await assistant.assist_debugging()

    print("\n" + "=" * 80)
    print("🎉 调试会话结束")
    print("=" * 80)
    print("\n下一步:")
    print("  1. 如果找到了令牌，记录其来源")
    print("  2. 如果没找到，在 Console 中手动执行扫描")
    print("  3. 查看保存的 JSON 文件了解详情")


if __name__ == "__main__":
    asyncio.run(main())
