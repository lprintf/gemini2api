# 备忘录

## 常用指令

选择模型：`select_menu_item item_selectors=['[data-test-id="bard-mode-option-思考"]'] menu_selectors=['[data-test-id="bard-mode-menu-button"]', 'button[aria-label*="Model"]', 'button[aria-label*="模型"]']`
选择工具：`select_menu_item item_selectors=['button.toolbox-drawer-item-list-button:has-text("Create images")','button.toolbox-drawer-item-list-button:has-text("生成图片")'] menu_selectors=["button.toolbox-drawer-button",'button[aria-label="工具"]','button[aria-label="Tools"]']`
图片上传：`upload_image server/services/tasks/remove_watermark/bg_48.png`
自动同意弹窗：`handle_consent_popups`
点击工具：`click selectors=['button.toolbox-drawer-item-list-button:has-text("Create images")','button.toolbox-drawer-item-list-button:has-text("生成图片")',"text=Create images", "text=生成图片"]`
发送消息：`submit`
提交：`generate prompt="make it ✨" image_paths=["server/services/tasks/remove_watermark/bg_48.png"]`
`submit_image_prompt prompt='这两张图那个大' image_paths=["server/services/tasks/remove_watermark/bg_48.png","server/services/tasks/remove_watermark/bg_96.png"]`
download_generated_images download_mode=hd

## 常用js
```
// 获取当前输入框中已物理存在的图片预览数量
(() => {
    const inputArea = document.querySelector('.input-area, .chat-input, [class*="input"]');
    const container = inputArea || document;
    const images = container.querySelectorAll('.image-preview, img[src*="blob:"]');
    return Array.from(images).length;
})()
```

## 测试

```
docker compose exec gemini2api uv run tests/bulk_httpx.py --sample-size=1
docker compose exec gemini2api uv run tests/test_hd.py 
docker compose exec gemini2api uv run python -c "import server.app"
```

## 维护

```
清除3天前上传的图片： find /data/gemini2api/data/uploads/ -type f -mtime +3 -delete
清除缓存： 
find /data/gemini2api/data/browser_data/*/Default/Cache/ -type f -delete
find /data/gemini2api/data/browser_data/*/Default/Code\ Cache/ -type f -delete
find /data/gemini2api/data/browser_data/*/Default/GPUCache/ -type f -delete
```