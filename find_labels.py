import re
import json

with open("/wsp/gemini2api/scripts/tmp.html", "r", encoding="utf-8") as f:
    text = f.read()

# Find all tags with aria-label
print("Searching for specific keywords in aria-labels...")
labels = re.findall(r'aria-label="([^"]*)"', text)
keywords = ["add", "upload", "tool", "image", "图片", "工具", "添加", "闪电", "fast", "生成", "plus", "附件", "加号"]

found = []
for label in set(labels):
    if any(k in label.lower() for k in keywords):
        found.append(label)

for label in sorted(found):
    print(f" - {label}")
