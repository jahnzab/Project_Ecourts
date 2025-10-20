
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
        print(f"📅 Using today's date: {today.strftime('%d-%m-%Y')}")
        return today
        
    if arg == "tomorrow":
        tomorrow = today + datetime.timedelta(days=1)
        # Check if tomorrow is within 1 month
        max_allowed_date = today + datetime.timedelta(days=30)
        if tomorrow > max_allowed_date:
            print(f"⚠️  Tomorrow ({tomorrow}) is beyond 1 month limit.")
            print(f"🔄 Using maximum allowed date: {max_allowed_date}")
            return max_allowed_date
        print(f"📅 Using tomorrow's date: {tomorrow.strftime('%d-%m-%Y')}")
        return tomorrow
    
    # else parse YYYY-MM-DD
    try:
        parsed_date = datetime.datetime.strptime(arg_when, "%Y-%m-%d").date()
        # Check if date is within 1 month from today
        max_allowed_date = today + datetime.timedelta(days=30)
        if parsed_date > max_allowed_date:
            print(f"⚠️  Date {parsed_date} is beyond 1 month limit.")
            print(f"🔄 Using maximum allowed date: {max_allowed_date}")
            return max_allowed_date
        print(f"📅 Using specified date: {parsed_date.strftime('%d-%m-%Y')}")
        return parsed_date
    except Exception as e:
        print(f"❌ Date error: {e}, defaulting to today")
        return today

def save_results(cases: List[Dict], filename_prefix: str):
    """Save cases to CSV and JSON files"""
    if not cases:
        logger.warning("No cases to save")
        return
    
    # Create output directory if it doesn't exist
    BASE_DIR.mkdir(exist_ok=True)
    
    # Save to CSV
    csv_path = BASE_DIR / f"{filename_prefix}.csv"
    df = pd.DataFrame(cases)
    df.to_csv(csv_path, index=False, encoding='utf-8')
    print(f"✅ Saved {len(cases)} cases to CSV: {csv_path}")
    
    # Save to JSON
    json_path = BASE_DIR / f"{filename_prefix}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved cases to JSON: {json_path}")
    
    return csv_path, json_path

def fetch_cause_list_from_html(html_file: str) -> List[Dict]:
    """Extract cases from saved HTML file using BeautifulSoup"""
    cases = []
    
    try:
        if not os.path.exists(html_file):
            print(f"HTML file not found: {html_file}")
            return cases
            
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()

        soup = BeautifulSoup(html, 'html.parser')
        cases = extract_cases_from_soup(soup)
        print(f"Extracted {len(cases)} cases from HTML file")
        
    except Exception as e:
        print(f"Error processing HTML file: {e}")
    
    return cases

def looks_like_real_case(case_info: Dict) -> bool:
    """Check if the case info looks like a real case"""
    return (
        case_info.get('serial', '').strip() and
        case_info.get('case_number', '').strip() and
        case_info.get('party_name', '').strip()
    )


def parse_table_rows(table) -> List[Dict]:
    """
    Parse table rows from the nested HTML structure where:
    - Sr No | Cases | Party Name | Advocate (headers)
    - Multiple rows with case info, hearing date, and status tags
    """
    cases = []
    rows = table.find_all('tr')
    print(f"🔍 Parsing table with {len(rows)} rows")
    
    current_case = None
    skip_headers = True
    
    for row_idx, row in enumerate(rows):
        cells = row.find_all('td')
        
        if not cells:
            continue
        
        cell_texts = [cell.get_text(strip=True) for cell in cells]
        
        if not any(cell_texts):
            continue
        
        # Skip header row
        if skip_headers and any('Sr No' in text or 'Cases' in text for text in cell_texts):
            skip_headers = False
            continue
        
        # Check for section headers (single cell, non-numeric)
        if len(cells) == 1:
            section_text = cell_texts[0]
            if section_text and not section_text[0].isdigit():
                if current_case and looks_like_real_case(current_case):
                    cases.append(current_case)
                
                print(f"\n📂 {section_text}")
                current_case = None
                continue
        
        # Check if new case row (starts with number)
        first_cell = cell_texts[0].strip()
        if first_cell and first_cell[0].isdigit():
            if current_case and looks_like_real_case(current_case):
                cases.append(current_case)
            
            serial = first_cell
            case_number = cell_texts[1].strip() if len(cell_texts) > 1 else ""
            case_number = case_number.replace('\n', ' ').strip()
            
            party_name = cell_texts[2].strip() if len(cell_texts) > 2 else ""
            # Fix party name: add spaces around "versus"
            party_name = party_name.replace('\n', ' ').strip()
            party_name = party_name.replace('versus', ' versus ').replace('  ', ' ').strip()
            
            advocate = cell_texts[3].strip() if len(cell_texts) > 3 else ""
            advocate = advocate.replace('\n', ' ').strip()
            
            current_case = {
                'serial': serial,
                'case_number': case_number,
                'party_name': party_name,
                'advocate': advocate
            }
            
            print(f"  Row {row_idx}: ✅ Case #{serial}")
        

    
    # Save last case
    if current_case and looks_like_real_case(current_case):
        cases.append(current_case)
    
    print(f"📊 Total cases from this table: {len(cases)}")
    return cases


def extract_cases_from_soup(soup: BeautifulSoup) -> List[Dict]:
    """Extract cases from BeautifulSoup object with nested structure handling"""
    cases = []
    
    try:
        # Extract court name from page header
        court_name = ""
        page_text = soup.get_text()
        
        # Look for court name in the page text (usually near the top)
        lines = page_text.split('\n')
        for line in lines:
            line = line.strip()
            if 'Additional District' in line or 'District Judge' in line or 'Judge' in line:
                if line and not line.startswith('Select'):
                    court_name = line
                    break
        
        print(f"Court Name: {court_name}\n")
        
        table = soup.find('table')
        if table:
            print("Found table with ID 'dispTable'" if table.get('id') == 'dispTable' else "Found table")
            cases = parse_table_rows(table)
            
            # Add court_name to all cases
            for case in cases:
                case['court_name'] = court_name
            
            if cases:
                print(f"✅ Extracted {len(cases)} cases from table")
        else:
            print("No table found in HTML")
            
    except Exception as e:
        print(f"Error parsing: {e}")
        import traceback
        traceback.print_exc()
    
    return cases
def extract_cases_using_beautifulsoup(driver) -> List[Dict]:
    """Extract cases from the current page HTML using BeautifulSoup"""
    try:
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        import os
        output_dir = "ecourts_output"
        os.makedirs(output_dir, exist_ok=True)
        
        debug_file = os.path.join(output_dir, "debug_page.html")
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Saved page HTML to: {debug_file}\n")
        
        cases = extract_cases_from_soup(soup)
        print(f"Extracted {len(cases)} cases using BeautifulSoup\n")
        
        return cases
        
    except Exception as e:
        print(f"Error extracting cases with BeautifulSoup: {e}")
        import traceback
        traceback.print_exc()
        return []
def parse_cases_from_text(text: str) -> List[Dict]:
    """Parse cases from raw text content"""
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

def parse_cases_from_text(text: str) -> List[Dict]:
    """Parse cases from raw text content"""
    cases = []
    lines = text.split('\n')
    
    current_case = {}
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for serial number patterns
        serial_match = re.match(r'^(\d+)\.?\s*$', line)
        if serial_match and not current_case:
            current_case = {'serial': serial_match.group(1)}
            i += 1
            continue
        
        # Look for case number patterns
        case_match = re.search(r'(View)?(OS|AS|ARBTN|CS)/\d+/\d+', line, re.IGNORECASE)
        if case_match and current_case and 'case_number' not in current_case:
            current_case['case_number'] = line.strip()
            i += 1
            continue
        
        # Look for parties (lines with "versus")
        if 'versus' in line.lower() and current_case and 'parties' not in current_case:
            current_case['parties'] = line.strip()
            i += 1
            continue
        
        # Look for advocate (lines with "Sri" or short names after parties)
        if (current_case and 'parties' in current_case and 'advocate' not in current_case and
            line and len(line.split()) <= 4 and not line.isdigit()):
            current_case['advocate'] = line.strip()
            i += 1
            continue
        
        # If we have a complete case, save it
        if current_case and 'case_number' in current_case and 'parties' in current_case:
            if looks_like_real_case(current_case):
                cases.append(current_case)
            current_case = {}
        
        i += 1
    
    # Don't forget the last case
    if current_case and 'case_number' in current_case and 'parties' in current_case:
        if looks_like_real_case(current_case):
            cases.append(current_case)
    
    return cases

def download_pdf_manual_captcha(pdf_url: str, output_path: str) -> bool:
    """Download PDF with manual CAPTCHA handling"""
    print(f"Downloading PDF from: {pdf_url}")
    print("If the PDF requires CAPTCHA, please handle it manually in the browser.")
    print(f"PDF will be saved to: {output_path}")
    
    try:
        # Create browser instance for PDF download
        browser = Browser(headless=False)
        
        # Navigate to PDF URL
        browser.driver.get(pdf_url)
        
        # Wait for user to handle CAPTCHA if needed
        print("Please handle any CAPTCHA or authentication in the browser...")
        input("Press ENTER after the PDF loads or downloads...")
        
        # Check if we're on a PDF page or download page
        current_url = browser.driver.current_url
        if current_url.endswith('.pdf'):
            # Direct PDF URL - download it
            response = requests.get(current_url, stream=True)
            response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)
            
            print(f"PDF successfully downloaded to: {output_path}")
            browser.close()
            return True
        else:
            # Try to find PDF download links
            pdf_links = browser.driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")
            if pdf_links:
                pdf_url = pdf_links[0].get_attribute('href')
                response = requests.get(pdf_url, stream=True)
                response.raise_for_status()
                
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                
                print(f"PDF successfully downloaded to: {output_path}")
                browser.close()
                return True
            else:
                print("No PDF link found on the page")
                browser.close()
                return False
                
    except Exception as e:
        print(f"PDF download failed: {e}")
        return False

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
        
        # Enhanced download preferences for PDFs
        if download_dir:
            download_path = os.path.abspath(download_dir)
            prefs = {
                "download.default_directory": download_path,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "plugins.always_open_pdf_externally": True,  # Don't open PDF in browser
                "safebrowsing.enabled": True,
                "profile.default_content_settings.popups": 0,  # Disable download popups
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
        # wait minimal element
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

    def interactive_select_from(self, select_by_tuple, description: str) -> Optional[str]:
        # Wait for select to appear
        try:
            sel = self.wait.until(EC.presence_of_element_located(select_by_tuple))
        except TimeoutException:
            logger.error("%s select not found", description)
            return None
        opts = self.get_options_from_select(sel)
        if not opts:
            # wait a bit more — sometimes options load after
            human_delay(1.0, 2.0)
            opts = self.get_options_from_select(sel)
        if not opts:
            logger.error("No options in %s", description)
            return None
        print(f"\nAvailable {description}s:")
        for i, o in enumerate(opts, 1):
            print(f"  {i}. {o}")
        while True:
            choice = input(f"Select {description} (1-{len(opts)}): ").strip()
            if not choice:
                selected = opts[0]; break
            if choice.isdigit() and 1 <= int(choice) <= len(opts):
                selected = opts[int(choice) - 1]; break
            print("Invalid choice")
        
        # Safe selection that handles disabled options
        try:
            select_obj = Select(sel)
            select_obj.select_by_visible_text(selected)
        except Exception as e:
            logger.warning("Select by visible text failed, trying by index: %s", e)
            # Fallback: select by index
            for i, opt in enumerate(select_obj.options):
                if opt.text.strip() == selected and opt.is_enabled():
                    select_obj.select_by_index(i)
                    break
        human_delay(0.6, 1.2)
        return selected

    def wait_for_judge_dropdown(self) -> Optional[webdriver.remote.webelement.WebElement]:
        """Try multiple strategies to find the judge dropdown after court_complex selection."""
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
                # Ensure it's not 
                # the same as court_complex and has options
                try:
                    complex_el = self.driver.find_element(By.ID, "court_complex_code")
                    if el == complex_el:
                        continue
                except Exception:
                    pass
                
                # Check if it has options (not just "Select" or empty)
                options = self.get_options_from_select(el)
                if len(options) > 1:  # More than just "Select" option
                    logger.info("Found judge dropdown via %s %s with %d options", by, val, len(options))
                    return el
                else:
                    logger.debug("Found dropdown but no options: %s %s", by, val)
                    
            except Exception as e:
                continue
        
        return None

    def debug_page_state(self):
        """Debug the current page state"""
        try:
            current_url = self.driver.current_url
            page_title = self.driver.title
            
            print(f"🔍 DEBUG - URL: {current_url}")
            print(f"🔍 DEBUG - Title: {page_title}")
            
            # Check all dropdowns
            all_selects = self.driver.find_elements(By.TAG_NAME, "select")
            print(f"🔍 DEBUG - Found {len(all_selects)} dropdowns:")
            
            for i, select in enumerate(all_selects):
                select_id = select.get_attribute('id') or 'no-id'
                select_name = select.get_attribute('name') or 'no-name'
                is_displayed = select.is_displayed()
                is_enabled = select.is_enabled()
                
                options = select.find_elements(By.TAG_NAME, "option")
                option_texts = []
                for opt in options[:5]:  # First 5 options
                    text = opt.text.strip()
                    if text:
                        option_texts.append(text)
                
                print(f"  {i+1}. ID: '{select_id}', Name: '{select_name}'")
                print(f"     Displayed: {is_displayed}, Enabled: {is_enabled}")
                print(f"     Options ({len(options)}): {option_texts}")
                
        except Exception as e:
            print(f"🔍 DEBUG Error: {e}")
    def process_all_courts_batch(self, district: str, date_obj: datetime.date, judges: List[str]) -> Dict[str, List[Dict]]:
   
     all_results = {}
    
     for i, judge in enumerate(judges, 1):
        print(f"\n{'='*60}")
        print(f"🔄 Processing court/judge {i}/{len(judges)}: {judge}")
        print(f"{'='*60}")
        
        try:
            # Navigate back to the main form if needed
            if i > 1:
                print("🔄 Returning to main form...")
                self.driver.get(CAUSE_LIST_URL)
                human_delay(2.0, 3.0)
                
                # Re-select state, district, court complex
                self.wait.until(EC.presence_of_element_located((By.ID, "sess_state_code")))
                human_delay(1.0, 2.0)
                
                # Note: You might need to re-select previous options here
                # This is a simplified version - you may need to adapt based on your actual flow
                print("🔄 Re-selecting previous options...")
                # You'll need to implement re-selection logic based on your specific flow
            
            # Select the specific judge
            judge_el = self.wait_for_judge_dropdown()
            if judge_el:
                try:
                    select_obj = Select(judge_el)
                    select_obj.select_by_visible_text(judge)
                    human_delay(1.0, 2.0)
                except Exception as e:
                    logger.warning(f"Select by visible text failed for {judge}, trying by index: {e}")
                    # Fallback selection logic
                    for idx, opt in enumerate(select_obj.options):
                        if opt.text.strip() == judge and opt.is_enabled():
                            select_obj.select_by_index(idx)
                            break
            
            # Set date
            if not self.set_date_mmddyyyy(date_obj):
                print(f"❌ Failed to set date for {judge}, skipping...")
                continue
            
            # Handle CAPTCHA
            human_delay(1.0, 2.0)
            if not self.captcha_terminal_or_ocr(max_attempts=3):  # Reduced attempts for batch
                print(f"❌ CAPTCHA failed for {judge}, skipping...")
                continue
            
            # Select case type
            human_delay(1.0, 2.0)
            case_type = self.select_case_type_prompt()
            
            if case_type in ["DateError", "FormPage"]:
                print(f"❌ Case type selection failed for {judge}, skipping...")
                continue
            
            # Extract cases
            print(f"⏳ Extracting cases for {judge}...")
            human_delay(3.0, 5.0)
            cases = self.extract_cases_using_beautifulsoup()
            
            # Add metadata
            for case in cases:
                case['court_name'] = judge
                case['date'] = date_obj.strftime("%Y-%m-%d")
                case['case_type'] = case_type
                case['district'] = district
            
            all_results[judge] = cases
            print(f"✅ Extracted {len(cases)} cases for {judge}")
            
        except Exception as e:
            print(f"❌ Error processing {judge}: {e}")
            continue
    
     return all_results
    def interactive_court_judge_selection(self, select_all: bool = False) -> List[str]:
    
     logger.info("Attempting to find Court Name / Judge dropdown...")
    
     # Debug current state
     print("🔍 Checking available dropdowns...")
     self.debug_page_state()
    
     # First try to locate an element (may require dispatch change)
     try:
        complex_el = self.driver.find_element(By.ID, "court_complex_code")
        # Trigger change event to load judges
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", complex_el)
        logger.info("Triggered change event on court complex dropdown")
     except Exception as e:
        logger.debug(f"Could not trigger change event: {e}")

     # Wait for AJAX to load judges
     print("⏳ Waiting for judge list to load...")
     human_delay(2.0, 3.0)

     # Try multiple times with increasing delays
     judge_el = None
     for attempt in range(5):
        print(f"🔍 Looking for judge dropdown... attempt {attempt + 1}/5")
        judge_el = self.wait_for_judge_dropdown()
        if judge_el:
            break
        human_delay(1.0, 2.0)

     if not judge_el:
        print("❌ Still cannot find judge dropdown after manual help.")
        raise RuntimeError("Judge selection failed - no judge dropdown found")

     # Get options from the dropdown (exclude "Select Court Name")
     all_opts = self.get_options_from_select(judge_el)
     opts = [opt for opt in all_opts if opt.lower() not in ["select court name",  "select", "choose"]]

     if not opts:
        print("❌ No judges available in the dropdown.")
        raise RuntimeError("Judge selection failed - no judges available")

     print(f"\n✅ Found {len(opts)} judges/courts:")
     for i, t in enumerate(opts, 1):
        print(f"  {i}. {t}")
    
     if select_all:
        # Return ALL options for batch processing (excluding "Select Court Name")
        print(f"🔄 Selecting ALL {len(opts)} courts/judges for batch processing")
        return opts
     else:
        # Show selection options including "all"
        print(f"\n🎯 Selection Options:")
        print(f"  1-{len(opts)} - Select specific court/judge")
        print(f"  all - Process ALL {len(opts)} courts/judges")
        
        while True:
            ch = input(f"\nEnter your choice (1-{len(opts)} or 'all'): ").strip().lower()
            
            if ch == 'all':
                return opts
            if ch.isdigit() and 1 <= int(ch) <= len(opts):
                selected_judge = opts[int(ch) - 1]
                print(f"✅ Selected: {selected_judge}")
                
                # Select the specific judge
                try:
                    select_obj = Select(judge_el)
                    select_obj.select_by_visible_text(selected_judge)
                except Exception as e:
                    logger.warning(f"Select by visible text failed, trying alternatives: {e}")
                    # Try alternative selection methods
                    for idx, opt in enumerate(select_obj.options):
                        if opt.text.strip() == selected_judge and opt.is_enabled():
                            select_obj.select_by_index(idx)
                            break
                
                human_delay(1.0, 2.0)
                return [selected_judge]
            
            print(f"❌ Invalid choice. Please enter 1-{len(opts)} or 'all'")

    def set_date_mmddyyyy(self, date_obj: datetime.date) -> bool:
        """Set date in DD-MM-YYYY format (Indian standard)"""
        # Ensure date is within allowed range
        today = datetime.date.today()
        max_allowed_date = today + datetime.timedelta(days=30)
        
        if date_obj > max_allowed_date:
            print(f"❌ Date {date_obj} is beyond 1 month limit.")
            print(f"🔄 Using maximum allowed date: {max_allowed_date}")
            date_obj = max_allowed_date
        
        # **USE DD-MM-YYYY FORMAT (Indian standard)**
        date_str_ddmmyyyy = date_obj.strftime("%d-%m-%Y")  # Correct: DD-MM-YYYY
        date_str_mmddyyyy = date_obj.strftime("%m-%d-%Y")  # Fallback: MM-DD-YYYY
        
        print(f"📅 Setting date to: {date_str_ddmmyyyy} (DD-MM-YYYY format)")
        
        # Try multiple date input fields
        date_selectors = [
            (By.ID, "cause_list_date"),
            (By.NAME, "cause_list_date"), 
            (By.ID, "hearing_date"),
            (By.NAME, "hearing_date"),
            (By.XPATH, "//input[contains(@id,'date')]"),
            (By.XPATH, "//input[contains(@name,'date')]"),
            (By.XPATH, "//input[@type='date']"),
        ]
        
        # Try DD-MM-YYYY first (Indian format)
        for by, selector in date_selectors:
            try:
                date_input = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, selector))
                )
                
                # Clear existing value
                date_input.clear()
                human_delay(0.5, 1.0)
                
                # Try DD-MM-YYYY format
                date_input.send_keys(date_str_ddmmyyyy)
                human_delay(1.0, 1.5)
                
                # Verify the value was set
                actual_value = date_input.get_attribute('value')
                if actual_value:
                    print(f"✅ Date set successfully to: {date_str_ddmmyyyy}")
                    return True
                    
            except Exception as e:
                continue
        
        # If DD-MM-YYYY failed, try MM-DD-YYYY as fallback
        print("⚠️  DD-MM-YYYY format failed, trying MM-DD-YYYY...")
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
                    print(f"✅ Date set successfully to: {date_str_mmddyyyy}")
                    return True
                    
            except Exception as e:
                continue
        
        print("❌ Failed to set date in any format")
        return False

    def click_case_type_button(self, case_type: str) -> bool:
     """Automatically find and click Civil or Criminal button"""
     # Map case type to the onclick parameter value
     type_mapping = {
        "Civil": "civ",
        "Criminal": "cri"
     }
    
     onclick_value = type_mapping.get(case_type, "")
    
     button_selectors = [
        # EXACT SELECTORS FOR THE BUTTONS YOU FOUND
        (By.XPATH, f"//button[@class='btn btn-primary' and contains(@onclick, '{onclick_value}')]"),
        (By.XPATH, f"//button[contains(@onclick, 'submit_causelist') and contains(@onclick, '{onclick_value}')]"),
        (By.XPATH, f"//button[contains(text(), '{case_type}') and contains(@onclick, 'submit_causelist')]"),
        
        # Fallback selectors
        (By.XPATH, f"//button[contains(text(), '{case_type}')]"),
        (By.XPATH, f"//input[@value='{case_type}']"),
     ]
    
     for by, selector in button_selectors:
        try:
            button = self.driver.find_element(by, selector)
            if button.is_displayed() and button.is_enabled():
                print(f"✅ Found {case_type} button using: {selector}")
                try:
                    button.click()
                    return True
                except Exception as e:
                    # Try JavaScript click as fallback
                    self.driver.execute_script("arguments[0].click();", button)
                    return True
        except Exception:
            continue
    
     print(f"❌ No {case_type} button found")
     return False

    def _check_case_type_success(self, case_type: str) -> bool:
     """Check if case type button click was successful"""
     # Check for errors first
     if self.check_for_popup_errors():
        print(f"❌ {case_type} submission failed due to error")
        return False
    
     # Check if URL changed (indicating form submission)
     current_url = self.driver.current_url
     if "cause_list/index" not in current_url:
        print(f"✅ URL changed - {case_type} submission successful")
        return True
    
     # Check for results table or case list
     if self.has_cause_list_content():
        print(f"✅ {case_type} cause list content detected")
        return True
    
     # Check for case type specific content in page
     try:
        page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        if (case_type.lower() in page_text and 
            any(keyword in page_text for keyword in ['case', 'cause list', 'viewos', 'viewas', 'dispTable'])):
            print(f"✅ {case_type} content verified in page text")
            return True
     except Exception:
        pass
    
     return False

    def select_case_type_prompt(self) -> str:
     """Automatically detect and click Civil or Criminal buttons - FULLY AUTOMATIC"""
     print("\n🔍 Automatically detecting and clicking Civil/Criminal buttons...")
    
     # Store original URL for comparison
     original_url = self.driver.current_url
     print(f"🔍 Current URL before button click: {original_url}")
    
     # STRATEGY 1: Try Civil first (most common)
     print("🔄 Attempting to click Civil button...")
     civil_clicked = self.click_case_type_button("Civil")
    
     if civil_clicked:
        print("✅ Civil button clicked successfully")
        human_delay(4.0, 6.0)  # Wait for page load
        
        # Check if successful
        if self._check_case_type_success("Civil"):
            print("✅ Civil case type selection successful!")
            return "Civil"
        else:
            print("❌ Civil button click didn't produce expected results")
            # Check if we're still on the same page (button didn't work)
            current_url = self.driver.current_url
            if current_url == original_url:
                print("🔄 Still on same page, Civil button might not have worked, trying Criminal...")
            else:
                print("🔄 Page changed but no results detected, trying Criminal...")
            
            # Try going back and clicking Criminal
            try:
                self.driver.back()
                human_delay(3.0, 5.0)
            except:
                print("❌ Could not go back, refreshing page...")
                self.driver.get(original_url)
                human_delay(3.0, 5.0)
    
     # STRATEGY 2: Try Criminal button
     print("🔄 Attempting to click Criminal button...")
     criminal_clicked = self.click_case_type_button("Criminal")
    
     if criminal_clicked:
        print("✅ Criminal button clicked successfully")
        human_delay(4.0, 6.0)  # Wait for page load
        
        if self._check_case_type_success("Criminal"):
            print("✅ Criminal case type selection successful!")
            return "Criminal"
        else:
            print("❌ Criminal button click didn't produce expected results")
    
     # STRATEGY 3: If automatic clicking fails, ask user
     print("❌ Automatic button clicking failed")
     return self._ask_user_for_case_type()

    def _ask_user_for_case_type(self) -> str:
     """Ask user which case type to use when automatic fails"""
     print("\n" + "="*50)
     print("⚠️  AUTOMATIC BUTTON DETECTION FAILED")
     print("="*50)
     print("Please select case type:")
     print("1. Civil Cases")
     print("2. Criminal Cases")
     print("="*50)
    
     while True:
        choice = input("Enter your choice (1 or 2): ").strip()
        if choice == "1":
            return "Civil"
        elif choice == "2":
            return "Criminal"
        else:
            print("❌ Invalid choice. Please enter 1 or 2.")

    def _analyze_page_for_case_type(self) -> str:
     """Analyze page content to determine case type"""
     try:
        page_text = self.driver.find_element(By.TAG_NAME, "body").text
        page_source = self.driver.page_source
        
        # Look for indicators in page text
        civil_indicators = ['civil', 'civ', 'civil cases', 'civil cause list']
        criminal_indicators = ['criminal', 'cri', 'criminal cases', 'criminal cause list']
        
        civil_count = sum(1 for indicator in civil_indicators if indicator in page_text.lower())
        criminal_count = sum(1 for indicator in criminal_indicators if indicator in page_text.lower())
        
        print(f"🔍 Civil indicators: {civil_count}, Criminal indicators: {criminal_count}")
        
        if civil_count > criminal_count:
            print("✅ Page analysis suggests Civil cases")
            return "Civil"
        elif criminal_count > civil_count:
            print("✅ Page analysis suggests Criminal cases") 
            return "Criminal"
        else:
            # Default to Civil if cannot determine
            print("🔄 Cannot determine from page analysis, defaulting to Civil")
            return "Civil"
            
     except Exception as e:
        print(f"❌ Page analysis failed: {e}")
        return "Civil"  # Default fallback

    def _check_case_type_success(self, case_type: str) -> bool:
     """Check if case type button click was successful"""
     # Check for errors first
     if self.check_for_popup_errors():
        print(f"❌ {case_type} submission failed due to error")
        return False
    
     # Check if URL changed (indicating form submission)
     current_url = self.driver.current_url
     if "cause_list/index" not in current_url:
        print(f"✅ URL changed - {case_type} submission successful")
        return True
    
     # Check for results table or case list
     if self.has_cause_list_content():
        print(f"✅ {case_type} cause list content detected")
        return True
    
     # Check for case type specific content in page
     try:
        page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        if (case_type.lower() in page_text and 
            any(keyword in page_text for keyword in ['case', 'cause list', 'viewos', 'viewas', 'dispTable'])):
            print(f"✅ {case_type} content verified in page text")
            return True
     except Exception as e:
        print(f"❌ Error checking page text: {e}")
    
     # Check for any tables with cases
     try:
        tables = self.driver.find_elements(By.TAG_NAME, "table")
        for table in tables:
            if table.is_displayed():
                table_text = table.text.lower()
                if any(term in table_text for term in ['case no', 'sr.no', 'party', 'advocate']):
                    print(f"✅ {case_type} cases table found")
                    return True
     except Exception as e:
        print(f"❌ Error checking tables: {e}")
    
     return False

    def detect_case_type(self) -> str:
     """Detect case type from page content using multiple methods"""
     try:
        page_content = self.driver.page_source.lower()
        current_url = self.driver.current_url.lower()
        
        # Method 1: Check URL for case type indicators
        url_indicators = {
            "civil": ["civil", "causelist_civil", "civil_cause"],
            "criminal": ["criminal", "causelist_criminal", "criminal_cause"]
        }
        
        for case_type, indicators in url_indicators.items():
            for indicator in indicators:
                if indicator in current_url:
                    print(f"✅ Detected {case_type} from URL indicator: {indicator}")
                    return case_type.capitalize()
        
        # Method 2: Check page content for specific patterns
        content_indicators = {
            "civil": [
                "original suits", "civil suit", "civil case", "civil application",
                "civil appeal", "execution case", "recovery suit", "declaration suit",
                "civil misc", "civil revision"
            ],
            "criminal": [
                "criminal appeal", "criminal revision", "criminal case", 
                "criminal complaint", "fir no", "police case", "bail application",
                "criminal misc"
            ]
        }
        
        for case_type, indicators in content_indicators.items():
            for indicator in indicators:
                if indicator in page_content:
                    print(f"✅ Detected {case_type} from content indicator: {indicator}")
                    return case_type.capitalize()
        
        # Method 3: Check for case number patterns that indicate civil cases
        civil_case_patterns = [
            r'viewos/\d+/\d+',  # Original Suits
            r'os/\d+/\d+',
            r'viewas/\d+/\d+',  # Appeal Suits
            r'as/\d+/\d+',
            r'execution/\d+/\d+',
            r'suit for declaration',
            r'civil first appeal',
            r'misc\. civil application',
            r'succession case'
        ]
        
        for pattern in civil_case_patterns:
            if re.search(pattern, page_content, re.IGNORECASE):
                print(f"✅ Detected Civil from case pattern: {pattern}")
                return "Civil"
        
        # Method 4: Check page title or headings
        try:
            title = self.driver.title.lower()
            if "civil" in title and "criminal" not in title:
                print("✅ Detected Civil from page title")
                return "Civil"
            elif "criminal" in title and "civil" not in title:
                print("✅ Detected Criminal from page title")
                return "Criminal"
        except:
            pass
            
        # Method 5: Look for specific buttons or text on the results page
        try:
            # Check if there are buttons to switch between civil/criminal
            civil_buttons = self.driver.find_elements(By.XPATH, 
                "//*[contains(text(), 'Civil') or contains(@value, 'Civil')]")
            criminal_buttons = self.driver.find_elements(By.XPATH,
                "//*[contains(text(), 'Criminal') or contains(@value, 'Criminal')]")
            
            if civil_buttons and not criminal_buttons:
                print("✅ Detected Civil from button presence")
                return "Civil"
            elif criminal_buttons and not civil_buttons:
                print("✅ Detected Criminal from button presence")
                return "Criminal"
        except:
            pass
            
     except Exception as e:
        print(f"🔍 Error detecting case type: {e}")
    
     return "Unknown"

    def has_cause_list_content(self) -> bool:
     """Check if the current page has cause list content"""
     try:
        # Method 1: Check for case tables
        tables = self.driver.find_elements(By.TAG_NAME, "table")
        for table in tables:
            if table.is_displayed():
                table_text = table.text.lower()
                # Look for indicators of cause list table
                if any(keyword in table_text for keyword in ['case', 'party', 'advocate', 'viewos', 'viewas', 'os/', 'as/']):
                    print("✅ Found cause list table with case data")
                    return True
        
        # Method 2: Check page content for case patterns
        page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        case_indicators = [
            'viewos/', 'viewas/', 'os/', 'as/', 'case no', 'case number',
            'sr.no', 'serial no', 'advocate', 'petitioner', 'respondent'
        ]
        
        for indicator in case_indicators:
            if indicator in page_text:
                print(f"✅ Found case indicator in page: {indicator}")
                return True
                
     except Exception as e:
        print(f"🔍 Error checking for cause list content: {e}")
    
     return False
    def check_for_popup_errors(self) -> bool:
        """Check for JavaScript popup errors and alert messages"""
        try:
            # Check for JavaScript alert messages FIRST
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text.lower()
                print(f"🔍 Alert detected: {alert_text}")
                
                # Handle common alerts
                if "selection valid upto one month" in alert_text or "1 month" in alert_text:
                    print("❌ Date restriction alert detected!")
                    alert.accept()  # Click OK on the alert
                    return True
                    
                alert.dismiss()  # Close other alerts
                return True
            except:
                pass  # No alert present
            
            # Check for error messages in page content
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
                    print(f"❌ Error detected: {error_msg}")
                    return True
                    
        except Exception as e:
            logger.debug(f"Error checking for popups: {e}")
        
        return False

    def check_for_errors(self) -> bool:
        """Check for common error messages on the page"""
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            error_indicators = [
                "invalid request",
                "something went wrong",
                "no record found",
                "no cases found",
                "error",
                "oops",
                "try again",
                "session expired"
            ]
            
            for error in error_indicators:
                if error in body_text:
                    logger.warning("Error detected on page: %s", error)
                    return True
                    
            # Check for success indicators
            success_indicators = [
                "cause list",
                "case list", 
                "displaying",
                "records found",
                "viewos",
                "viewas"
            ]
            
            for success in success_indicators:
                if success in body_text:
                    return False
                    
            # If no clear indicators, assume it might be an error page
            return "select state" in body_text and "select district" in body_text
            
        except Exception:
            return False


    def solve_captcha_ocr(self, captcha_element) -> Optional[str]:
     """
     Improved OCR-based CAPTCHA solver for 6-character CAPTCHAs with higher accuracy.
     """
     if not OCR_AVAILABLE:
        print("❌ OCR not available")
        return None

     try:
        from PIL import Image, ImageEnhance, ImageFilter
        import io, base64
        import numpy as np
        import cv2

        # --- Load image ---
        src = captcha_element.get_attribute('src')
        if src and src.startswith('data:image'):
            base64_data = src.split(',')[1]
            image_data = base64.b64decode(base64_data)
            image = Image.open(io.BytesIO(image_data))
        else:
            screenshot = captcha_element.screenshot_as_png
            image = Image.open(io.BytesIO(screenshot))

        # --- Convert to OpenCV format ---
        img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # --- Enhance contrast and sharpness ---
        pil_img = Image.fromarray(gray)
        pil_img = ImageEnhance.Contrast(pil_img).enhance(2.0)
        pil_img = ImageEnhance.Sharpness(pil_img).enhance(2.0)
        gray = np.array(pil_img)

        # --- Scale up image to help OCR ---
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        # --- Apply multiple thresholds ---
        blur = cv2.medianBlur(gray, 3)
        _, thresh_otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresh_adapt = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                             cv2.THRESH_BINARY, 11, 2)
        # Morphology
        kernel = np.ones((2,2), np.uint8)
        for thresh in [thresh_otsu, thresh_adapt]:
            thresh = cv2.dilate(thresh, kernel, iterations=1)
            thresh = cv2.erode(thresh, kernel, iterations=1)

            # --- OCR with multiple PSM ---
            image_proc = Image.fromarray(thresh)
            for psm in [7, 8]:
                custom_config = f'--oem 3 --psm {psm} -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyz0123456789'
                captcha_text = pytesseract.image_to_string(image_proc, config=custom_config)
                captcha_text = ''.join(c for c in captcha_text if c.isalnum()).strip().lower()
                if len(captcha_text) == 6:
                    print(f"✅ OCR solved CAPTCHA: {captcha_text} (PSM {psm})")
                    return captcha_text

        print(f"⚠️ OCR failed or invalid length: '{captcha_text}'")
        self.refresh_captcha()
        return None

     except Exception as e:
        print(f"❌ OCR CAPTCHA failed: {e}")
        import traceback
        traceback.print_exc()
        return None



    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    def solve_captcha_with_user_choice(self, max_attempts: int = 6) -> bool:
     for attempt in range(1, max_attempts + 1):
        print(f"\n⏳ CAPTCHA attempt {attempt}/{max_attempts}")
        human_delay(2, 3)

        # Step 1: Locate CAPTCHA image
        captcha_elem = None
        captcha_selectors = [
            "//img[contains(@src,'captcha')]",
            "//img[contains(@id,'captcha')]",
            "//img[contains(@class,'captcha')]",
            "//img[@id='captchaImage']"
        ]
        for sel in captcha_selectors:
            try:
                elems = self.driver.find_elements(By.XPATH, sel)
                for elem in elems:
                    if elem.is_displayed():
                        captcha_elem = elem
                        break
                if captcha_elem:
                    break
            except:
                continue

        if not captcha_elem:
            print("❌ CAPTCHA image not found")
            continue

        # Step 2: Solve CAPTCHA
        captcha_text = self.solve_captcha_ocr(captcha_elem)
        if not captcha_text:
            print("⚠️ OCR failed, refreshing CAPTCHA...")
            self.refresh_captcha()
            continue

        # Step 3: Enter CAPTCHA
        try:
            inp = self.driver.find_element(By.XPATH, "//input[contains(@id,'captcha') or contains(@name,'captcha')]")
            inp.clear()
            human_delay(0.5, 1.0)
            inp.send_keys(captcha_text)
            print(f"✅ Entered CAPTCHA: {captcha_text}")
        except Exception as e:
            print(f"❌ Failed to enter CAPTCHA: {e}")
            continue

        # Step 4: Ask user for Civil or Criminal
        while True:
            user_choice = input("Enter case type (civ/cri): ").strip().lower()
            if user_choice in ["civ", "cri"]:
                break
            print("❌ Invalid choice. Enter 'civ' or 'cri'.")

        # Step 5: Click the button
        try:
            btn_xpath = f"//button[contains(@onclick,'{user_choice}')]"
            btn = self.driver.find_element(By.XPATH, btn_xpath)
            if btn.is_displayed() and btn.is_enabled():
                btn.click()
                print(f"🔄 Clicked {user_choice.upper()} button")
                human_delay(2, 3)
        except Exception as e:
            print(f"❌ Could not click {user_choice.upper()} button: {e}")
            continue

        # Step 6: Validate CAPTCHA by checking for page text
        try:
            success_text = "Civil Cases Listed on"
            WebDriverWait(self.driver, 7).until(
                lambda d: success_text in d.page_source
            )
            print("✅ CAPTCHA passed — results page loaded successfully!")
            return True
        except:
            print("⚠️ CAPTCHA may have failed, text not found.")
            self.refresh_captcha()
            human_delay(2, 3)

     print("❌ CAPTCHA failed after all attempts")
     return False








    def download_cause_list_pdf(self, output_filename: str = None) -> Optional[str]:
     """Download the cause list PDF from the current page"""
     try:
        # Look for PDF download buttons/links on the cause list page
        pdf_selectors = [
            (By.XPATH, "//a[contains(@href, '.pdf')]"),
            (By.XPATH, "//a[contains(text(), 'PDF')]"),
            (By.XPATH, "//a[contains(text(), 'Download')]"),
            (By.XPATH, "//button[contains(text(), 'PDF')]"),
            (By.XPATH, "//button[contains(text(), 'Download')]"),
            (By.XPATH, "//a[contains(@onclick, 'pdf')]"),
            (By.XPATH, "//a[contains(@href, 'download')]"),
        ]
        
        pdf_url = None
        pdf_element = None
        
        # Try to find PDF download link
        for by, selector in pdf_selectors:
            try:
                elements = self.driver.find_elements(by, selector)
                for element in elements:
                    if element.is_displayed():
                        # Get the PDF URL
                        if by[0] == By.XPATH and "href" in selector:
                            href = element.get_attribute('href')
                            if href and '.pdf' in href.lower():
                                pdf_url = href
                                pdf_element = element
                                break
                        else:
                            # For buttons, we might need to click and handle download
                            pdf_element = element
                            break
                if pdf_url or pdf_element:
                    break
            except Exception:
                continue
        
        if not pdf_url and not pdf_element:
            print("❌ No PDF download link found on the page")
            return None
        
        # Generate output filename if not provided
        if not output_filename:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"cause_list_{timestamp}.pdf"
        
        output_path = BASE_DIR / output_filename
        
        # If we have a direct PDF URL, download it
        if pdf_url:
            print(f"📥 Downloading PDF from: {pdf_url}")
            try:
                response = requests.get(pdf_url, stream=True, timeout=30)
                response.raise_for_status()
                
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                
                print(f"✅ PDF successfully downloaded to: {output_path}")
                return str(output_path)
                
            except Exception as e:
                print(f"❌ Direct PDF download failed: {e}")
                # Fall back to browser download
        
        # If no direct URL or download failed, try browser interaction
        if pdf_element:
            print("🔄 Using browser to download PDF...")
            try:
                # Click the PDF download element
                pdf_element.click()
                human_delay(5, 8)  # Wait for download
                
                # Check if PDF opened in new tab/window
                if len(self.driver.window_handles) > 1:
                    # Switch to new tab
                    self.driver.switch_to.window(self.driver.window_handles[1])
                    
                    # Get current URL which might be the PDF
                    current_url = self.driver.current_url
                    if current_url.endswith('.pdf'):
                        # Download the PDF
                        response = requests.get(current_url, stream=True, timeout=30)
                        response.raise_for_status()
                        
                        with open(output_path, 'wb') as f:
                            for chunk in response.iter_content(8192):
                                f.write(chunk)
                        
                        print(f"✅ PDF successfully downloaded to: {output_path}")
                        
                        # Close the tab and switch back
                        self.driver.close()
                        self.driver.switch_to.window(self.driver.window_handles[0])
                        return str(output_path)
                    
                    # Close the tab if not PDF
                    self.driver.close()
                    self.driver.switch_to.window(self.driver.window_handles[0])
                
                print("⚠️ PDF download initiated in browser, please check downloads folder")
                return "browser_download"
                
            except Exception as e:
                print(f"❌ Browser PDF download failed: {e}")
        
        return None
        
     except Exception as e:
        print(f"❌ PDF download error: {e}")
        return None
    def refresh_captcha(self) -> bool:
     """Click the refresh button to get new CAPTCHA."""
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
                    print("🔄 CAPTCHA refreshed successfully")
                    human_delay(2, 4)  # wait for new CAPTCHA to load
                    return True
            except:
                continue
        print("❌ Could not find refresh button")
        return False
     except Exception as e:
        print(f"❌ Error refreshing CAPTCHA: {e}")
        return False


    def check_captcha_validation(self) -> bool:
  
     try:
        human_delay(2, 3)  # Wait for page to fully load after button click
        
        # Step 1: Check for explicit failure popup (Image 2 shows this)
        # "Invalid Captcha..." alert box
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
                        error_text = elem.text.strip()
                        print(f"❌ CAPTCHA failed - {desc}: {error_text}")
                        return False
            except:
                pass
        
        # Step 2: Check if CAPTCHA input field is still visible
        # If input is still present and visible, CAPTCHA wasn't accepted
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
                        # Check if it's empty (cleared by page after success) or still has placeholder
                        value = inp.get_attribute('value')
                        if value and len(value.strip()) > 0:
                            print("⚠️ CAPTCHA input still has value - likely failed")
                            return False
            except:
                pass
        
        # Step 3: Check for success indicators - look for cause list table/data
        # Images 1, 3, 4 show the result after successful CAPTCHA
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
                    print(f"✅ CAPTCHA success - {desc} detected")
                    return True
            except:
                pass
        
        # Step 4: Check for "Record not found" message (Image 3)
        # This means CAPTCHA passed but no matching records
        try:
            record_not_found = self.driver.find_element(By.XPATH, "//div[contains(text(),'Record not found')]")
            if record_not_found.is_displayed():
                print("✅ CAPTCHA passed - 'Record not found' message shown")
                return True
        except:
            pass
        
        # Step 5: Check page body text for content change
        # After successful CAPTCHA, page loads cause list content
        body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        success_keywords = [
            "principal district judge",
            "civil cases listed",
            "sr no", "cases", "party name", "advocate",
            "record not found",  # Valid success state
            "urgent cases", "awaited"
        ]
        
        keyword_count = sum(1 for kw in success_keywords if kw in body_text)
        if keyword_count >= 2:
            print(f"✅ CAPTCHA passed - found {keyword_count} success keywords in page")
            return True
        
        # Step 6: URL check as fallback
        # Should remain on cause_list page after success
        current_url = self.driver.current_url.lower()
        if "cause_list" in current_url and "index" in current_url:
            print(f"✅ CAPTCHA likely passed - still on cause list page")
            return True
        
        print("❌ CAPTCHA validation inconclusive - no clear success or failure indicators")
        return False
        
     except Exception as e:
        print(f"⚠️ Error during CAPTCHA validation: {e}")
        import traceback
        traceback.print_exc()
        return False


    def captcha_terminal_or_ocr(self, max_attempts: int = 6) -> bool:
  
     for attempt in range(1, max_attempts + 1):
        print(f"\n⏳ CAPTCHA attempt {attempt}/{max_attempts}")
        human_delay(2, 4)

        # Locate CAPTCHA image
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
                        print(f"✅ CAPTCHA image found")
                        break
                if captcha_elem:
                    break
            except:
                continue

        if not captcha_elem:
            print("❌ CAPTCHA image not found")
            self.refresh_captcha()
            continue

        # Solve CAPTCHA with OCR
        captcha_text = self.solve_captcha_ocr(captcha_elem)
        if not captcha_text:
            print("❌ OCR failed, refreshing CAPTCHA")
            self.refresh_captcha()
            continue
        print(f"✅ OCR result: {captcha_text}")

        # Find and fill input field
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
            print("❌ CAPTCHA input field not found")
            continue

        try:
            inp.clear()
            human_delay(0.3, 0.6)
            inp.send_keys(captcha_text)
            print(f"✅ Entered CAPTCHA")
        except Exception as e:
            print(f"❌ Failed to enter CAPTCHA: {e}")
            continue

        # Get case type from user
        while True:
            user_choice = input("Enter case type (civ/cri): ").strip().lower()
            if user_choice in ["civ", "cri"]:
                break
            print("❌ Invalid choice. Enter 'civ' or 'cri'.")

        # Click appropriate button
        try:
            case_type = "Civil" if user_choice == "civ" else "Criminal"
            btn = self.driver.find_element(By.XPATH, f"//button[contains(text(),'{case_type}')]")
            if btn.is_displayed() and btn.is_enabled():
                btn.click()
                print(f"🔄 Clicked {case_type} button")
            else:
                print(f"❌ {case_type} button not clickable")
                continue
        except Exception as e:
            print(f"❌ Could not click button: {e}")
            continue

        human_delay(3, 5)

        # Validate CAPTCHA with improved method
        if self.check_captcha_validation():
            print("✅ CAPTCHA solved and validated successfully!")
            return True
        else:
            print("❌ CAPTCHA validation failed, retrying...")
            self.refresh_captcha()

     print("❌ CAPTCHA failed after all attempts")
     return False
    def check_captcha_popup(self) -> bool:
     """Check if a popup or message indicates CAPTCHA failure, then confirm success via URL."""
     try:
        # Step 1: Check for common failure popups/messages
        popup_selectors = [
            "//div[contains(@class,'alert') and contains(text(),'captcha')]",
            "//div[contains(@class,'modal') and contains(text(),'captcha')]",
            "//span[contains(text(),'Invalid Captcha')]",
            "//div[contains(@class,'toast') and contains(text(),'captcha')]"
        ]
        for sel in popup_selectors:
            elems = self.driver.find_elements(By.XPATH, sel)
            for e in elems:
                if e.is_displayed():
                    print(f"❌ CAPTCHA failed popup detected: {e.text}")
                    return False  # CAPTCHA definitely failed

        # Step 2: No failure popups → check URL for success indicators
        current_url = self.driver.current_url.lower()
        success_keywords = ["display", "list", "result", "view"]  # adjust based on your site
        if any(keyword in current_url for keyword in success_keywords):
            print(f"✅ CAPTCHA likely passed: URL changed to {current_url}")
            return True

        # Step 3: Optional fallback: assume success if no popup and page changed visually
        print("✅ CAPTCHA likely passed (no popups detected, URL not explicitly changed)")
        return True

     except Exception as e:
        print(f"⚠️ Error checking CAPTCHA popup: {e}")
        return False

    def extract_cases_using_beautifulsoup(self) -> List[Dict]:
        """Extract cases using BeautifulSoup from the current page with multiple strategies"""
        try:
            # Get page HTML
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            # Save HTML for debugging
            debug_file = BASE_DIR / "debug_page.html"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"Saved page HTML to: {debug_file}")
            
            cases = extract_cases_from_soup(soup)
            print(f"Extracted {len(cases)} cases using BeautifulSoup")
            
            # If no cases found, try to get text content directly
            if not cases:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                print("Page text content (first 1000 chars):")
                print(page_text[:1000])
                
                # Try text-based parsing
                cases = parse_cases_from_text(page_text)
                print(f"Extracted {len(cases)} cases from text parsing")
            
            return cases
            
        except Exception as e:
            print(f"Error extracting cases with BeautifulSoup: {e}")
            return []

    def fetch_cause_list_live(self, district: str, date_obj: datetime.date, specific_judge: str = None) -> List[Dict]:
     """Full interactive flow for cause list - returns cases for single judge"""
     # If a specific judge is provided, use it; otherwise do interactive selection
     if specific_judge:
        print(f"🔄 Processing specific judge: {specific_judge}")
        judge_selected = specific_judge
     else:
        # Do the interactive selection flow
        self.open_page()
        
        # State select
        state_selected = self.interactive_select_from((By.ID, "sess_state_code"), "State")
        if not state_selected:
            raise RuntimeError("State selection failed")
        
        # Wait for district dropdown to load
        human_delay(2.0, 3.0)
            
        district_selected = self.interactive_select_from((By.ID, "sess_dist_code"), "District")
        if not district_selected:
            raise RuntimeError("District selection failed")
        
        # Wait for court complex dropdown to load
        human_delay(2.0, 3.0)
            
        complex_selected = self.interactive_select_from((By.ID, "court_complex_code"), "Court Complex")
        if not complex_selected:
            raise RuntimeError("Court complex selection failed")

        # Wait for judge dropdown to load
        human_delay(2.0, 3.0)

        # Judge selection (single mode)
        selected_judges = self.interactive_court_judge_selection(select_all=False)
        if not selected_judges:
            raise RuntimeError("Judge selection failed")
        
        judge_selected = selected_judges[0]

     # Rest of the method remains the same for single court processing
     # Wait before setting date
     human_delay(1.0, 2.0)

     # **ENFORCE DATE RESTRICTION AND USE CORRECT FORMAT**
     today = datetime.date.today()
     max_allowed_date = today + datetime.timedelta(days=30)
    
     if date_obj > max_allowed_date:
        print(f"❌ Date {date_obj} is beyond 1 month limit.")
        print(f"🔄 Using maximum allowed date: {max_allowed_date}")
        date_obj = max_allowed_date

     print(f"📅 Final date being used: {date_obj.strftime('%d-%m-%Y')} (DD-MM-YYYY)")
    
     if not self.set_date_mmddyyyy(date_obj):
        print("❌ Failed to set requested date, trying today instead")
        date_obj = datetime.date.today()
        print(f"📅 Using today's date: {date_obj.strftime('%d-%m-%Y')}")
        if not self.set_date_mmddyyyy(date_obj):
            raise RuntimeError("Date setting failed")

     # Wait before CAPTCHA
     human_delay(1.0, 2.0)
    
     # CAPTCHA handling
     if not self.captcha_terminal_or_ocr(max_attempts=8):
        raise RuntimeError("CAPTCHA failed")

     # Wait before case type selection
     human_delay(1.0, 2.0)

     # MANUAL CASE TYPE SELECTION
     print("🔄 Automatically selecting case type...")
     case_type = self.select_case_type_prompt()

     # Handle date restriction error
     if case_type == "DateError":
        print("\n🚫 CANNOT PROCEED - Date restriction!")
        print("The website blocks dates beyond 1 month from today.")
        print(f"Today is: {datetime.date.today()}")
        print(f"Maximum allowed: {max_allowed_date}")
        print("Please run with: --when today")
        return []
    
     # Handle form page error (still on form after click)
     if case_type == "FormPage":
        print("\n🚫 Form submission failed!")
        print("Possible reasons:")
        print("1. No cases scheduled for this court/date")
        print("2. Court may be closed/holiday")
        print("3. Try different judge or 'today' date")
        return []

     # If we got a valid case type (Civil, Criminal, or Unknown), proceed to extract cases
     print(f"\n✅ Proceeding with case type: {case_type}")
    
     # Wait for results to fully load
     print("⏳ Waiting for cause list to fully load...")
     human_delay(5.0, 8.0)

     # Extract cases
     print("⏳ Extracting cases...")
     cases = self.extract_cases_using_beautifulsoup()
    
     # **VALIDATE CASE TYPE BASED ON EXTRACTED CASES**
     if case_type == "Unknown":
        # Try to determine case type from the actual cases extracted
        case_type_from_cases = self.determine_case_type_from_cases(cases)
        if case_type_from_cases != "Unknown":
            print(f"🔄 Determined case type from cases: {case_type_from_cases}")
            case_type = case_type_from_cases
    
     # Add metadata to cases
     for case in cases:
        case['court_name'] = judge_selected
        case['date'] = date_obj.strftime("%Y-%m-%d")
        case['case_type'] = case_type
        case['district'] = district_selected if 'district_selected' in locals() else district
    
     return cases
    def determine_case_type_from_cases(self, cases: List[Dict]) -> str:
     """Determine case type based on the extracted cases"""
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
     
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch     
def generate_pdf_from_cases(cases: List[Dict], output_filename: str, court_name: str, date: str, case_type: str):
    """Generate a professional PDF cause list from scraped cases"""
    try:
        # Create output path
        output_path = BASE_DIR / output_filename
        
        # Create PDF document
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )
        
        # Story to hold content
        story = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1,  # Center
            textColor=colors.darkblue
        )
        
        title_text = f"CAUSE LIST - {court_name}"
        story.append(Paragraph(title_text, title_style))
        
        # Court and date info
        info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=20,
            alignment=1
        )
        
        info_text = f"Court: {court_name}<br/>Date: {date}<br/>Case Type: {case_type}"
        story.append(Paragraph(info_text, info_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Prepare table data
        table_data = [['Sr No', 'Case Number', 'Parties', 'Advocate']]
        
        for case in cases:
            # Clean and truncate long text for PDF
            serial = str(case.get('serial', ''))[:10]
            case_number = str(case.get('case_number', ''))[:30]
            parties = str(case.get('party_name', case.get('parties', '')))[:50] + "..." if len(str(case.get('party_name', case.get('parties', '')))) > 50 else str(case.get('party_name', case.get('parties', '')))
            advocate = str(case.get('advocate', ''))[:30]
            
            table_data.append([serial, case_number, parties, advocate])
        
        # Create table
        table = Table(table_data, colWidths=[0.8*inch, 2.2*inch, 3.2*inch, 1.8*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
        ]))
        
        story.append(table)
        
        # Footer
        story.append(Spacer(1, 0.3*inch))
        footer_style = ParagraphStyle(
            'FooterStyle',
            parent=styles['Normal'],
            fontSize=8,
            alignment=1,
            textColor=colors.grey
        )
        footer_text = f"Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Cases: {len(cases)}"
        story.append(Paragraph(footer_text, footer_style))
        
        # Build PDF
        doc.build(story)
        print(f"✅ PDF generated successfully: {output_path}")
        return str(output_path)
        
    except Exception as e:
        print(f"❌ PDF generation failed: {e}")
        import traceback
        traceback.print_exc()
        return None
# ---- Command Functions ----
def live_scraping_command(args):
    """Live scraping from eCourts website with batch processing option"""
    # Default to today if tomorrow causes issues
    try:
        date_obj = ensure_date_object(args.when)
    except Exception as e:
        print(f"Date error: {e}, defaulting to today")
        date_obj = datetime.date.today()
    
    # Create Browser instance
    browser = Browser(headless=args.headless, download_dir=str(BASE_DIR))
    
    try:
        cls = CauseListScraper(browser, ocr_captcha=True)
        
        # Open page and do initial selections
        cls.open_page()
        
        # State select
        state_selected = cls.interactive_select_from((By.ID, "sess_state_code"), "State")
        if not state_selected:
            raise RuntimeError("State selection failed")
        
        # Wait for district dropdown to load
        human_delay(2.0, 3.0)
            
        district_selected = cls.interactive_select_from((By.ID, "sess_dist_code"), "District")
        if not district_selected:
            raise RuntimeError("District selection failed")
        
        # Wait for court complex dropdown to load
        human_delay(2.0, 3.0)
            
        complex_selected = cls.interactive_select_from((By.ID, "court_complex_code"), "Court Complex")
        if not complex_selected:
            raise RuntimeError("Court complex selection failed")

        # Wait for judge dropdown to load
        human_delay(2.0, 3.0)

        # JUDGE SELECTION WITH ALL OPTION
        print("\n" + "="*60)
        print("🎯 COURT/JUDGE SELECTION")
        print("="*60)

        # Ask user if they want batch mode first
        print("\n🎯 SELECTION MODE:")
        print("1. Single court/judge (process one)")
        print("2. ALL courts/judges (batch process all)")

        while True:
            mode_choice = input("Choose mode (1 or 2): ").strip()
            if mode_choice in ['1', '2']:
                break
            print("❌ Invalid choice. Enter 1 or 2.")

        # Call with appropriate mode
        if mode_choice == '2':
            print("🔄 Batch mode selected - will process ALL courts/judges")
            selected_judges = cls.interactive_court_judge_selection(select_all=True)
        else:
            print("🔄 Single mode selected - will process one court/judge")
            selected_judges = cls.interactive_court_judge_selection(select_all=False)
        
        if not selected_judges:
            raise RuntimeError("No judges selected")
        
        # Check if we're processing all judges or just one
        if len(selected_judges) > 1:
            # BATCH PROCESSING MODE - Process all selected judges
            print(f"🔄 Starting batch processing for {len(selected_judges)} courts/judges...")
            
            # Process all courts
            all_results = cls.process_all_courts_batch(args.district, date_obj, selected_judges)
            
            # Save results
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            total_cases = 0
            
            for judge, cases in all_results.items():
                if cases:
                    # Create safe filename
                    safe_judge_name = re.sub(r'[^\w\s-]', '', judge).strip().replace(' ', '_')
                    filename_prefix = f'court_{safe_judge_name}_{timestamp}'
                    
                    # Save individual court results
                    csv_path, json_path = save_results(cases, filename_prefix)
                    total_cases += len(cases)
                    
                    # Generate PDF for this court
                    print(f"📄 Generating PDF for {judge}...")
                    pdf_filename = f"cause_list_{safe_judge_name}_{timestamp}.pdf"
                    date_str = cases[0].get('date', date_obj.strftime('%Y-%m-%d'))
                    case_type = cases[0].get('case_type', 'Unknown')
                    
                    pdf_path = generate_pdf_from_cases(cases, pdf_filename, judge, date_str, case_type)
                    if pdf_path:
                        print(f"✅ PDF generated: {pdf_path}")
            
            # Save combined results
            if total_cases > 0:
                all_cases = []
                for cases in all_results.values():
                    all_cases.extend(cases)
                
                combined_csv, combined_json = save_results(all_cases, f'all_courts_combined_{timestamp}')
                print(f"\n🎉 BATCH PROCESSING COMPLETE!")
                print(f"📊 Total cases across all courts: {total_cases}")
                print(f"📁 Individual files saved for each court")
                print(f"📦 Combined file: {combined_csv}")
            else:
                print("❌ No cases found in batch processing")
                
        else:
            # SINGLE COURT MODE
            judge = selected_judges[0]
            print(f"🔄 Processing single court: {judge}")
            
            # Continue with single court processing
            human_delay(1.0, 2.0)

            # Set date
            if not cls.set_date_mmddyyyy(date_obj):
                print("❌ Failed to set date")
                return

            # Handle CAPTCHA
            human_delay(1.0, 2.0)
            if not cls.captcha_terminal_or_ocr(max_attempts=8):
                raise RuntimeError("CAPTCHA failed")

            # Select case type
            human_delay(1.0, 2.0)
            case_type = cls.select_case_type_prompt()

            if case_type in ["DateError", "FormPage"]:
                print("❌ Case type selection failed")
                return

            # Extract cases
            print("⏳ Waiting for cause list to fully load...")
            human_delay(5.0, 8.0)

            print("⏳ Extracting cases...")
            cases = cls.extract_cases_using_beautifulsoup()
            
            # Add metadata to cases
            for case in cases:
                case['court_name'] = judge
                case['date'] = date_obj.strftime("%Y-%m-%d")
                case['case_type'] = case_type
                case['district'] = district_selected
            
            if cases:
                print(f"\n✅ Successfully extracted {len(cases)} cases:")
                for case in cases[:5]:
                    print(f"  {case.get('serial', 'N/A')} | {case.get('case_number', 'N/A')} | {case.get('party_name', 'N/A')}")
                if len(cases) > 5:
                    print(f"  ... and {len(cases) - 5} more cases")
                
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_path, json_path = save_results(cases, f'live_cause_list_{timestamp}')
                
                # PDF generation
                print("\n📥 Generate PDF report?")
                generate_pdf = input("Generate PDF report? (y/n): ").strip().lower()
                
                if generate_pdf in ['y', 'yes']:
                    court_name = cases[0].get('court_name', 'Unknown Court') if cases else 'Unknown Court'
                    date_str = cases[0].get('date', date_obj.strftime('%Y-%m-%d')) if cases else date_obj.strftime('%Y-%m-%d')
                    case_type = cases[0].get('case_type', 'Unknown') if cases else 'Unknown'
                    
                    pdf_filename = f"cause_list_report_{timestamp}.pdf"
                    pdf_path = generate_pdf_from_cases(cases, pdf_filename, court_name, date_str, case_type)
                    
                    if pdf_path:
                        print(f"🎉 PDF report generated: {pdf_path}")
            else:
                print("❌ No cases found")
            
    except Exception as e:
        print(f"\n💥 Error during scraping: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        try:
            browser.close()
        except:
            pass
def fetch_causelist(args):
    """Fetch cause list from saved HTML file"""
    html_file = args.htmlfile
    if args.today:
        print("Fetching today's cause list from saved HTML...")
    elif args.tomorrow:
        print("Fetching tomorrow's cause list from saved HTML...")
    else:
        print("Date not specified; defaulting to today's cause list...")
    
    cases = fetch_cause_list_from_html(html_file)
    if not cases:
        print("No cases found or invalid HTML file.")
        return
    
    print(f"Extracted {len(cases)} cases:")
    for case in cases:
        print(f"{case['serial']} | {case['case_number']} | {case['parties']} | {case['advocate']}")
    
    save_results(cases, 'cause_list')

def download_pdf_command(args):
    """Download PDF with manual CAPTCHA handling"""
    pdf_url = args.url
    output_path = args.output or "downloaded_cause_list.pdf"
    
    if download_pdf_manual_captcha(pdf_url, output_path):
        print(f"PDF successfully downloaded to: {output_path}")
    else:
        print("PDF download failed.")

# ---- CLI Setup ----
def build_arg_parser():
    p = argparse.ArgumentParser(description="eCourts Scraper - Unified CLI")
    
    # Create subparsers for different commands
    subparsers = p.add_subparsers(dest='command', help='Available commands')
    
    # Live scraping command
    live_parser = subparsers.add_parser('live', help='Live scraping from eCourts website')
    live_parser.add_argument("--district", required=True, help="District name")
    live_parser.add_argument("--when", default="today", help="today, tomorrow, or YYYY-MM-DD")
    live_parser.add_argument("--headless", action="store_true", help="Run headless")
    live_parser.add_argument("--ocr-captcha", action="store_true", help="Try OCR to auto-solve captcha")
    
    # HTML parsing command
    html_parser = subparsers.add_parser('html', help='Parse cause list from saved HTML file')
    html_parser.add_argument('htmlfile', help='Path to HTML file containing cause list')
    html_parser.add_argument('--today', action='store_true', help='Mark as today\'s cause list')
    html_parser.add_argument('--tomorrow', action='store_true', help='Mark as tomorrow\'s cause list')
    
    # PDF download command
    pdf_parser = subparsers.add_parser('pdf', help='Download PDF cause list')
    pdf_parser.add_argument('url', help='URL of the PDF to download')
    pdf_parser.add_argument('--output', help='Output path for downloaded PDF')
    
    return p

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == 'live':
        live_scraping_command(args)
    elif args.command == 'html':
        fetch_causelist(args)
    elif args.command == 'pdf':
        download_pdf_command(args)

if __name__ == "__main__":
    main()