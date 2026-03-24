from bs4 import BeautifulSoup
import sys

def main():
    try:
        with open("scripts/tmp.html", "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
            
        print("Looking for model menu options...")
        
        # We will look for elements containing "Flash", "Fast", "快速", "Pro", "Advanced", "思考", "Thinking"
        keywords = ["Flash", "Fast", "快速", "Pro", "Advanced", "思考", "Thinking", "模型"]
        
        found = set()
        for tag in soup.find_all(True):
            if tag.name in ["script", "style", "html", "body", "head"]: continue
            text = tag.get_text(strip=True)
            if not text or len(text) > 100: continue
            
            if any(k in text for k in keywords):
                if hasattr(tag, "parent") and tag.parent:
                    # check if the parent is a menu list or has role
                    parents_roles = [p.get("role") for p in tag.parents if p and p.name != "body"]
                    if "menu" in parents_roles or "listbox" in parents_roles or "menuitem" in parents_roles or tag.get("role") in ["menuitem", "option", "menuitemradio"]:
                        found.add((tag.name, str(tag.get("class")), tag.get("role"), text[:20]))

        for item in sorted(found):
            print(f"Tag: {item[0]} | Class: {item[1]} | Role: {item[2]} | Text: {item[3]}")
            
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
