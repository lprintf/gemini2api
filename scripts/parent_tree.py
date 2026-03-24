import json
from bs4 import BeautifulSoup

def main():
    with open("scripts/tmp.html", "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
        
    btn = soup.find(lambda tag: tag.name == "button" and "menu-button" in tag.get("class", []))
    if not btn:
        print("Menu button not found!")
        return
        
    print("Found the menu-button:")
    print("Classes:", btn.get("class"))
    print("\nAncestors (bottom-up):")
    
    # print ancestors up to 5 levels
    for i, p in enumerate(btn.parents):
        if i > 7 or p.name == "body":
            break
        classes = " ".join(p.get("class", []))
        id_ = p.get("id", "")
        print(f"Level {i+1}: <{p.name} id='{id_}' class='{classes}'>")

if __name__ == "__main__":
    main()
