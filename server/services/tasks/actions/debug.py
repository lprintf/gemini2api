import asyncio
from typing import Any
from datetime import datetime
from playwright.async_api import Page
from server.utils.logger import tab_log, DATA_DIR

async def dump_inspect(page: Page, mode: str = "basic") -> bool:
    """[Debug] 分析并输出当前页面的交互元素清单"""
    is_full = str(mode).lower() in ["full", "all", "verbose", "1", "true"]
    
    script = """
    (full) => {
        const results = [];
        const baseSelector = 'button, a, input, [role="button"], [contenteditable="true"]';
        const fullSelector = baseSelector + ', h1, h2, h3, h4, h5, h6, p';
        const elements = document.querySelectorAll(full ? fullSelector : baseSelector);
        
        elements.forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== 'hidden') {
                const text = (el.innerText || el.value || "").trim().substring(0, 100).replace(/\\n/g, ' ');
                
                // 逻辑修正：如果是交互元素，哪怕没文字也要看；
                // 如果是展示元素（full模式下新增的），没文字才过滤。
                const isInteractive = ['BUTTON', 'A', 'INPUT'].includes(el.tagName) || 
                                     el.getAttribute('role') === 'button' || 
                                     el.getAttribute('contenteditable') === 'true';
                
                if (full && !isInteractive && !text) return;

                results.push({
                    tag: el.tagName,
                    text: text,
                    label: el.getAttribute('aria-label') || "",
                    selector: el.id ? `#${el.id}` : (el.className ? `.${el.className.split(' ').join('.')}` : '')
                });
            }
        });
        return results;
    }
    """
    try:
        elements = await page.evaluate(script, is_full)
        tab_log(page, f"--- Page Inspection ({'Full' if is_full else 'Basic'}, {len(elements)} elements) ---")
        for idx, el in enumerate(elements):
            msg = f"[{idx}] <{el['tag']}> Text: '{el['text']}'"
            if el['label']: msg += f" | Label: '{el['label']}'"
            if el['selector']: msg += f" | Sel: {el['selector']}"
            tab_log(page, msg)
        tab_log(page, "--- End of Inspection ---")
        return True
    except Exception as e:
        tab_log(page, f"Inspection failed: {e}", "error")
        return False

async def dump_html(page: Page) -> bool:
    """[Debug] 保存当前页面源码到 data/debug 目录"""
    try:
        html = await page.content()
        date_str = datetime.now().strftime("%Y%m%d")
        time_str = datetime.now().strftime("%H%M%S")
        
        debug_dir = DATA_DIR / "debug" / date_str
        debug_dir.mkdir(parents=True, exist_ok=True)
        file_path = debug_dir / f"{time_str}.html"
        file_path.write_text(html, encoding="utf-8")
        
        tab_log(page, f"HTML Source saved: {file_path}")
        return True
    except Exception as e:
        tab_log(page, f"Failed to save HTML: {e}", "error")
        return False

async def listen(page: Page, duration: Any = 30.0) -> bool:
    """[Debug] 开启当前页面监听（录像机模式）。记录 DOM 变动到日志。"""
    try:
        duration_val = float(duration)
    except:
        duration_val = 30.0

    def handle_console(msg):
        if msg.text.startswith("[DOM] "):
            tab_log(page, f"[Monitor] {msg.text[6:]}")

    setup_script = """
    (() => {
        if (window._dom_observer) return;
        const log = (m) => console.log("[DOM] " + m);
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((m) => {
                if (m.type === 'childList') {
                    m.addedNodes.forEach(node => {
                        if (node.nodeType === 1) {
                            const desc = `<${node.tagName}> ${node.className || ""}`.substring(0, 60);
                            const text = (node.innerText || node.textContent || "").trim().substring(0, 30);
                            if (text) log(`ADD: ${desc} | "${text}"`);
                        }
                    });
                } else if (m.type === 'characterData') {
                    const text = m.target.data.trim();
                    if (text.length > 2) log(`TEXT: "${text.substring(0, 50)}"`);
                }
            });
        });
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
        window._dom_observer = observer;
        console.log("[DOM] --- Listener Injected ---");
    })();
    """

    async def run_monitor():
        tab_log(page, f"--- Monitoring Current Page for {duration_val}s ---")
        page.on("console", handle_console)
        try:
            await page.evaluate(setup_script)
        except: pass
        await asyncio.sleep(duration_val)
        page.remove_listener("console", handle_console)
        await page.evaluate("() => { if(window._dom_observer) window._dom_observer.disconnect(); delete window._dom_observer; }")
        tab_log(page, f"--- Monitoring Finished ---")

    asyncio.create_task(run_monitor())
    return True
