from bs4 import BeautifulSoup
import re
from collections import Counter

with open("scripts/tmp.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "html.parser")

buttons = soup.find_all(lambda tag: tag.name == "button" or tag.get("role") == "button")
print("Top button classes/aria-labels:")
for b in buttons:
    label = b.get("aria-label", "")
    cls = " ".join(b.get("class", []))
    text = b.get_text(strip=True)[:20]
    
    if label and any(word in label.lower() for word in ["upload", "add", "tool", "image", "图片", "工具", "添加", "附件", "生图", "plus"]):
        print(f"Label: {label} | Class: {cls} | Text: {text}")

# specific search for '加号' matching anything around it
with open("scripts/tmp.html", "r", encoding="utf-8") as f:
    text = f.read()
    
matches = re.findall(r'aria-label="([^"]*加号[^"]*|[^"]*添加[^"]*|[^"]*上传[^"]*|[^"]*附件[^"]*)"', text, re.IGNORECASE)
print("\nPossible aria-labels for plus/add/upload:")
for m in set(matches):
    print(" -", m)
