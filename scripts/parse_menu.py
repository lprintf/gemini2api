from bs4 import BeautifulSoup
import json

def main():
    try:
        with open("scripts/tmp.html", "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
            
        print("Looking for image generation menu items...")
        menu_items = soup.find_all(lambda tag: "制作图片" in tag.get_text() or "Image" in tag.get_text() or "图片" in tag.get_text())
        
        for item in menu_items:
            # We want elements that look like clickable menu items, not the entire body or large containers
            if item.name in ["script", "style", "html", "body", "head"]: continue
            if len(item.get_text(strip=True)) > 50: continue # too much text means it's a wrapper
            
            print(f"\nTag: {item.name}")
            print(f"Classes: {item.get('class')}")
            print(f"Roles: {item.get('role')}")
            print(f"Text: {item.get_text(strip=True)}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
