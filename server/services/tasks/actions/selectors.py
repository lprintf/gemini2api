from typing import List

# =========================================================================
# 物理层定位符 (内部隐藏)
# =========================================================================

_SELECTORS = {
    "input_box": 'div[contenteditable="true"]',
    "submit_btns": [
        'button[aria-label*="发送"]',
        'button[aria-label*="Send"]',
        'button[aria-label*="submit"]',
        'button[data-test-id="send-button"]',
    ],
    "model_menu": [
        '[data-test-id="bard-mode-menu-button"]',
        'button.input-area-switch',
        'button[aria-label*="模式选择"]',
        'button[aria-label*="mode picker"]',
    ],
    "model_fast": [
        '[data-test-id="bard-mode-option-fast"]',
        '[data-test-id="bard-mode-option-快速"]',
        '[data-test-id="bard-mode-option-Flash"]',
        '.bard-mode-list-button:has-text("Flash")',
        '.bard-mode-list-button:text-is("Fast")',
        '.bard-mode-list-button:text-is("快速")',
        '.menu-option-container:has-text("Gemini Flash")',
        '.menu-option-container:text-is("Flash")',
        '.menu-option-container:text-is("Fast")',
        '.mat-mdc-menu-item:has-text("Gemini Flash")',
        '.mat-mdc-menu-item:text-is("Flash")',
        '.mat-mdc-menu-item:text-is("Fast")',
    ],
    "model_thinking": [
        '[data-test-id="bard-mode-option-thinking"]',
        '[data-test-id="bard-mode-option-思考"]',
        '[data-test-id="bard-mode-option-Thinking"]',
        '.bard-mode-list-button:has-text("Thinking Solves")',
        '.bard-mode-list-button:has-text("Thinking")',
        '.bard-mode-list-button:has-text("思考")',
        '.menu-option-container:has-text("Thinking Solves")',
        '.mat-mdc-menu-item:has-text("Thinking Solves")',
        '.mat-mdc-menu-item:has-text("Thinking")',
    ],
    "model_pro": [
        '[data-test-id="bard-mode-option-pro"]',
        '[data-test-id="bard-mode-option-Pro"]',
        '.bard-mode-list-button:has-text("Gemini Advanced")',
        '.bard-mode-list-button:has-text("Pro Advanced")',
        '.bard-mode-list-button:text-is("Pro")',
        '.menu-option-container:has-text("Gemini Advanced")',
        '.menu-option-container:has-text("Pro Advanced")',
        '.menu-option-container:text-is("Pro")',
        '.mat-mdc-menu-item:has-text("Gemini Advanced")',
        '.mat-mdc-menu-item:has-text("Pro Advanced")',
        '.mat-mdc-menu-item:text-is("Pro")',
    ],
    "tools_btn": [
        "button.toolbox-drawer-button",
        'button[aria-label="工具"]',
        'button[aria-label="Tools"]',
        'button[aria-label="toolbox"]',
    ],
    "image_gen_opt": [
        'button.toolbox-drawer-item-list-button:has-text("Image")',
        'button.toolbox-drawer-item-list-button:has-text("图片")',
        'button.toolbox-drawer-item-list-button:has-text("Images")',
        'button.toolbox-drawer-item-list-button:has-text("Create image")',
        'button.toolbox-drawer-item-list-button:has-text("Create images")',
        'button.toolbox-drawer-item-list-button:has-text("生成图片")',
        'button.toolbox-drawer-item-list-button:has-text("制作图片")',
    ],
    "image_gen_deselect": ".toolbox-drawer-item-deselect-button",
    "response_container": ["model-response", "response-container"],
    "download_btns": [
        'button[aria-label*="Download"]',
        'button[aria-label*="下载"]',
        'button[aria-label*="保存"]',
    ],
    "agree_btns": [
        'button:has-text("Agree")',
        'button:has-text("同意")',
        'button:has-text("OK")',
        '[role="dialog"] button[data-mdc-dialog-action="accept"]',
    ],
    "sign_in_btns": [
        'a[href*="accounts.google.com/ServiceLogin"]',
        'a:text-is("Sign in")', 
        'a:text-is("登录")',
        'button:text-is("Sign in")',
        'button:text-is("登录")',
        'button:text-is("登入")',
        'button[aria-label="Sign in"]',
        'button[aria-label="登录"]',
    ],
}

_AVATAR_PATTERN = "/a/ACg8oc"
