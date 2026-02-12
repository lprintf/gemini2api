"""
Gemini 动作控制包
"""

# 1. 选择器与常量 (selectors.py)
# 存放所有的 CSS 选择器字典 (_SELECTORS) 和正则模式
from .selectors import _SELECTORS, _AVATAR_PATTERN

# 2. 基础原子动作 (base.py)
# 存放最底层的物理交互逻辑，如点击、文本填充、粘贴上传等
from .base import (
    click, 
    input_prompt, 
    select_menu_item, 
    upload_image, 
    get_uploaded_image_count
)

# 3. 业务组合逻辑 (business.py)
# 存放面向业务的复杂动作组合，如发送消息、切换模型、获取结果 URL、下载图片等
from .business import (
    start_new_chat,
    ensure_image_gen_active,
    set_model,
    upload_images_by_paste,
    click_submit,
    submit_image_prompt,
    wait_for_results,
    get_generated_urls,
    download_hd_image,
    download_q_image,
    download_generated_images
)

# 4. 页面环境准备 (environment.py)
# 存放跳转、同意弹窗处理、环境可用性预检、页面重置等逻辑
from .environment import (
    handle_consent_popups,
    prepare_environment,
    reinitialize_page
)

# 5. 调试与分析工具 (debug.py)
# 存放用于开发调试的工具，如 DOM 快照 (inspect)、HTML 导出、DOM 变动监听 (listen) 等
from .debug import (
    dump_inspect,
    dump_html,
    listen
)

# 统一导出接口
__all__ = [
    "_SELECTORS", "_AVATAR_PATTERN",
    "click", "input_prompt", "select_menu_item", "upload_image", "get_uploaded_image_count",
    "start_new_chat", "ensure_image_gen_active", "set_model", "upload_images_by_paste",
    "click_submit", "submit_image_prompt", "wait_for_results", "get_generated_urls",
    "download_hd_image", "download_q_image", "download_generated_images",
    "handle_consent_popups", "prepare_environment", "reinitialize_page",
    "dump_inspect", "dump_html", "listen"
]
