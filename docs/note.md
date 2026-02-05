# 备忘录

## 常用指令

选择模型：`select_menu_item item_selectors=['[data-test-id="bard-mode-option-思考"]'] menu_selectors=['[data-test-id="bard-mode-menu-button"]', 'button[aria-label*="Model"]', 'button[aria-label*="模型"]']`
选择工具：`select_menu_item item_selectors=["text=Create images", "text=生成图片"] menu_selectors=["button.toolbox-drawer-button",'button[aria-label="工具"]','button[aria-label="Tools"]']`
图片上传：`upload_image server/services/tasks/remove_watermark/bg_48.png`
自动同意弹窗：`handle_consent_popups`

click_submit selectors=['button.toolbox-drawer-item-list-button:has-text("Create images")','button.toolbox-drawer-item-list-button:has-text("生成图片")',"text=Create images", "text=生成图片"]


## 测试

```
docker compose exec gemini2api uv run tests/bulk_httpx.py --sample-size=1
docker compose exec gemini2api uv run python -c "import server.app"
```