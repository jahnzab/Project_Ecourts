#!/usr/bin/env python3
"""
eCourts Website Inspector
Helps understand the actual structure of the eCourts portal
"""

import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from pathlib import Path

BASE_DIR = Path("ecourts_output")
BASE_DIR.mkdir(exist_ok=True)

def inspect_website():
    """Inspect the eCourts website structure"""
    
    print("\n" + "="*70)
    print("eCOURTS WEBSITE INSPECTOR")
    print("="*70 + "\n")
    
    # Initialize driver (visible browser)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)
    driver.maximize_window()
    
    try:
        # Load main page
        url = "https://services.ecourts.gov.in/ecourtindia_v6/"
        print(f"Loading: {url}\n")
        driver.get(url)
        time.sleep(8)
        
        # Page info
        print(f"Page Title: {driver.title}")
        print(f"Current URL: {driver.current_url}\n")
        
        # Save screenshot
        screenshot = BASE_DIR / "inspect_homepage.png"
        driver.save_screenshot(str(screenshot))
        print(f"✓ Screenshot saved: {screenshot}\n")
        
        # Find all links
        print("="*70)
        print("ALL LINKS ON PAGE:")
        print("="*70)
        
        all_links = driver.find_elements(By.TAG_NAME, "a")
        print(f"Total links found: {len(all_links)}\n")
        
        important_links = []
        for idx, link in enumerate(all_links, 1):
            try:
                text = link.text.strip()
                href = link.get_attribute('href') or 'no-href'
                
                # Filter important links
                keywords = ['cause', 'list', 'display', 'board', 'court', 'search', 'case']
                if text and any(kw in text.lower() for kw in keywords):
                    important_links.append({
                        'index': idx,
                        'text': text,
                        'href': href
                    })
                    print(f"{idx}. {text}")
                    print(f"   URL: {href}")
                    print()
            except:
                continue
        
        # Find all buttons/inputs
        print("="*70)
        print("ALL BUTTONS/INPUTS:")
        print("="*70)
        
        inputs = driver.find_elements(By.TAG_NAME, "input")
        buttons = driver.find_elements(By.TAG_NAME, "button")
        
        print(f"Inputs found: {len(inputs)}")
        print(f"Buttons found: {len(buttons)}\n")
        
        for idx, inp in enumerate(inputs[:20], 1):  # First 20
            try:
                inp_type = inp.get_attribute('type') or 'no-type'
                inp_id = inp.get_attribute('id') or 'no-id'
                inp_value = inp.get_attribute('value') or 'no-value'
                inp_name = inp.get_attribute('name') or 'no-name'
                
                if inp_type in ['submit', 'button'] or 'search' in inp_value.lower():
                    print(f"{idx}. Type: {inp_type}, ID: {inp_id}")
                    print(f"   Name: {inp_name}, Value: {inp_value}")
                    print()
            except:
                continue
        
        # Find all select elements
        print("="*70)
        print("ALL SELECT DROPDOWNS:")
        print("="*70)
        
        selects = driver.find_elements(By.TAG_NAME, "select")
        print(f"Select elements found: {len(selects)}\n")
        
        for idx, sel in enumerate(selects, 1):
            try:
                sel_id = sel.get_attribute('id') or 'no-id'
                sel_name = sel.get_attribute('name') or 'no-name'
                
                print(f"{idx}. ID: {sel_id}, Name: {sel_name}")
                
                options = sel.find_elements(By.TAG_NAME, "option")
                if len(options) <= 20:
                    print(f"   Options: {[opt.text.strip() for opt in options]}")
                else:
                    print(f"   Options: {len(options)} total (showing first 5)")
                    print(f"   {[opt.text.strip() for opt in options[:5]]}")
                print()
            except:
                continue
        
        # Interactive part
        print("="*70)
        print("INTERACTIVE INSPECTION")
        print("="*70)
        print("\nThe browser window is open. You can:")
        print("1. Manually navigate to the cause list page")
        print("2. Note the URL and steps taken")
        print("3. Check what dropdowns/forms appear")
        print("\nImportant links found:")
        for link in important_links[:10]:
            print(f"  [{link['index']}] {link['text']}")
        
        # Ask user to try clicking
        if important_links:
            print(f"\n\nWould you like to try clicking link #1? ({important_links[0]['text']})")
            response = input("Type 'yes' to try, or press Enter to skip: ")
            
            if response.lower() == 'yes':
                try:
                    print(f"\nClicking: {important_links[0]['text']}")
                    first_link = driver.find_element(By.LINK_TEXT, important_links[0]['text'])
                    first_link.click()
                    time.sleep(5)
                    
                    screenshot2 = BASE_DIR / "inspect_after_click.png"
                    driver.save_screenshot(str(screenshot2))
                    print(f"✓ Screenshot saved: {screenshot2}")
                    print(f"New URL: {driver.current_url}")
                    
                    # Check for selects again
                    new_selects = driver.find_elements(By.TAG_NAME, "select")
                    print(f"\nSelect elements on new page: {len(new_selects)}")
                    
                    for idx, sel in enumerate(new_selects, 1):
                        sel_id = sel.get_attribute('id') or 'no-id'
                        print(f"  {idx}. ID: {sel_id}")
                    
                except Exception as e:
                    print(f"Error clicking: {e}")
        
        print("\n" + "="*70)
        print("INSPECTION COMPLETE")
        print("="*70)
        print(f"\nCheck screenshots in: {BASE_DIR}/")
        print("\nPress Enter to close browser...")
        input()
        
    finally:
        driver.quit()
        print("\nBrowser closed.")


if __name__ == "__main__":
    inspect_website()