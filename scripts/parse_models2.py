from bs4 import BeautifulSoup

def main():
    try:
        with open("scripts/tmp.html", "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
            
        print("Looking for model options broadly...")
        keywords = ["Flash", "Fast", "快速", "Pro", "Advanced", "思考", "Thinking", "模型", "Gemini"]
        
        found = []
        for tag in soup.find_all(True):
            if tag.name in ["script", "style", "html", "body", "head"]: continue
            text = tag.get_text(strip=True)
            if not text or len(text) > 100: continue
            
            if any(k.lower() in text.lower() for k in keywords):
                classes = " ".join(tag.get("class", []))
                role = tag.get("role", "")
                found.append(f"<{tag.name} class='{classes}' role='{role}'>: {text[:40]}")

        for item in sorted(set(found)):
            print(item)
            
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
