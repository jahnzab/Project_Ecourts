import argparse
import datetime
import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict
import cv2
import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, StaleElementReferenceException, WebDriverException
)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Optional OCR
try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# ---- Config ----
BASE_DIR = Path("ecourts_output")
BASE_DIR.mkdir(exist_ok=True)
LOG_FILE = BASE_DIR / "ecourts_run.log"
CAUSE_LIST_URL = "https://services.ecourts.gov.in/ecourtindia_v6/?p=cause_list/index"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ecourt")

# ---- Helper Functions ----
def human_delay(min_sec=0.6, max_sec=1.6):
    time.sleep(random.uniform(min_sec, max_sec))

def ensure_date_object(arg_when: str) -> datetime.date:
    arg = arg_when.lower()
    today = datetime.date.today()
    
    if arg == "today":
        return today
        
    if arg == "tomorrow":
        tomorrow = today + datetime.timedelta(days=1)
        max_allowed_date = today + datetime.timedelta(days=30)
        if tomorrow > max_allowed_date:
            return max_allowed_date
        return tomorrow
    
    try:
        parsed_date = datetime.datetime.strptime(arg_when, "%Y-%m-%d").date()
        max_allowed_date = today + datetime.timedelta(days=30)
        if parsed_date > max_allowed_date:
            return max_allowed_date
        return parsed_date
    except Exception:
        return today

def save_results(cases: List[Dict], filename_prefix: str):
    if not cases:
        logger.warning("No cases to save")
        return
    
    BASE_DIR.mkdir(exist_ok=True)
    
    csv_path = BASE_DIR / f"{filename_prefix}.csv"
    df = pd.DataFrame(cases)
    df.to_csv(csv_path, index=False, encoding='utf-8')
    
    json_path = BASE_DIR / f"{filename_prefix}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)
    
    return csv_path, json_path

def fetch_cause_list_from_html(html_file: str) -> List[Dict]:
    cases = []
    
    try:
        if not os.path.exists(html_file):
            return cases
            
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()

        soup = BeautifulSoup(html, 'html.parser')
        cases = extract_cases_from_soup(soup)
        
    except Exception:
        pass
    
    return cases

def looks_like_real_case(case_info: Dict) -> bool:
    return (
        case_info.get('serial', '').strip() and
        case_info.get('case_number', '').strip() and
        case_info.get('party_name', '').strip()
    )

def parse_table_rows(table) -> List[Dict]:
    cases = []
    rows = table.find_all('tr')
    
    current_case = None
    skip_headers = True
    
    for row_idx, row in enumerate(rows):
        cells = row.find_all('td')
        
        if not cells:
            continue
        
        cell_texts = [cell.get_text(strip=True) for cell in cells]
        
        if not any(cell_texts):
            continue
        
        if skip_headers and any('Sr No' in text or 'Cases' in text for text in cell_texts):
            skip_headers = False
            continue
        
        if len(cells) == 1:
            section_text = cell_texts[0]
            if section_text and not section_text[0].isdigit():
                if current_case and looks_like_real_case(current_case):
                    cases.append(current_case)
                current_case = None
                continue
        
        first_cell = cell_texts[0].strip()
        if first_cell and first_cell[0].isdigit():
            if current_case and looks_like_real_case(current_case):
                cases.append(current_case)
            
            serial = first_cell
            
            # FIXED: Get FULL case number without truncation
            case_number = cell_texts[1].strip() if len(cell_texts) > 1 else ""
            # Clean up the case number - remove extra whitespace and newlines
            case_number = ' '.join(case_number.split())
            
            # Format case number with line break before "Next hearing date"
            # This adds visual separation without removing the data
            if 'Next hearing date' in case_number:
                parts = case_number.split('Next hearing date')
                case_number = parts[0].strip() + '\n\n' + 'Next hearing date' + parts[1]
            
            party_name = cell_texts[2].strip() if len(cell_texts) > 2 else ""
            party_name = party_name.replace('\n', ' ').strip()
            party_name = party_name.replace('versus', ' versus ').replace('  ', ' ').strip()
            
            # Remove hearing date info if present in party name
            hearing_match = re.search(r'Next hearing date.*', party_name, re.IGNORECASE)
            if hearing_match:
                party_name = party_name[:hearing_match.start()].strip()
            
            advocate = cell_texts[3].strip() if len(cell_texts) > 3 else ""
            advocate = advocate.replace('\n', ' ').strip()
            
            current_case = {
                'serial': serial,
                'case_number': case_number,
                'party_name': party_name,
                'advocate': advocate
            }
    
    if current_case and looks_like_real_case(current_case):
        cases.append(current_case)
    
    return cases

def extract_cases_from_soup(soup: BeautifulSoup) -> List[Dict]:
    cases = []
    
    try:
        court_name = ""
        page_text = soup.get_text()
        
        lines = page_text.split('\n')
        for line in lines:
            line = line.strip()
            if 'Additional District' in line or 'District Judge' in line or 'Judge' in line:
                if line and not line.startswith('Select'):
                    court_name = line
                    break
        
        table = soup.find('table')
        if table:
            cases = parse_table_rows(table)
            
            for case in cases:
                case['court_name'] = court_name
                
    except Exception:
        pass
    
    return cases

def extract_cases_using_beautifulsoup(driver) -> List[Dict]:
    try:
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        output_dir = "ecourts_output"
        os.makedirs(output_dir, exist_ok=True)
        
        debug_file = os.path.join(output_dir, "debug_page.html")
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(html)
        
        cases = extract_cases_from_soup(soup)
        return cases
        
    except Exception:
        return []

# ---- WebDriver wrapper ----
class Browser:
    def __init__(self, headless: bool = False, download_dir: Optional[str] = None):
        chrome_options = webdriver.ChromeOptions()
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1600,1000")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
        
        if download_dir:
            download_path = os.path.abspath(download_dir)
            prefs = {
                "download.default_directory": download_path,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "plugins.always_open_pdf_externally": True,
                "safebrowsing.enabled": True,
                "profile.default_content_settings.popups": 0,
            }
            chrome_options.add_experimental_option("prefs", prefs)
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, 20)

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass

# ---- Cause List Scraper ----
class CauseListScraper:
    def __init__(self, browser: Browser, ocr_captcha: bool = False):
        self.browser = browser
        self.driver = browser.driver
        self.wait = browser.wait
        self.ocr_captcha = ocr_captcha and OCR_AVAILABLE

    def open_page(self):
        logger.info("Opening cause list page...")
        self.driver.get(CAUSE_LIST_URL)
        self.wait.until(EC.presence_of_element_located((By.ID, "sess_state_code")))
        human_delay(0.5, 1.0)

    def get_options_from_select(self, select_el) -> List[str]:
        try:
            options = []
            for opt in Select(select_el).options:
                if (opt.text.strip() and 
                    opt.text.strip().lower() not in ("select", "choose") and
                    opt.is_enabled()):
                    options.append(opt.text.strip())
            return options
        except Exception:
            return []

    def select_dropdown_value(self, select_by_tuple, value: str) -> bool:
        try:
            sel = self.wait.until(EC.presence_of_element_located(select_by_tuple))
            select_obj = Select(sel)
            select_obj.select_by_visible_text(value)
            human_delay(0.6, 1.2)
            return True
        except Exception:
            return False

    def wait_for_judge_dropdown(self) -> Optional[webdriver.remote.webelement.WebElement]:
        strategies = [
            (By.ID, "court_name_code"),
            (By.ID, "court_code"),
            (By.ID, "court_judge_code"),
            (By.ID, "judge_code"),
            (By.NAME, "court_code"),
            (By.NAME, "court_name_code"),
            (By.NAME, "judge_code"),
            (By.XPATH, "//select[contains(@id, 'court') and contains(@id,'name')]"),
            (By.XPATH, "//select[contains(@id, 'court') and contains(@id,'judge')]"),
            (By.XPATH, "//select[contains(@name,'judge') or contains(@name,'court_name') or contains(@name,'court')]"),
            (By.XPATH, "//select[not(@id='sess_state_code') and not(@id='sess_dist_code') and not(@id='court_complex_code')]"),
        ]
        
        for by, val in strategies:
            try:
                el = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((by, val)))
                try:
                    complex_el = self.driver.find_element(By.ID, "court_complex_code")
                    if el == complex_el:
                        continue
                except Exception:
                    pass
                
                options = self.get_options_from_select(el)
                if len(options) > 1:
                    logger.info("Found judge dropdown via %s %s with %d options", by, val, len(options))
                    return el
            except Exception:
                continue
        
        return None

    def select_judge(self, judge_name: str) -> bool:
        try:
            complex_el = self.driver.find_element(By.ID, "court_complex_code")
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", complex_el)
        except Exception:
            pass

        human_delay(0.6, 1.0)

        judge_el = None
        for attempt in range(5):
            judge_el = self.wait_for_judge_dropdown()
            if judge_el:
                break
            human_delay(0.6, 1.0)

        if not judge_el:
            return False

        opts = self.get_options_from_select(judge_el)
        if not opts:
            try:
                judge_el.click()
                human_delay(1.0, 2.0)
                opts = self.get_options_from_select(judge_el)
            except Exception:
                pass

        if not opts or len(opts) <= 1:
            return False

        try:
            select_obj = Select(judge_el)
            select_obj.select_by_visible_text(judge_name)
        except Exception:
            for i, opt in enumerate(select_obj.options):
                if opt.text.strip() == judge_name and opt.is_enabled():
                    select_obj.select_by_index(i)
                    break
            else:
                try:
                    self.driver.execute_script(f"""
                        var select = arguments[0];
                        for (var i = 0; i < select.options.length; i++) {{
                            if (select.options[i].text === '{judge_name}' && !select.options[i].disabled) {{
                                select.selectedIndex = i;
                                select.dispatchEvent(new Event('change', {{bubbles: true}}));
                                break;
                            }}
                        }}
                    """, judge_el)
                except Exception:
                    return False
        
        human_delay(0.6, 1.2)
        logger.info("Selected judge: %s", judge_name)
        return True

    def set_date_mmddyyyy(self, date_obj: datetime.date) -> bool:
        today = datetime.date.today()
        max_allowed_date = today + datetime.timedelta(days=30)
        
        if date_obj > max_allowed_date:
            date_obj = max_allowed_date
        
        date_str_ddmmyyyy = date_obj.strftime("%d-%m-%Y")
        date_str_mmddyyyy = date_obj.strftime("%m-%d-%Y")
        
        date_selectors = [
            (By.ID, "cause_list_date"),
            (By.NAME, "cause_list_date"), 
            (By.ID, "hearing_date"),
            (By.NAME, "hearing_date"),
            (By.XPATH, "//input[contains(@id,'date')]"),
            (By.XPATH, "//input[contains(@name,'date')]"),
            (By.XPATH, "//input[@type='date']"),
        ]
        
        for by, selector in date_selectors:
            try:
                date_input = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, selector))
                )
                
                date_input.clear()
                human_delay(0.5, 1.0)
                date_input.send_keys(date_str_ddmmyyyy)
                human_delay(1.0, 1.5)
                
                actual_value = date_input.get_attribute('value')
                if actual_value:
                    return True
                    
            except Exception:
                continue
        
        for by, selector in date_selectors:
            try:
                date_input = WebDriverWait(self.driver, 3).until(
                    EC.presence_of_element_located((by, selector))
                )
                
                date_input.clear()
                human_delay(0.5, 1.0)
                date_input.send_keys(date_str_mmddyyyy)
                human_delay(1.0, 1.5)
                
                actual_value = date_input.get_attribute('value')
                if actual_value:
                    return True
                    
            except Exception:
                continue
        
        return False

    def click_case_type_button(self, case_type: str) -> bool:
        type_mapping = {
            "Civil": "civ",
            "Criminal": "cri"
        }
        
        onclick_value = type_mapping.get(case_type, "")
        
        button_selectors = [
            (By.XPATH, f"//button[@class='btn btn-primary' and contains(@onclick, '{onclick_value}')]"),
            (By.XPATH, f"//button[contains(@onclick, 'submit_causelist') and contains(@onclick, '{onclick_value}')]"),
            (By.XPATH, f"//button[contains(text(), '{case_type}') and contains(@onclick, 'submit_causelist')]"),
            (By.XPATH, f"//button[contains(text(), '{case_type}')]"),
            (By.XPATH, f"//input[@value='{case_type}']"),
        ]
        
        for by, selector in button_selectors:
            try:
                button = self.driver.find_element(by, selector)
                if button.is_displayed() and button.is_enabled():
                    try:
                        button.click()
                        return True
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", button)
                        return True
            except Exception:
                continue
        
        return False

    def _check_case_type_success(self, case_type: str) -> bool:
        if self.check_for_popup_errors():
            return False
        
        current_url = self.driver.current_url
        if "cause_list/index" not in current_url:
            return True
        
        if self.has_cause_list_content():
            return True
        
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            if (case_type.lower() in page_text and 
                any(keyword in page_text for keyword in ['case', 'cause list', 'viewos', 'viewas', 'dispTable'])):
                return True
        except Exception:
            pass
        
        try:
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            for table in tables:
                if table.is_displayed():
                    table_text = table.text.lower()
                    if any(term in table_text for term in ['case no', 'sr.no', 'party', 'advocate']):
                        return True
        except Exception:
            pass
        
        return False

    def select_case_type_auto(self) -> str:
        original_url = self.driver.current_url
        
        civil_clicked = self.click_case_type_button("Civil")
        
        if civil_clicked:
            human_delay(4.0, 6.0)
            
            if self._check_case_type_success("Civil"):
                return "Civil"
            else:
                current_url = self.driver.current_url
                if current_url == original_url:
                    pass
                else:
                    pass
                
                try:
                    self.driver.back()
                    human_delay(3.0, 5.0)
                except:
                    self.driver.get(original_url)
                    human_delay(3.0, 5.0)
        
        criminal_clicked = self.click_case_type_button("Criminal")
        
        if criminal_clicked:
            human_delay(4.0, 6.0)
            
            if self._check_case_type_success("Criminal"):
                return "Criminal"
        
        return "Civil"

    def has_cause_list_content(self) -> bool:
        try:
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            for table in tables:
                if table.is_displayed():
                    table_text = table.text.lower()
                    if any(keyword in table_text for keyword in ['case', 'party', 'advocate', 'viewos', 'viewas', 'os/', 'as/']):
                        return True
            
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            case_indicators = [
                'viewos/', 'viewas/', 'os/', 'as/', 'case no', 'case number',
                'sr.no', 'serial no', 'advocate', 'petitioner', 'respondent'
            ]
            
            for indicator in case_indicators:
                if indicator in page_text:
                    return True
                    
        except Exception:
            pass
        
        return False

    def check_for_popup_errors(self) -> bool:
        try:
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text.lower()
                
                if "selection valid upto one month" in alert_text or "1 month" in alert_text:
                    alert.accept()
                    return True
                    
                alert.dismiss()
                return True
            except:
                pass
            
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            
            error_messages = [
                "selection valid upto one month",
                "selection only upto 1 month allowed", 
                "invalid date",
                "date range exceeded",
                "maximum 1 month",
                "date should be within",
                "please select date within"
            ]
            
            for error_msg in error_messages:
                if error_msg in page_text:
                    return True
                    
        except Exception:
            pass
        
        return False

    def solve_captcha_ocr(self, captcha_element) -> Optional[str]:
        if not OCR_AVAILABLE:
            return None

        try:
            from PIL import Image, ImageEnhance, ImageFilter
            import io, base64
            import numpy as np
            import cv2

            src = captcha_element.get_attribute('src')
            if src and src.startswith('data:image'):
                base64_data = src.split(',')[1]
                image_data = base64.b64decode(base64_data)
                image = Image.open(io.BytesIO(image_data))
            else:
                screenshot = captcha_element.screenshot_as_png
                image = Image.open(io.BytesIO(screenshot))

            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            pil_img = Image.fromarray(gray)
            pil_img = ImageEnhance.Contrast(pil_img).enhance(2.0)
            pil_img = ImageEnhance.Sharpness(pil_img).enhance(2.0)
            gray = np.array(pil_img)

            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

            blur = cv2.medianBlur(gray, 3)
            _, thresh_otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            thresh_adapt = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                 cv2.THRESH_BINARY, 11, 2)
            kernel = np.ones((2,2), np.uint8)
            for thresh in [thresh_otsu, thresh_adapt]:
                thresh = cv2.dilate(thresh, kernel, iterations=1)
                thresh = cv2.erode(thresh, kernel, iterations=1)

                image_proc = Image.fromarray(thresh)
                for psm in [7, 8]:
                    custom_config = f'--oem 3 --psm {psm} -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyz0123456789'
                    captcha_text = pytesseract.image_to_string(image_proc, config=custom_config)
                    captcha_text = ''.join(c for c in captcha_text if c.isalnum()).strip().lower()
                    if len(captcha_text) == 6:
                        return captcha_text

            self.refresh_captcha()
            return None

        except Exception:
            return None

    def refresh_captcha(self) -> bool:
        try:
            refresh_selectors = [
                (By.XPATH, "//a[contains(@onclick,'refreshCaptcha')]"),
                (By.XPATH, "//a[contains(text(),'Refresh')]"),
                (By.XPATH, "//button[contains(text(),'Refresh')]"),
                (By.XPATH, "//img[contains(@onclick,'refresh')]/parent::a")
            ]
            for by, selector in refresh_selectors:
                try:
                    btn = self.driver.find_element(by, selector)
                    if btn.is_displayed() and btn.is_enabled():
                        btn.click()
                        human_delay(2, 4)
                        return True
                except:
                    continue
            return False
        except Exception:
            return False
    def captcha_web_wait(self, max_attempts: int = 4) -> bool:
        """
        CAPTCHA handler for Flask web interface.
        
        Waits for user to:
        1. Manually solve CAPTCHA in browser
        2. Click Civil or Criminal button
        
        Does NOT require terminal input - detects button click automatically.
        Returns True when form is submitted and page changes.
        """
        print("⏳ CAPTCHA Web Wait - Waiting for user interaction...")
        print("   You have up to 4 attempts")
        print("   Page will auto-detect when you click Civil/Criminal button\n")
        
        for attempt in range(1, max_attempts + 1):
            print(f"   Attempt {attempt}/{max_attempts}")
            
            # Wait for CAPTCHA image to appear
            captcha_elem = None
            captcha_selectors = [
                (By.XPATH, "//img[contains(@src,'captcha')]"),
                (By.XPATH, "//img[contains(@id,'captcha')]"),
                (By.XPATH, "//img[contains(@class,'captcha')]"),
                (By.XPATH, "//img[@id='captchaImage']"),
                (By.XPATH, "//img[contains(@alt,'captcha')]"),
            ]
            
            # Give user time to see the CAPTCHA
            human_delay(2, 3)
            
            for by, sel in captcha_selectors:
                try:
                    elems = self.driver.find_elements(by, sel)
                    for elem in elems:
                        if elem.is_displayed():
                            captcha_elem = elem
                            print("   ✅ CAPTCHA image detected in browser")
                            break
                    if captcha_elem:
                        break
                except:
                    continue

            if not captcha_elem:
                print("   ❌ CAPTCHA not found, retrying...")
                human_delay(2, 3)
                continue

            # Try OCR to auto-solve (optional, user can enter manually)
            print("   🔍 Attempting OCR solve (optional - you can also enter manually)...")
            captcha_text = self.solve_captcha_ocr(captcha_elem)
            
            if captcha_text:
                print(f"   ✅ OCR solved: {captcha_text}")
                
                # Try to enter it
                inp = None
                input_selectors = [
                    (By.ID, "cause_list_captcha_code"),
                    (By.NAME, "cause_list_captcha_code"),
                    (By.XPATH, "//input[contains(@placeholder,'Captcha')]"),
                    (By.XPATH, "//input[@aria-label='Enter Captcha']"),
                ]
                
                for by, sel in input_selectors:
                    try:
                        inp = self.driver.find_element(by, sel)
                        if inp.is_displayed():
                            inp.clear()
                            human_delay(0.5, 1.0)
                            inp.send_keys(captcha_text)
                            print(f"   ✅ CAPTCHA entered: {captcha_text}")
                            break
                    except:
                        continue
            else:
                print("   ⏳ OCR failed - waiting for manual entry...")
            
            # Now wait for user to click Civil or Criminal button
            # This is the critical part - we monitor the page for changes
            print("   ⏳ Waiting for you to click CIVIL or CRIMINAL button...")
            print("   Monitoring for page change...")
            
            original_url = self.driver.current_url
            original_title = self.driver.title
            
            # Wait up to 2 minutes for button click
            wait_start = time.time()
            max_wait = 120  # 2 minutes
            
            while time.time() - wait_start < max_wait:
                human_delay(1, 2)  # Check every 1-2 seconds
                
                try:
                    # Check if page content changed (button was clicked)
                    current_title = self.driver.title
                    current_url = self.driver.current_url
                    page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                    
                    # Indicators that button was clicked and form submitted
                    success_indicators = [
                        "principal district judge",
                        "civil cases listed",
                        "criminal cases listed",
                        "sr no", "case number", "party name", "advocate",
                        "record not found", "urgent cases", "awaited",
                        "viewos/", "viewas/"
                    ]
                    
                    indicator_count = sum(1 for ind in success_indicators if ind in page_text)
                    
                    if indicator_count >= 2:
                        print(f"   ✅ SUCCESS! Results page detected")
                        print(f"   Page content: {indicator_count} success indicators found")
                        return True
                    
                    # Also check for any visible table with cases
                    tables = self.driver.find_elements(By.TAG_NAME, "table")
                    for table in tables:
                        if table.is_displayed():
                            table_text = table.text.lower()
                            if any(term in table_text for term in ['case', 'party', 'advocate']):
                                print(f"   ✅ SUCCESS! Results table detected")
                                return True
                    
                    # Check for error messages
                    error_checks = [
                        "//div[@class='alert alert-danger']",
                        "//div[contains(text(),'Invalid Captcha')]",
                        "//span[contains(text(),'Invalid')]"
                    ]
                    
                    for xpath in error_checks:
                        try:
                            error_elem = self.driver.find_element(By.XPATH, xpath)
                            if error_elem.is_displayed():
                                print(f"   ❌ Error detected: {error_elem.text[:50]}")
                                print(f"   Refreshing CAPTCHA for retry...")
                                self.refresh_captcha()
                                break
                        except:
                            pass
                
                except Exception as e:
                    print(f"   ⚠️ Check error (continuing): {str(e)[:50]}")
                    continue
            
            print(f"   ⏱️  Timeout after 2 minutes - CAPTCHA button not clicked")
            print(f"   Please try again manually")
        
        print("❌ CAPTCHA web wait failed after all attempts")
        return False

    def captcha_hybrid_solve(self, max_attempts: int = 4) -> tuple:
        """
        HYBRID CAPTCHA SOLVER for Flask:
        
        1. Auto-solves CAPTCHA using OCR
        2. Enters solved code automatically
        3. WAITS for user to select Civil/Criminal in Flask
        4. Clicks the selected button
        5. Validates the result
        
        Returns:
            (success: bool, case_type: str)
            - success: True if CAPTCHA validated
            - case_type: "Civil" or "Criminal" (or "Unknown" if validation failed)
        """
        print("🔐 CAPTCHA HYBRID SOLVE - Auto OCR + Manual Case Type Selection\n")
        
        for attempt in range(1, max_attempts + 1):
            print(f"Attempt {attempt}/{max_attempts}")
            
            # STEP 1: Find CAPTCHA image
            print("  1️⃣ Finding CAPTCHA image...")
            captcha_elem = None
            captcha_selectors = [
                (By.XPATH, "//img[contains(@src,'captcha')]"),
                (By.XPATH, "//img[contains(@id,'captcha')]"),
                (By.XPATH, "//img[contains(@class,'captcha')]"),
                (By.XPATH, "//img[@id='captchaImage']"),
                (By.XPATH, "//img[contains(@alt,'captcha')]"),
            ]
            
            for by, sel in captcha_selectors:
                try:
                    elems = self.driver.find_elements(by, sel)
                    for elem in elems:
                        if elem.is_displayed():
                            captcha_elem = elem
                            break
                    if captcha_elem:
                        break
                except:
                    continue
            
            if not captcha_elem:
                print("  ❌ CAPTCHA image not found")
                self.refresh_captcha()
                human_delay(2, 3)
                continue
            
            print("  ✅ CAPTCHA image found")
            
            # STEP 2: Solve CAPTCHA with OCR
            print("  2️⃣ Solving CAPTCHA with OCR...")
            captcha_text = self.solve_captcha_ocr(captcha_elem)
            
            if not captcha_text:
                print("  ❌ OCR failed to solve CAPTCHA")
                self.refresh_captcha()
                human_delay(2, 3)
                continue
            
            print(f"  ✅ OCR solved: {captcha_text}")
            
            # STEP 3: Enter CAPTCHA code
            print("  3️⃣ Entering CAPTCHA code...")
            inp = None
            input_selectors = [
                (By.ID, "cause_list_captcha_code"),
                (By.NAME, "cause_list_captcha_code"),
                (By.XPATH, "//input[contains(@placeholder,'Captcha')]"),
                (By.XPATH, "//input[@aria-label='Enter Captcha']"),
            ]
            
            for by, sel in input_selectors:
                try:
                    inp = self.driver.find_element(by, sel)
                    if inp.is_displayed():
                        inp.clear()
                        human_delay(0.3, 0.6)
                        inp.send_keys(captcha_text)
                        print(f"  ✅ CAPTCHA code entered")
                        break
                except:
                    continue
            
            if not inp:
                print("  ❌ CAPTCHA input field not found")
                continue
            
            # STEP 4: Wait for user to select Civil/Criminal in Flask and return the choice
            print("  4️⃣ Waiting for case type selection in Flask (max 3 minutes)...")
            print("     → Flask will show CIVIL and CRIMINAL buttons")
            
            # Return special marker indicating we're ready for user selection
            # The calling code will wait for scraping_session.selected_case_type
            return (True, "WAITING_FOR_FLASK_SELECTION")
        
        print("❌ CAPTCHA hybrid solve failed after all attempts")
        return (False, "FAILED")
    
    def captcha_hybrid_click_and_validate(self, case_type: str) -> bool:
        """
        PART 2 of hybrid CAPTCHA solving:
        
        After user selects Civil/Criminal in Flask, this clicks the button
        and validates the result.
        
        Args:
            case_type: "Civil" or "Criminal" (from user selection in Flask)
        
        Returns:
            True if CAPTCHA validated and results page loaded
        """
        print(f"  5️⃣ Clicking {case_type} button (user selected via Flask)...")
        
        # Click the button
        if not self.click_case_type_button(case_type):
            print(f"  ❌ Failed to click {case_type} button")
            return False
        
        print(f"  ✅ {case_type} button clicked")
        
        # Wait for page to load
        print("  6️⃣ Waiting for results page...")
        human_delay(4, 6)
        
        # Validate CAPTCHA
        print("  7️⃣ Validating CAPTCHA submission...")
        if self.check_captcha_validation():
            print(f"  ✅ CAPTCHA validated! Results page loaded")
            return True
        else:
            print(f"  ❌ CAPTCHA validation failed")
            return False
    def captcha_web_wait_simple(self, timeout: int = 180) -> bool:
        """
        Simplified CAPTCHA wait for Flask - just monitors page changes.
        
        Works best when:
        - User manually solves CAPTCHA and clicks button
        - Page auto-submits form
        
        Args:
            timeout: Maximum seconds to wait (default 3 minutes)
        
        Returns:
            True if results page detected, False on timeout/error
        """
        print("\n" + "="*60)
        print("CAPTCHA SUBMISSION WAITING")
        print("="*60)
        print("1. CAPTCHA is visible in your browser")
        print("2. Solve it and enter the code (if not auto-filled)")
        print("3. Click CIVIL or CRIMINAL button")
        print("4. System will auto-detect when you're done")
        print("="*60 + "\n")
        
        start_time = time.time()
        check_count = 0
        
        while time.time() - start_time < timeout:
            check_count += 1
            elapsed = int(time.time() - start_time)
            
            try:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                
                # Success indicators - results page loaded
                success_keywords = [
                    ("principal district judge", "judge info"),
                    ("civil cases listed", "civil header"),
                    ("criminal cases listed", "criminal header"),
                    ("sr no", "table header"),
                    ("case number", "case column"),
                    ("party name", "party column"),
                    ("record not found", "empty results"),
                ]
                
                matches = []
                for keyword, desc in success_keywords:
                    if keyword in page_text:
                        matches.append(desc)
                
                if len(matches) >= 2:
                    print(f"✅ SUCCESS! ({elapsed}s elapsed)")
                    print(f"   Detected: {', '.join(matches)}")
                    return True
                
                # Check for visible results table
                try:
                    tables = self.driver.find_elements(By.TAG_NAME, "table")
                    for table in tables:
                        if table.is_displayed():
                            rows = table.find_elements(By.TAG_NAME, "tr")
                            if len(rows) > 1:
                                print(f"✅ SUCCESS! ({elapsed}s elapsed)")
                                print(f"   Results table with {len(rows)} rows detected")
                                return True
                except:
                    pass
                
                # Check for error
                error_indicators = [
                    "invalid captcha",
                    "captcha failed",
                    "incorrect",
                ]
                
                for error in error_indicators:
                    if error in page_text:
                        print(f"❌ Error detected: {error}")
                        return False
                
                # Print status every 10 seconds
                if check_count % 10 == 0:
                    print(f"⏳ Waiting... ({elapsed}s/{timeout}s)")
                
                # Check every 500ms
                human_delay(0.5, 1.0)
                
            except Exception as e:
                print(f"⚠️  Error during check: {str(e)[:50]}")
                human_delay(1, 2)
                continue
        
        print(f"❌ TIMEOUT after {timeout}s - No results page detected")
        print("   Please check if button was clicked correctly")
        return False
    def captcha_auto_solve(self, max_attempts: int = 6) -> bool:
        for attempt in range(1, max_attempts + 1):
            human_delay(2, 4)

            captcha_elem = None
            selectors = [
                (By.XPATH, "//img[contains(@src,'captcha')]"),
                (By.XPATH, "//img[contains(@id,'captcha')]"),
                (By.XPATH, "//img[contains(@class,'captcha')]"),
                (By.XPATH, "//img[@id='captchaImage']"),
                (By.XPATH, "//img[contains(@alt,'captcha')]"),
            ]
            
            for by, sel in selectors:
                try:
                    elems = self.driver.find_elements(by, sel)
                    for elem in elems:
                        if elem.is_displayed():
                            captcha_elem = elem
                            break
                    if captcha_elem:
                        break
                except:
                    continue

            if not captcha_elem:
                self.refresh_captcha()
                continue

            captcha_text = self.solve_captcha_ocr(captcha_elem)
            if not captcha_text:
                self.refresh_captcha()
                continue

            inp = None
            input_selectors = [
                (By.ID, "cause_list_captcha_code"),
                (By.NAME, "cause_list_captcha_code"),
                (By.XPATH, "//input[contains(@placeholder,'Captcha')]"),
                (By.XPATH, "//input[@aria-label='Enter Captcha']"),
            ]
            
            for by, sel in input_selectors:
                try:
                    inp = self.driver.find_element(by, sel)
                    if inp.is_displayed():
                        break
                except:
                    continue
            
            if not inp:
                continue

            try:
                inp.clear()
                human_delay(0.3, 0.6)
                inp.send_keys(captcha_text)
            except Exception:
                continue

            case_type = "Civil"
            try:
                btn = self.driver.find_element(By.XPATH, f"//button[contains(text(),'{case_type}')]")
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                else:
                    continue
            except Exception:
                continue

            human_delay(3, 5)

            if self.check_captcha_validation():
                return True
            else:
                self.refresh_captcha()

        return False
    
    def check_captcha_validation(self) -> bool:
        try:
            human_delay(2, 3)
            
            failure_indicators = [
                ("//div[@class='alert alert-danger']", "alert-danger"),
                ("//div[contains(@class,'alert') and contains(text(),'Invalid')]", "Invalid alert"),
                ("//span[contains(text(),'Invalid Captcha')]", "Invalid Captcha text"),
                ("//div[@role='alert' and contains(text(),'invalid')]", "role alert"),
            ]
            
            for xpath, desc in failure_indicators:
                try:
                    elems = self.driver.find_elements(By.XPATH, xpath)
                    for elem in elems:
                        if elem.is_displayed():
                            return False
                except:
                    pass
            
            captcha_inputs = [
                (By.ID, "cause_list_captcha_code"),
                (By.NAME, "cause_list_captcha_code"),
                (By.XPATH, "//input[contains(@placeholder,'Captcha')]"),
                (By.XPATH, "//input[@aria-label='Enter Captcha']"),
            ]
            
            for by, sel in captcha_inputs:
                try:
                    input_elems = self.driver.find_elements(by, sel)
                    for inp in input_elems:
                        if inp.is_displayed():
                            value = inp.get_attribute('value')
                            if value and len(value.strip()) > 0:
                                return False
                except:
                    pass
            
            success_selectors = [
                ("//table[contains(@class,'table')]", "data table"),
                ("//div[contains(text(),'Sr No')]", "table header"),
                ("//th[contains(text(),'Cases')]", "Cases column"),
                ("//th[contains(text(),'Party Name')]", "Party Name column"),
                ("//div[contains(text(),'Principal District Judge')]", "judge info"),
                ("//div[contains(text(),'Civil Cases Listed')]", "civil cases info"),
                ("//tbody/tr", "table rows"),
            ]
            
            for xpath, desc in success_selectors:
                try:
                    elems = self.driver.find_elements(By.XPATH, xpath)
                    if elems and any(e.is_displayed() for e in elems):
                        return True
                except:
                    pass
            
            try:
                record_not_found = self.driver.find_element(By.XPATH, "//div[contains(text(),'Record not found')]")
                if record_not_found.is_displayed():
                    return True
            except:
                pass
            
            body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            success_keywords = [
                "principal district judge",
                "civil cases listed",
                "sr no", "cases", "party name", "advocate",
                "record not found",
                "urgent cases", "awaited"
            ]
            
            keyword_count = sum(1 for kw in success_keywords if kw in body_text)
            if keyword_count >= 2:
                return True
            
            current_url = self.driver.current_url.lower()
            if "cause_list" in current_url and "index" in current_url:
                return True
            
            return False
            
        except Exception:
            return False

    def extract_cases_using_beautifulsoup(self) -> List[Dict]:
        try:
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            debug_file = BASE_DIR / "debug_page.html"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(html)
            
            cases = extract_cases_from_soup(soup)
            
            if not cases:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                cases = self.parse_cases_from_text(page_text)
            
            return cases
            
        except Exception:
            return []

    def parse_cases_from_text(self, text: str) -> List[Dict]:
        cases = []
        lines = text.split('\n')
        
        current_case = {}
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            serial_match = re.match(r'^(\d+)\.?\s*$', line)
            if serial_match and not current_case:
                current_case = {'serial': serial_match.group(1)}
                i += 1
                continue
            
            case_match = re.search(r'(View)?(OS|AS|ARBTN|CS)/\d+/\d+', line, re.IGNORECASE)
            if case_match and current_case and 'case_number' not in current_case:
                current_case['case_number'] = line.strip()
                i += 1
                continue
            
            if 'versus' in line.lower() and current_case and 'parties' not in current_case:
                current_case['parties'] = line.strip()
                i += 1
                continue
            
            if (current_case and 'parties' in current_case and 'advocate' not in current_case and
                line and len(line.split()) <= 4 and not line.isdigit()):
                current_case['advocate'] = line.strip()
                i += 1
                continue
            
            if current_case and 'case_number' in current_case and 'parties' in current_case:
                if looks_like_real_case(current_case):
                    cases.append(current_case)
                current_case = {}
            
            i += 1
        
        if current_case and 'case_number' in current_case and 'parties' in current_case:
            if looks_like_real_case(current_case):
                cases.append(current_case)
        
        return cases

    def fetch_cause_list_live(self, state: str, district: str, court_complex: str, judge: str, date_obj: datetime.date) -> List[Dict]:
        self.open_page()
        
        if not self.select_dropdown_value((By.ID, "sess_state_code"), state):
            raise RuntimeError("State selection failed")
        
        human_delay(2.0, 3.0)
            
        if not self.select_dropdown_value((By.ID, "sess_dist_code"), district):
            raise RuntimeError("District selection failed")
        
        human_delay(2.0, 3.0)
            
        if not self.select_dropdown_value((By.ID, "court_complex_code"), court_complex):
            raise RuntimeError("Court complex selection failed")

        human_delay(2.0, 3.0)

        if not self.select_judge(judge):
            raise RuntimeError("Judge selection failed")

        human_delay(1.0, 2.0)

        today = datetime.date.today()
        max_allowed_date = today + datetime.timedelta(days=30)
        
        if date_obj > max_allowed_date:
            date_obj = max_allowed_date
    
        if not self.set_date_mmddyyyy(date_obj):
            date_obj = datetime.date.today()
            if not self.set_date_mmddyyyy(date_obj):
                raise RuntimeError("Date setting failed")

        human_delay(1.0, 2.0)
        
        if not self.captcha_auto_solve(max_attempts=8):
            raise RuntimeError("CAPTCHA failed")

        human_delay(1.0, 2.0)

        case_type = self.select_case_type_auto()

        if case_type in ["DateError", "FormPage"]:
            return []

        human_delay(5.0, 8.0)

        cases = self.extract_cases_using_beautifulsoup()
        
        if case_type == "Unknown":
            case_type_from_cases = self.determine_case_type_from_cases(cases)
            if case_type_from_cases != "Unknown":
                case_type = case_type_from_cases
        
        for case in cases:
            case['court_name'] = judge
            case['date'] = date_obj.strftime("%Y-%m-%d")
            case['case_type'] = case_type
            case['district'] = district
        
        return cases

    def determine_case_type_from_cases(self, cases: List[Dict]) -> str:
        if not cases:
            return "Unknown"
        
        civil_indicators = [
            "original suits", "os/", "civil suit", "civil application", 
            "execution", "declaration", "recovery", "succession", "misc. civil"
        ]
        
        criminal_indicators = [
            "criminal appeal", "criminal revision", "bail application", 
            "fir", "police case", "criminal complaint"
        ]
        
        civil_count = 0
        criminal_count = 0
        
        for case in cases:
            case_number = case.get('case_number', '').lower()
            
            for indicator in civil_indicators:
                if indicator in case_number:
                    civil_count += 1
                    break
            
            for indicator in criminal_indicators:
                if indicator in case_number:
                    criminal_count += 1
                    break
        
        if civil_count > criminal_count:
            return "Civil"
        elif criminal_count > civil_count:
            return "Criminal"
        else:
            return "Unknown"


# def generate_pdf_from_cases(cases: List[Dict], output_filename: str, court_name: str, date: str, case_type: str, state: str = '', district: str = '', court_complex: str = '', available_judges: List[str] = None):
#     try:
#         from reportlab.lib.pagesizes import A4, landscape
#         from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
#         from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
#         from reportlab.lib import colors
#         from reportlab.lib.units import inch
        
#         output_path = BASE_DIR / output_filename
        
#         # Use landscape for better width
#         doc = SimpleDocTemplate(
#             str(output_path),
#             pagesize=landscape(A4),
#             topMargin=0.4*inch,
#             bottomMargin=0.4*inch,
#             leftMargin=0.3*inch,
#             rightMargin=0.3*inch
#         )
        
#         story = []
#         styles = getSampleStyleSheet()
        
#         # Main title
#         title_style = ParagraphStyle(
#             'CustomTitle',
#             parent=styles['Heading1'],
#             fontSize=16,
#             spaceAfter=15,
#             alignment=1,
#             textColor=colors.HexColor('#003366')
#         )
        
#         title_text = "CAUSE LIST"
#         story.append(Paragraph(title_text, title_style))
#         story.append(Spacer(1, 0.1*inch))
        
#         # Blue Header Box with State, District, Court Complex
#         header_label_style = ParagraphStyle(
#             'HeaderLabel',
#             parent=styles['Normal'],
#             fontSize=10,
#             fontName='Helvetica-Bold',
#             textColor=colors.whitesmoke,
#             alignment=1,
#             leading=12
#         )
        
#         header_value_style = ParagraphStyle(
#             'HeaderValue',
#             parent=styles['Normal'],
#             fontSize=9,
#             fontName='Helvetica',
#             textColor=colors.whitesmoke,
#             alignment=1,
#             leading=11
#         )
        
#         header_data = [[
#             Paragraph("STATE", header_label_style),
#             Paragraph("DISTRICT", header_label_style),
#             Paragraph("COURT COMPLEX", header_label_style)
#         ],[
#             Paragraph(state, header_value_style),
#             Paragraph(district, header_value_style),
#             Paragraph(court_complex, header_value_style)
#         ]]
        
#         header_table = Table(header_data, colWidths=[2.4*inch, 2.4*inch, 5.8*inch])
#         header_table.setStyle(TableStyle([
#             ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#003366')),
#             ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
#             ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
#             ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
#             ('TOPPADDING', (0, 0), (-1, -1), 10),
#             ('LEFTPADDING', (0, 0), (-1, -1), 8),
#             ('RIGHTPADDING', (0, 0), (-1, -1), 8),
#             ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#003366')),
#             ('LINEWIDTH', (0, 0), (-1, -1), 1),
#         ]))
#         story.append(header_table)
#         story.append(Spacer(1, 0.15*inch))
        
#         # Selected court information
#         info_style = ParagraphStyle(
#             'InfoStyle',
#             parent=styles['Normal'],
#             fontSize=10,
#             spaceAfter=10,
#             alignment=0,
#             textColor=colors.HexColor('#003366'),
#             fontName='Helvetica-Bold'
#         )
        
#         info_text = f"<b>Selected Court Name:</b> {court_name}<br/><b>Date:</b> {date} | <b>Case Type:</b> {case_type}"
#         story.append(Paragraph(info_text, info_style))
#         story.append(Spacer(1, 0.12*inch))
        
#         # Add list of available judges/court names
#         if available_judges and len(available_judges) > 0:
#             judges_title_style = ParagraphStyle(
#                 'JudgesTitle',
#                 parent=styles['Normal'],
#                 fontSize=10,
#                 textColor=colors.HexColor('#003366'),
#                 fontName='Helvetica-Bold',
#                 spaceAfter=8
#             )
#             story.append(Paragraph("Available Court Names in this Complex:", judges_title_style))
            
#             judges_list_style = ParagraphStyle(
#                 'JudgesList',
#                 parent=styles['Normal'],
#                 fontSize=9,
#                 textColor=colors.black,
#                 leading=12,
#                 leftIndent=15
#             )
            
#             selected_judges_style = ParagraphStyle(
#                 'SelectedJudge',
#                 parent=styles['Normal'],
#                 fontSize=9,
#                 textColor=colors.HexColor('#003366'),
#                 fontName='Helvetica-Bold',
#                 leading=12,
#                 leftIndent=15,
#                 backColor=colors.HexColor('#E8F4F8')
#             )
            
#             # Filter out "Select Court Name" and duplicates, then sort
#             filtered_judges = []
#             seen = set()
#             for judge in available_judges:
#                 judge_clean = judge.strip()
#                 # Skip "Select Court Name" placeholder
#                 if judge_clean.lower() != "select court name" and judge_clean not in seen:
#                     filtered_judges.append(judge_clean)
#                     seen.add(judge_clean)
            
#             # Remove duplicates by converting to set and back (preserves order somewhat)
#             unique_judges = []
#             seen_judges = set()
#             for judge in filtered_judges:
#                 if judge not in seen_judges:
#                     unique_judges.append(judge)
#                     seen_judges.add(judge)
            
#             # Create bulleted list with selected judge highlighted
#             for judge in unique_judges:
#                 # Check if this is the selected court
#                 if court_name.strip() in judge or judge in court_name.strip():
#                     story.append(Paragraph(f"<b>• {judge} (SELECTED)</b>", selected_judges_style))
#                 else:
#                     story.append(Paragraph(f"• {judge}", judges_list_style))
            
#             story.append(Spacer(1, 0.15*inch))
        
#         # Cases table header styles
#         table_header_style = ParagraphStyle(
#             'TableHeader',
#             parent=styles['Normal'],
#             fontSize=9,
#             fontName='Helvetica-Bold',
#             textColor=colors.whitesmoke,
#             alignment=1,
#             leading=11
#         )
        
#         # Cell content style
#         cell_style = ParagraphStyle(
#             'CellContent',
#             parent=styles['Normal'],
#             fontSize=7.5,
#             fontName='Helvetica',
#             alignment=0,
#             leading=9,
#             splitLongWords=True,
#             wordWrap='CJK'
#         )
        
#         # Build cases table data
#         table_data = []
        
#         # Add header
#         table_data.append([
#             Paragraph('Sr No', table_header_style),
#             Paragraph('Case Number', table_header_style),
#             Paragraph('Parties', table_header_style),
#             Paragraph('Advocate', table_header_style)
#         ])
        
#         # Add case rows
#         for case in cases:
#             serial = str(case.get('serial', '')).strip()
#             case_number = str(case.get('case_number', '')).strip()
#             parties = str(case.get('party_name', case.get('parties', ''))).strip()
#             advocate = str(case.get('advocate', '')).strip()
            
#             # Format case number with line break before "Next hearing date"
#             if 'Next hearing date' in case_number:
#                 parts = case_number.split('Next hearing date')
#                 case_number = parts[0].strip() + '\n\n' + '<b>Next hearing date</b>' + parts[1]
            
#             table_data.append([
#                 Paragraph(serial, cell_style),
#                 Paragraph(case_number, cell_style),
#                 Paragraph(parties, cell_style),
#                 Paragraph(advocate, cell_style)
#             ])
        
#         # Create cases table
#         cases_table = Table(
#             table_data,
#             colWidths=[0.45*inch, 2.8*inch, 5.5*inch, 1.2*inch],
#             repeatRows=1,
#             splitByRow=1
#         )
        
#         cases_table.setStyle(TableStyle([
#             # Header styling
#             ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
#             ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
#             ('FONTSIZE', (0, 0), (-1, 0), 9),
#             ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
#             ('TOPPADDING', (0, 0), (-1, 0), 8),
#             ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
#             ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
#             ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
#             # Body styling
#             ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
#             ('FONTSIZE', (0, 1), (-1, -1), 8),
#             ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
#             ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            
#             # Alignment and padding
#             ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
#             ('VALIGN', (0, 1), (-1, -1), 'TOP'),
#             ('LEFTPADDING', (0, 1), (-1, -1), 5),
#             ('RIGHTPADDING', (0, 1), (-1, -1), 5),
#             ('TOPPADDING', (0, 1), (-1, -1), 6),
#             ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            
#             # Grid and borders
#             ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
#             ('LINEWIDTH', (0, 0), (-1, -1), 0.5),
            
#             # Auto row height
#             ('ROWHEIGHTS', (0, 1), (-1, -1), None),
#         ]))
        
#         story.append(cases_table)
        
#         story.append(Spacer(1, 0.15*inch))
#         footer_style = ParagraphStyle(
#             'FooterStyle',
#             parent=styles['Normal'],
#             fontSize=8,
#             alignment=1,
#             textColor=colors.grey
#         )
#         footer_text = f"Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Cases: {len(cases)}"
#         story.append(Paragraph(footer_text, footer_style))
        
#         doc.build(story)
#         return str(output_path)
        
#     except Exception as e:
#         print(f"PDF generation error: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         return None

def generate_pdf_from_cases(cases: List[Dict], output_filename: str, court_name: str, date: str, case_type: str, state: str = '', district: str = '', court_complex: str = '', available_judges: List[str] = None):
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        
        output_path = BASE_DIR / output_filename
        
        # Use landscape for better width
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=landscape(A4),
            topMargin=0.4*inch,
            bottomMargin=0.4*inch,
            leftMargin=0.3*inch,
            rightMargin=0.3*inch
        )
        
        story = []
        styles = getSampleStyleSheet()
        
        # Main title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=15,
            alignment=1,
            textColor=colors.HexColor('#003366')
        )
        
        title_text = "CAUSE LIST"
        story.append(Paragraph(title_text, title_style))
        story.append(Spacer(1, 0.1*inch))
        
        # Blue Header Box with State, District, Court Complex
        header_label_style = ParagraphStyle(
            'HeaderLabel',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold',
            textColor=colors.whitesmoke,
            alignment=1,
            leading=12
        )
        
        header_value_style = ParagraphStyle(
            'HeaderValue',
            parent=styles['Normal'],
            fontSize=9,
            fontName='Helvetica',
            textColor=colors.whitesmoke,
            alignment=1,
            leading=11
        )
        
        header_data = [[
            Paragraph("STATE", header_label_style),
            Paragraph("DISTRICT", header_label_style),
            Paragraph("COURT COMPLEX", header_label_style)
        ],[
            Paragraph(state, header_value_style),
            Paragraph(district, header_value_style),
            Paragraph(court_complex, header_value_style)
        ]]
        
        header_table = Table(header_data, colWidths=[2.4*inch, 2.4*inch, 5.8*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#003366')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#003366')),
            ('LINEWIDTH', (0, 0), (-1, -1), 1),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 0.15*inch))
        
        # Selected court information
        info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=10,
            alignment=0,
            textColor=colors.HexColor('#003366'),
            fontName='Helvetica-Bold'
        )
        
        info_text = f"<b>Selected Court Name:</b> {court_name}<br/><b>Date:</b> {date} | <b>Case Type:</b> {case_type}"
        story.append(Paragraph(info_text, info_style))
        story.append(Spacer(1, 0.12*inch))
        
        # Add list of available judges/court names
        if available_judges and len(available_judges) > 0:
            judges_title_style = ParagraphStyle(
                'JudgesTitle',
                parent=styles['Normal'],
                fontSize=10,
                textColor=colors.HexColor('#003366'),
                fontName='Helvetica-Bold',
                spaceAfter=8
            )
            story.append(Paragraph("Available Court Names in this Complex:", judges_title_style))
            
            judges_list_style = ParagraphStyle(
                'JudgesList',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.black,
                leading=12,
                leftIndent=15
            )
            
            selected_judges_style = ParagraphStyle(
                'SelectedJudge',
                parent=styles['Normal'],
                fontSize=9,
                textColor=colors.HexColor('#003366'),
                fontName='Helvetica-Bold',
                leading=12,
                leftIndent=15,
                backColor=colors.HexColor('#E8F4F8')
            )
            
            # CRITICAL: Remove ALL duplicates properly - use dict to maintain order
            unique_judges = []
            seen_judges = set()
            
            for judge in available_judges:
                judge_clean = judge.strip()
                # Skip "Select Court Name" placeholder and empty strings
                if (judge_clean and 
                    judge_clean.lower() != "select court name" and 
                    judge_clean not in seen_judges):
                    unique_judges.append(judge_clean)
                    seen_judges.add(judge_clean)
            
            # Create bulleted list with selected judge highlighted
            for judge in unique_judges:
                # Check if this is the selected court
                if court_name.strip() in judge or judge in court_name.strip():
                    story.append(Paragraph(f"<b>• {judge} (SELECTED)</b>", selected_judges_style))
                else:
                    story.append(Paragraph(f"• {judge}", judges_list_style))
            
            story.append(Spacer(1, 0.15*inch))
        
        # Cases table header styles
        table_header_style = ParagraphStyle(
            'TableHeader',
            parent=styles['Normal'],
            fontSize=9,
            fontName='Helvetica-Bold',
            textColor=colors.whitesmoke,
            alignment=1,
            leading=11
        )
        
        # Cell content style
        cell_style = ParagraphStyle(
            'CellContent',
            parent=styles['Normal'],
            fontSize=7.5,
            fontName='Helvetica',
            alignment=0,
            leading=9,
            splitLongWords=True,
            wordWrap='CJK'
        )
        
        # Build cases table data
        table_data = []
        
        # Add header
        table_data.append([
            Paragraph('Sr No', table_header_style),
            Paragraph('Case Number', table_header_style),
            Paragraph('Parties', table_header_style),
            Paragraph('Advocate', table_header_style)
        ])
        
        # Add case rows
        for case in cases:
            serial = str(case.get('serial', '')).strip()
            case_number = str(case.get('case_number', '')).strip()
            parties = str(case.get('party_name', case.get('parties', ''))).strip()
            advocate = str(case.get('advocate', '')).strip()
            
            # Format case number with line break before "Next hearing date"
            if 'Next hearing date' in case_number:
                parts = case_number.split('Next hearing date')
                case_number = parts[0].strip() + '\n\n' + '<b>Next hearing date</b>' + parts[1]
            
            table_data.append([
                Paragraph(serial, cell_style),
                Paragraph(case_number, cell_style),
                Paragraph(parties, cell_style),
                Paragraph(advocate, cell_style)
            ])
        
        # Create cases table
        cases_table = Table(
            table_data,
            colWidths=[0.45*inch, 2.8*inch, 5.5*inch, 1.2*inch],
            repeatRows=1,
            splitByRow=1
        )
        
        cases_table.setStyle(TableStyle([
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
            # Body styling
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            
            # Alignment and padding
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 1), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 1), (-1, -1), 5),
            ('RIGHTPADDING', (0, 1), (-1, -1), 5),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            
            # Grid and borders
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('LINEWIDTH', (0, 0), (-1, -1), 0.5),
            
            # Auto row height
            ('ROWHEIGHTS', (0, 1), (-1, -1), None),
        ]))
        
        story.append(cases_table)
        
        story.append(Spacer(1, 0.15*inch))
        footer_style = ParagraphStyle(
            'FooterStyle',
            parent=styles['Normal'],
            fontSize=8,
            alignment=1,
            textColor=colors.grey
        )
        footer_text = f"Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Cases: {len(cases)}"
        story.append(Paragraph(footer_text, footer_style))
        
        doc.build(story)
        return str(output_path)
        
    except Exception as e:
        print(f"PDF generation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
# generate pdf and parse table        