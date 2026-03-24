import json
from bs4 import BeautifulSoup

def main():
    with open("scripts/tmp.html", "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
        
    buttons = soup.find_all(lambda tag: tag.name == "button" or tag.get("role") == "button")
    
    results = []
    for b in buttons:
        label = b.get("aria-label", "")
        if not label: 
            label = ""
        cls = " ".join(b.get("class", []))
        test_id = b.get("data-test-id", "")
        # look for svg
        svg = b.find("svg")
        svg_info = "Yes" if svg else "No"
        
        # we only care about buttons that likely relate to input, tools, models
        # filter to keep output short
        if any(word in label.lower() for word in ["upload", "add", "tool", "image", "图片", "工具", "添加", "闪电", "fast", "生成", "plus", "model", "模型", "gemini", "menu", "菜单"]):
            results.append({
                "label": label,
                "class": cls,
                "test_id": test_id,
                "svg": svg_info
            })
            continue
            
        if "input" in cls or "menu" in cls or "mode" in cls or "drawer" in cls:
            results.append({
                "label": label,
                "class": cls,
                "test_id": test_id,
                "svg": svg_info
            })
            
    print(json.dumps(results[:50], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
