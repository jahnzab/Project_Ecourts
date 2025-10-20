

# import os
# import json
# import datetime
# from flask import Flask, render_template, request, jsonify, send_file, session
# from pathlib import Path
# import threading
# import time
# from selenium.webdriver.common.by import By
# from imp import (
#     Browser, CauseListScraper, ensure_date_object, 
#     save_results, generate_pdf_from_cases, BASE_DIR
# )

# app = Flask(__name__)
# app.secret_key = 'your-secret-key-here'
# app.config['SESSION_TYPE'] = 'filesystem'

# active_sessions = {}

# class InteractiveScrapingSession:
#     def __init__(self, session_id, district, when, headless=False):
#         self.session_id = session_id
#         self.district = district
#         self.when = when
#         self.headless = headless
#         self.status = "idle"
#         self.current_step = "initializing"
#         self.progress = 0
#         self.message = ""
#         self.cases = []
#         self.error = None
#         self.browser = None
#         self.scraper = None
#         self.date_obj = None
        
#         self.available_states = []
#         self.available_districts = []
#         self.available_complexes = []
#         self.available_judges = []
#         self.case_type_options = ["Civil", "Criminal"]
        
#         self.selected_state = None
#         self.selected_district = None
#         self.selected_complex = None
#         self.selected_judge = None
#         self.selected_case_type = None
        
#         # Store for CSV/PDF output
#         self.output_state = None
#         self.output_district = None
#         self.output_complex = None
        
#         self.step_completed = {
#             "browser_init": False,
#             "page_load": False,
#             "state_selection": False,
#             "district_selection": False,
#             "complex_selection": False,
#             "judge_selection": False,
#             "date_setting": False,
#             "captcha_solving": False,
#             "case_type_selection": False,
#             "scraping": False
#         }
        
#         self.waiting_for_input = False
#         self.waiting_for_input_type = None

#     def update_status(self, step, progress, message, **kwargs):
#         self.current_step = step
#         self.progress = progress
#         self.message = message
#         self.waiting_for_input = False
#         self.waiting_for_input_type = None
        
#         if 'available_states' in kwargs:
#             self.available_states = kwargs['available_states']
#         if 'available_districts' in kwargs:
#             self.available_districts = kwargs['available_districts']
#         if 'available_complexes' in kwargs:
#             self.available_complexes = kwargs['available_complexes']
#         if 'available_judges' in kwargs:
#             self.available_judges = kwargs['available_judges']

#     def set_waiting_for_input(self, step, progress, message, input_type, options=None):
#         """Set session to wait for user input - BLOCKING"""
#         self.current_step = step
#         self.progress = progress
#         self.message = message
#         self.waiting_for_input = True
#         self.waiting_for_input_type = input_type
        
#         if options is None:
#             options = []
        
#         if input_type == 'state':
#             self.available_states = options
#         elif input_type == 'district':
#             self.available_districts = options
#         elif input_type == 'complex':
#             self.available_complexes = options
#         elif input_type == 'judge':
#             self.available_judges = options
#         elif input_type == 'case_type':
#             self.case_type_options = options

#     def clear_selection(self, input_type):
#         """Clear a selection after it's been processed"""
#         if input_type == 'state':
#             self.selected_state = None
#         elif input_type == 'district':
#             self.selected_district = None
#         elif input_type == 'complex':
#             self.selected_complex = None
#         elif input_type == 'judge':
#             self.selected_judge = None
#         elif input_type == 'case_type':
#             self.selected_case_type = None

#     def set_error(self, error):
#         self.status = "error"
#         self.error = error
#         self.waiting_for_input = False
#         self.waiting_for_input_type = None

#     def set_results(self, cases):
#         self.cases = cases
#         self.status = "completed"
#         self.current_step = "completed"
#         self.waiting_for_input = False
#         self.waiting_for_input_type = None

#     def get_step_data(self):
#         return {
#             'current_step': self.current_step,
#             'progress': self.progress,
#             'message': self.message,
#             'available_states': self.available_states,
#             'available_districts': self.available_districts,
#             'available_complexes': self.available_complexes,
#             'available_judges': self.available_judges,
#             'case_type_options': self.case_type_options,
#             'requires_user_input': self.waiting_for_input,
#             'user_input_type': self.waiting_for_input_type
#         }


# def wait_for_user_selection(scraping_session, selection_key, timeout=120):
#     """
#     Wait for user to make a selection with SLOW checking.
    
#     Checks every 15 seconds ONLY - gives user plenty of time to:
#     1. Click dropdown/button
#     2. Read options  
#     3. Select one
#     4. Click confirm button
    
#     This timeout is 2 minutes per dropdown.
    
#     Args:
#         scraping_session: The session object
#         selection_key: 'state', 'district', 'complex', 'judge', or 'case_type'
#         timeout: Maximum seconds to wait (default 2 minutes = 120 seconds)
    
#     Returns:
#         True if selection made, False if timeout or cancelled
#     """
#     start_time = time.time()
#     check_number = 0
    
#     print(f"\n⏳ WAITING FOR {selection_key.upper()} (checking every 15 seconds, timeout {timeout}s)")
    
#     while time.time() - start_time < timeout:
#         # Check every 15 seconds ONLY - not more frequently
#         time.sleep(15)
#         check_number += 1
#         elapsed = int(time.time() - start_time)
        
#         print(f"   Check #{check_number} at {elapsed}s: ", end="")
        
#         # Check if selection was made
#         if selection_key == 'state' and scraping_session.selected_state:
#             print(f"✅ SELECTED")
#             print(f"✅ State received: {scraping_session.selected_state}\n")
#             return True
#         elif selection_key == 'district' and scraping_session.selected_district:
#             print(f"✅ SELECTED")
#             print(f"✅ District received: {scraping_session.selected_district}\n")
#             return True
#         elif selection_key == 'complex' and scraping_session.selected_complex:
#             print(f"✅ SELECTED")
#             print(f"✅ Complex received: {scraping_session.selected_complex}\n")
#             return True
#         elif selection_key == 'judge' and scraping_session.selected_judge:
#             print(f"✅ SELECTED")
#             print(f"✅ Judge received: {scraping_session.selected_judge}\n")
#             return True
#         elif selection_key == 'case_type' and scraping_session.selected_case_type:
#             print(f"✅ SELECTED")
#             print(f"✅ Case type received: {scraping_session.selected_case_type}\n")
#             return True
        
#         # Check for cancellation
#         if scraping_session.status == "error" or scraping_session.status == "cancelled":
#             print(f"❌ CANCELLED\n")
#             return False
        
#         remaining = timeout - elapsed
#         print(f"⏳ Waiting ({remaining}s remaining)")
    
#     print(f"\n❌ TIMEOUT - No {selection_key} selected after {timeout}s\n")
#     return False


# def run_interactive_scraping(session_id):
#     scraping_session = active_sessions[session_id]
    
#     try:
#         # Step 1: Initialize browser
#         scraping_session.update_status("initializing", 10, "Starting browser...")
#         browser = Browser(headless=True)
#         scraping_session.browser = browser
#         scraping_session.scraper = CauseListScraper(browser, ocr_captcha=True)
#         scraping_session.step_completed["browser_init"] = True
        
#         # Step 2: Open page
#         scraping_session.update_status("page_load", 20, "Opening eCourts website...")
#         scraping_session.scraper.open_page()
#         scraping_session.step_completed["page_load"] = True
        
#         # STEP 3: STATE SELECTION
#         scraping_session.update_status("state_selection", 25, "Loading states...")
#         time.sleep(1)
        
#         state_select = browser.driver.find_element(By.ID, "sess_state_code")
#         available_states = scraping_session.scraper.get_options_from_select(state_select)
        
#         if not available_states:
#             scraping_session.set_error("No states available")
#             return
        
#         scraping_session.set_waiting_for_input(
#             "state_selection", 30, "👇 SELECT A STATE FROM THE DROPDOWN",
#             "state", available_states
#         )
        
#         if not wait_for_user_selection(scraping_session, 'state', timeout=120):
#             scraping_session.set_error("State selection timeout")
#             return
        
#         selected_state = scraping_session.selected_state
#         scraping_session.output_state = selected_state  # Store for CSV/PDF
#         scraping_session.update_status("state_selection", 32, f"Processing: {selected_state}...")
#         scraping_session.scraper.select_dropdown_value((By.ID, "sess_state_code"), selected_state)
#         scraping_session.step_completed["state_selection"] = True
#         scraping_session.clear_selection('state')
        
#         time.sleep(3)
        
#         # STEP 4: DISTRICT SELECTION
#         scraping_session.update_status("district_selection", 35, "Loading districts...")
#         time.sleep(1)
        
#         district_select = browser.driver.find_element(By.ID, "sess_dist_code")
#         available_districts = scraping_session.scraper.get_options_from_select(district_select)
        
#         if not available_districts:
#             scraping_session.set_error("No districts available for selected state")
#             return
        
#         scraping_session.set_waiting_for_input(
#             "district_selection", 40, "👇 SELECT A DISTRICT FROM THE DROPDOWN",
#             "district", available_districts
#         )
        
#         if not wait_for_user_selection(scraping_session, 'district', timeout=120):
#             scraping_session.set_error("District selection timeout")
#             return
        
#         selected_district = scraping_session.selected_district
#         scraping_session.output_district = selected_district  # Store for CSV/PDF
#         scraping_session.update_status("district_selection", 42, f"Processing: {selected_district}...")
#         scraping_session.scraper.select_dropdown_value((By.ID, "sess_dist_code"), selected_district)
#         scraping_session.step_completed["district_selection"] = True
#         scraping_session.clear_selection('district')
        
#         time.sleep(3)
        
#         # STEP 5: COMPLEX SELECTION
#         scraping_session.update_status("complex_selection", 45, "Loading court complexes...")
#         time.sleep(1)
        
#         complex_select = browser.driver.find_element(By.ID, "court_complex_code")
#         available_complexes = scraping_session.scraper.get_options_from_select(complex_select)
        
#         if not available_complexes:
#             scraping_session.set_error("No court complexes available")
#             return
        
#         scraping_session.set_waiting_for_input(
#             "complex_selection", 50, "👇 SELECT A COURT COMPLEX FROM THE DROPDOWN",
#             "complex", available_complexes
#         )
        
#         if not wait_for_user_selection(scraping_session, 'complex', timeout=120):
#             scraping_session.set_error("Complex selection timeout")
#             return
        
#         selected_complex = scraping_session.selected_complex
#         scraping_session.output_complex = selected_complex  # Store for CSV/PDF
#         scraping_session.update_status("complex_selection", 52, f"Processing: {selected_complex}...")
#         scraping_session.scraper.select_dropdown_value((By.ID, "court_complex_code"), selected_complex)
#         scraping_session.step_completed["complex_selection"] = True
#         scraping_session.clear_selection('complex')
        
#         time.sleep(3)
        
#         # STEP 6: JUDGE SELECTION
#         scraping_session.update_status("judge_selection", 55, "Loading judges...")
#         time.sleep(1)
        
#         judge_el = scraping_session.scraper.wait_for_judge_dropdown()
        
#         if not judge_el:
#             scraping_session.set_error("No judge dropdown found")
#             return
        
#         available_judges = scraping_session.scraper.get_options_from_select(judge_el)
        
#         if not available_judges:
#             scraping_session.set_error("No judges available")
#             return
        
#         # Filter out duplicates from available_judges before storing
#         unique_judges = []
#         seen = set()
#         for judge in available_judges:
#             judge_clean = judge.strip()
#             if judge_clean.lower() != "select court name" and judge_clean not in seen:
#                 unique_judges.append(judge_clean)
#                 seen.add(judge_clean)
        
#         scraping_session.set_waiting_for_input(
#             "judge_selection", 60, "👇 SELECT A JUDGE FROM THE DROPDOWN",
#             "judge", unique_judges
#         )
        
#         if not wait_for_user_selection(scraping_session, 'judge', timeout=120):
#             scraping_session.set_error("Judge selection timeout")
#             return
        
#         selected_judge = scraping_session.selected_judge
#         scraping_session.update_status("judge_selection", 62, f"Processing: {selected_judge}...")
        
#         if not scraping_session.scraper.select_judge(selected_judge):
#             scraping_session.set_error("Failed to select judge in browser")
#             return
        
#         scraping_session.step_completed["judge_selection"] = True
#         scraping_session.clear_selection('judge')
        
#         time.sleep(2)
        
#         # STEP 7: DATE SETTING (automatic)
#         scraping_session.update_status("date_setting", 65, "Setting date automatically...")
#         date_obj = ensure_date_object(scraping_session.when)
#         scraping_session.date_obj = date_obj
        
#         if not scraping_session.scraper.set_date_mmddyyyy(date_obj):
#             scraping_session.set_error("Failed to set date")
#             return
        
#         scraping_session.step_completed["date_setting"] = True
#         time.sleep(2)
        
#         # STEP 8: CAPTCHA - Auto-solve with OCR, then wait for case type selection
#         scraping_session.update_status("captcha_solving", 70, "Auto-solving CAPTCHA with OCR...")
        
#         captcha_success, result = scraping_session.scraper.captcha_hybrid_solve(max_attempts=4)
        
#         if not captcha_success:
#             scraping_session.set_error("CAPTCHA auto-solve failed after 4 attempts")
#             return
        
#         # CAPTCHA auto-solved, now wait for user to select Civil/Criminal in Flask UI
#         scraping_session.update_status("captcha_solving", 75, "CAPTCHA auto-solved! Waiting for case type selection...")
        
#         scraping_session.set_waiting_for_input(
#             "captcha_solving", 75,
#             "CAPTCHA solved automatically! Now select case type: CIVIL or CRIMINAL",
#             "case_type", ["Civil", "Criminal"]
#         )
        
#         print("\n⏳ Waiting for user to select case type in Flask UI...")
        
#         if not wait_for_user_selection(scraping_session, 'case_type', timeout=180):
#             scraping_session.set_error("Case type selection timeout - not selected within 3 minutes")
#             return
        
#         case_type = scraping_session.selected_case_type
#         print(f"\n✅ User selected case type: {case_type}")
#         print(f"   Clicking {case_type} button and validating...")
        
#         scraping_session.update_status("captcha_solving", 80, f"Validating case type: {case_type}...")
        
#         if not scraping_session.scraper.captcha_hybrid_click_and_validate(case_type):
#             scraping_session.set_error("CAPTCHA validation failed after clicking button")
#             return
        
#         scraping_session.step_completed["captcha_solving"] = True
#         scraping_session.step_completed["case_type_selection"] = True
#         scraping_session.update_status("captcha_solving", 85, f"✅ CAPTCHA validated! Case type: {case_type}")
#         time.sleep(2)
        
#         # STEP 9: EXTRACT CASES
#         scraping_session.update_status("scraping", 90, "Extracting cases from results...")
#         time.sleep(2)
        
#         cases = scraping_session.scraper.extract_cases_using_beautifulsoup()
        
#         if cases:
#             for case in cases:
#                 case['court_name'] = selected_judge
#                 case['date'] = date_obj.strftime("%Y-%m-%d")
#                 case['case_type'] = scraping_session.selected_case_type
#                 case['district'] = selected_district
#                 case['state'] = scraping_session.output_state
#                 case['court_complex'] = scraping_session.output_complex
            
#             scraping_session.set_results(cases)
#             scraping_session.update_status("completed", 100, f"✅ Successfully extracted {len(cases)} cases!")
            
#             timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
#             csv_path, json_path = save_results(cases, f'web_cause_list_{session_id}_{timestamp}')
#         else:
#             scraping_session.set_error("No cases found in results page - court may be closed or no cases scheduled")
            
#     except Exception as e:
#         scraping_session.set_error(f"Error: {str(e)}")
#         import traceback
#         print(f"Scraping error: {traceback.format_exc()}")
        
#     finally:
#         if scraping_session.browser:
#             try:
#                 scraping_session.browser.close()
#             except:
#                 pass


# @app.route('/')
# def index():
#     return render_template('index_interactive.html')


# @app.route('/start_scraping', methods=['POST'])
# def start_scraping():
#     data = request.json
#     district = data.get('district', '').strip()
#     when = data.get('when', 'today')
    
#     if not district:
#         return jsonify({'error': 'District is required'}), 400
    
#     session_id = f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
#     scraping_session = InteractiveScrapingSession(session_id, district, when, headless=True)
#     active_sessions[session_id] = scraping_session
    
#     thread = threading.Thread(target=run_interactive_scraping, args=(session_id,))
#     thread.daemon = True
#     thread.start()
    
#     return jsonify({
#         'session_id': session_id,
#         'message': 'Scraping started successfully'
#     })


# @app.route('/scraping_status/<session_id>')
# def scraping_status(session_id):
#     if session_id not in active_sessions:
#         return jsonify({'error': 'Session not found'}), 404
    
#     scraping_session = active_sessions[session_id]
    
#     response_data = {
#         'status': scraping_session.status,
#         'current_step': scraping_session.current_step,
#         'progress': scraping_session.progress,
#         'message': scraping_session.message,
#         'error': scraping_session.error,
#         'case_count': len(scraping_session.cases),
#         'requires_user_input': scraping_session.waiting_for_input,
#         'user_input_type': scraping_session.waiting_for_input_type,
#         **scraping_session.get_step_data()
#     }
    
#     return jsonify(response_data)


# @app.route('/provide_selection/<session_id>', methods=['POST'])
# def provide_selection(session_id):
#     if session_id not in active_sessions:
#         return jsonify({'error': 'Session not found'}), 404
    
#     scraping_session = active_sessions[session_id]
#     data = request.json
#     selection_type = data.get('type')
#     selection_value = data.get('value')
    
#     if not selection_type or not selection_value:
#         return jsonify({'error': 'Type and value are required'}), 400
    
#     if selection_type == 'state':
#         scraping_session.selected_state = selection_value
#     elif selection_type == 'district':
#         scraping_session.selected_district = selection_value
#     elif selection_type == 'complex':
#         scraping_session.selected_complex = selection_value
#     elif selection_type == 'judge':
#         scraping_session.selected_judge = selection_value
#     elif selection_type == 'case_type':
#         scraping_session.selected_case_type = selection_value
#         print(f"✅ Case type selection received: {selection_value}")
#     else:
#         return jsonify({'error': f'Unknown selection type: {selection_type}'}), 400
    
#     return jsonify({
#         'message': f'Selection received: {selection_value}',
#         'type': selection_type,
#         'session_id': session_id
#     })


# @app.route('/download_results/<session_id>')
# def download_results(session_id):
#     if session_id not in active_sessions:
#         return jsonify({'error': 'Session not found'}), 404
    
#     scraping_session = active_sessions[session_id]
    
#     if not scraping_session.cases:
#         return jsonify({'error': 'No cases available for download'}), 400
    
#     csv_files = list(BASE_DIR.glob(f'*{session_id}*.csv'))
#     if not csv_files:
#         timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
#         csv_path, _ = save_results(scraping_session.cases, f'download_{session_id}_{timestamp}')
#     else:
#         csv_path = csv_files[0]
    
#     return send_file(
#         csv_path,
#         as_attachment=True,
#         download_name=f'cause_list_{session_id}.csv',
#         mimetype='text/csv'
#     )


# @app.route('/generate_pdf/<session_id>')
# def generate_pdf(session_id):
#     if session_id not in active_sessions:
#         return jsonify({'error': 'Session not found'}), 404
    
#     scraping_session = active_sessions[session_id]
    
#     if not scraping_session.cases:
#         return jsonify({'error': 'No cases available for PDF generation'}), 400
    
#     first_case = scraping_session.cases[0]
#     court_name = first_case.get('court_name', 'Unknown Court')
#     date_str = first_case.get('date', datetime.date.today().strftime('%Y-%m-%d'))
#     case_type = first_case.get('case_type', 'Unknown')
#     state = scraping_session.output_state or 'Unknown'
#     district = scraping_session.output_district or 'Unknown'
#     court_complex = scraping_session.output_complex or 'Unknown'
#     available_judges = scraping_session.available_judges or []
    
#     pdf_filename = f"cause_list_report_{session_id}.pdf"
#     pdf_path = generate_pdf_from_cases(
#         scraping_session.cases,
#         pdf_filename,
#         court_name,
#         date_str,
#         case_type,
#         state,
#         district,
#         court_complex,
#         available_judges
#     )
    
#     if pdf_path:
#         return send_file(
#             pdf_path,
#             as_attachment=True,
#             download_name=f'cause_list_report_{session_id}.pdf',
#             mimetype='application/pdf'
#         )
#     else:
#         return jsonify({'error': 'PDF generation failed'}), 500


# @app.route('/cancel_scraping/<session_id>', methods=['POST'])
# def cancel_scraping(session_id):
#     if session_id in active_sessions:
#         active_sessions[session_id].status = "cancelled"
#         if active_sessions[session_id].browser:
#             try:
#                 active_sessions[session_id].browser.close()
#             except:
#                 pass
#         return jsonify({'message': 'Scraping cancelled'})
#     else:
#         return jsonify({'error': 'Session not found'}), 404


# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=5000)


import os
import json
import datetime
from flask import Flask, render_template, request, jsonify, send_file, session
from pathlib import Path
import threading
import time
from selenium.webdriver.common.by import By
from imp import (
    Browser, CauseListScraper, ensure_date_object, 
    save_results, generate_pdf_from_cases, BASE_DIR
)

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
app.config['SESSION_TYPE'] = 'filesystem'

active_sessions = {}

class InteractiveScrapingSession:
    def __init__(self, session_id, district, when, headless=False):
        self.session_id = session_id
        self.district = district
        self.when = when
        self.headless = headless
        self.status = "idle"
        self.current_step = "initializing"
        self.progress = 0
        self.message = ""
        self.cases = []
        self.error = None
        self.browser = None
        self.scraper = None
        self.date_obj = None
        
        self.available_states = []
        self.available_districts = []
        self.available_complexes = []
        self.available_judges = []
        self.case_type_options = ["Civil", "Criminal"]
        
        self.selected_state = None
        self.selected_district = None
        self.selected_complex = None
        self.selected_judge = None
        self.selected_case_type = None
        
        # Store for CSV/PDF output
        self.output_state = None
        self.output_district = None
        self.output_complex = None
        
        self.step_completed = {
            "browser_init": False,
            "page_load": False,
            "state_selection": False,
            "district_selection": False,
            "complex_selection": False,
            "judge_selection": False,
            "date_setting": False,
            "captcha_solving": False,
            "case_type_selection": False,
            "scraping": False
        }
        
        self.waiting_for_input = False
        self.waiting_for_input_type = None

    def update_status(self, step, progress, message, **kwargs):
        self.current_step = step
        self.progress = progress
        self.message = message
        self.waiting_for_input = False
        self.waiting_for_input_type = None
        
        if 'available_states' in kwargs:
            self.available_states = kwargs['available_states']
        if 'available_districts' in kwargs:
            self.available_districts = kwargs['available_districts']
        if 'available_complexes' in kwargs:
            self.available_complexes = kwargs['available_complexes']
        if 'available_judges' in kwargs:
            self.available_judges = kwargs['available_judges']

    def set_waiting_for_input(self, step, progress, message, input_type, options=None):
        """Set session to wait for user input - BLOCKING"""
        self.current_step = step
        self.progress = progress
        self.message = message
        self.waiting_for_input = True
        self.waiting_for_input_type = input_type
        
        if options is None:
            options = []
        
        if input_type == 'state':
            self.available_states = options
        elif input_type == 'district':
            self.available_districts = options
        elif input_type == 'complex':
            self.available_complexes = options
        elif input_type == 'judge':
            self.available_judges = options
        elif input_type == 'case_type':
            self.case_type_options = options

    def clear_selection(self, input_type):
        """Clear a selection after it's been processed"""
        if input_type == 'state':
            self.selected_state = None
        elif input_type == 'district':
            self.selected_district = None
        elif input_type == 'complex':
            self.selected_complex = None
        elif input_type == 'judge':
            self.selected_judge = None
        elif input_type == 'case_type':
            self.selected_case_type = None

    def set_error(self, error):
        self.status = "error"
        self.error = error
        self.waiting_for_input = False
        self.waiting_for_input_type = None

    def set_results(self, cases):
        self.cases = cases
        self.status = "completed"
        self.current_step = "completed"
        self.waiting_for_input = False
        self.waiting_for_input_type = None

    def get_step_data(self):
        return {
            'current_step': self.current_step,
            'progress': self.progress,
            'message': self.message,
            'available_states': self.available_states,
            'available_districts': self.available_districts,
            'available_complexes': self.available_complexes,
            'available_judges': self.available_judges,
            'case_type_options': self.case_type_options,
            'requires_user_input': self.waiting_for_input,
            'user_input_type': self.waiting_for_input_type
        }


def wait_for_user_selection(scraping_session, selection_key, timeout=120):
    """
    Wait for user to make a selection with SLOW checking.
    
    Checks every 15 seconds ONLY - gives user plenty of time to:
    1. Click dropdown/button
    2. Read options  
    3. Select one
    4. Click confirm button
    
    This timeout is 2 minutes per dropdown.
    
    Args:
        scraping_session: The session object
        selection_key: 'state', 'district', 'complex', 'judge', or 'case_type'
        timeout: Maximum seconds to wait (default 2 minutes = 120 seconds)
    
    Returns:
        True if selection made, False if timeout or cancelled
    """
    start_time = time.time()
    check_number = 0
    
    print(f"\n⏳ WAITING FOR {selection_key.upper()} (checking every 15 seconds, timeout {timeout}s)")
    
    while time.time() - start_time < timeout:
        # Check every 15 seconds ONLY - not more frequently
        time.sleep(15)
        check_number += 1
        elapsed = int(time.time() - start_time)
        
        print(f"   Check #{check_number} at {elapsed}s: ", end="")
        
        # Check if selection was made
        if selection_key == 'state' and scraping_session.selected_state:
            print(f"✅ SELECTED")
            print(f"✅ State received: {scraping_session.selected_state}\n")
            return True
        elif selection_key == 'district' and scraping_session.selected_district:
            print(f"✅ SELECTED")
            print(f"✅ District received: {scraping_session.selected_district}\n")
            return True
        elif selection_key == 'complex' and scraping_session.selected_complex:
            print(f"✅ SELECTED")
            print(f"✅ Complex received: {scraping_session.selected_complex}\n")
            return True
        elif selection_key == 'judge' and scraping_session.selected_judge:
            print(f"✅ SELECTED")
            print(f"✅ Judge received: {scraping_session.selected_judge}\n")
            return True
        elif selection_key == 'case_type' and scraping_session.selected_case_type:
            print(f"✅ SELECTED")
            print(f"✅ Case type received: {scraping_session.selected_case_type}\n")
            return True
        
        # Check for cancellation
        if scraping_session.status == "error" or scraping_session.status == "cancelled":
            print(f"❌ CANCELLED\n")
            return False
        
        remaining = timeout - elapsed
        print(f"⏳ Waiting ({remaining}s remaining)")
    
    print(f"\n❌ TIMEOUT - No {selection_key} selected after {timeout}s\n")
    return False


def run_interactive_scraping(session_id):
    scraping_session = active_sessions[session_id]
    
    try:
        # Step 1: Initialize browser
        scraping_session.update_status("initializing", 10, "Starting browser...")
        browser = Browser(headless=True)
        scraping_session.browser = browser
        scraping_session.scraper = CauseListScraper(browser, ocr_captcha=True)
        scraping_session.step_completed["browser_init"] = True
        
        # Step 2: Open page
        scraping_session.update_status("page_load", 20, "Opening eCourts website...")
        scraping_session.scraper.open_page()
        scraping_session.step_completed["page_load"] = True
        
        # STEP 3: STATE SELECTION
        scraping_session.update_status("state_selection", 25, "Loading states...")
        time.sleep(1)
        
        state_select = browser.driver.find_element(By.ID, "sess_state_code")
        available_states = scraping_session.scraper.get_options_from_select(state_select)
        
        if not available_states:
            scraping_session.set_error("No states available")
            return
        
        scraping_session.set_waiting_for_input(
            "state_selection", 30, "👇 SELECT A STATE FROM THE DROPDOWN",
            "state", available_states
        )
        
        if not wait_for_user_selection(scraping_session, 'state', timeout=120):
            scraping_session.set_error("State selection timeout")
            return
        
        selected_state = scraping_session.selected_state
        scraping_session.output_state = selected_state  # Store for CSV/PDF
        scraping_session.update_status("state_selection", 32, f"Processing: {selected_state}...")
        scraping_session.scraper.select_dropdown_value((By.ID, "sess_state_code"), selected_state)
        scraping_session.step_completed["state_selection"] = True
        scraping_session.clear_selection('state')
        
        time.sleep(3)
        
        # STEP 4: DISTRICT SELECTION
        scraping_session.update_status("district_selection", 35, "Loading districts...")
        time.sleep(1)
        
        district_select = browser.driver.find_element(By.ID, "sess_dist_code")
        available_districts = scraping_session.scraper.get_options_from_select(district_select)
        
        if not available_districts:
            scraping_session.set_error("No districts available for selected state")
            return
        
        scraping_session.set_waiting_for_input(
            "district_selection", 40, "👇 SELECT A DISTRICT FROM THE DROPDOWN",
            "district", available_districts
        )
        
        if not wait_for_user_selection(scraping_session, 'district', timeout=120):
            scraping_session.set_error("District selection timeout")
            return
        
        selected_district = scraping_session.selected_district
        scraping_session.output_district = selected_district  # Store for CSV/PDF
        scraping_session.update_status("district_selection", 42, f"Processing: {selected_district}...")
        scraping_session.scraper.select_dropdown_value((By.ID, "sess_dist_code"), selected_district)
        scraping_session.step_completed["district_selection"] = True
        scraping_session.clear_selection('district')
        
        time.sleep(3)
        
        # STEP 5: COMPLEX SELECTION
        scraping_session.update_status("complex_selection", 45, "Loading court complexes...")
        time.sleep(1)
        
        complex_select = browser.driver.find_element(By.ID, "court_complex_code")
        available_complexes = scraping_session.scraper.get_options_from_select(complex_select)
        
        if not available_complexes:
            scraping_session.set_error("No court complexes available")
            return
        
        scraping_session.set_waiting_for_input(
            "complex_selection", 50, "👇 SELECT A COURT COMPLEX FROM THE DROPDOWN",
            "complex", available_complexes
        )
        
        if not wait_for_user_selection(scraping_session, 'complex', timeout=120):
            scraping_session.set_error("Complex selection timeout")
            return
        
        selected_complex = scraping_session.selected_complex
        scraping_session.output_complex = selected_complex  # Store for CSV/PDF
        scraping_session.update_status("complex_selection", 52, f"Processing: {selected_complex}...")
        scraping_session.scraper.select_dropdown_value((By.ID, "court_complex_code"), selected_complex)
        scraping_session.step_completed["complex_selection"] = True
        scraping_session.clear_selection('complex')
        
        time.sleep(3)
        
        # STEP 6: JUDGE SELECTION
        scraping_session.update_status("judge_selection", 55, "Loading judges...")
        time.sleep(1)
        
        judge_el = scraping_session.scraper.wait_for_judge_dropdown()
        
        if not judge_el:
            scraping_session.set_error("No judge dropdown found")
            return
        
        available_judges = scraping_session.scraper.get_options_from_select(judge_el)
        
        if not available_judges:
            scraping_session.set_error("No judges available")
            return
        
        scraping_session.set_waiting_for_input(
            "judge_selection", 60, "👇 SELECT A JUDGE FROM THE DROPDOWN",
            "judge", available_judges
        )
        
        if not wait_for_user_selection(scraping_session, 'judge', timeout=120):
            scraping_session.set_error("Judge selection timeout")
            return
        
        selected_judge = scraping_session.selected_judge
        scraping_session.update_status("judge_selection", 62, f"Processing: {selected_judge}...")
        
        if not scraping_session.scraper.select_judge(selected_judge):
            scraping_session.set_error("Failed to select judge in browser")
            return
        
        scraping_session.step_completed["judge_selection"] = True
        scraping_session.clear_selection('judge')
        
        time.sleep(2)
        
        # STEP 7: DATE SETTING (automatic)
        scraping_session.update_status("date_setting", 65, "Setting date automatically...")
        date_obj = ensure_date_object(scraping_session.when)
        scraping_session.date_obj = date_obj
        
        if not scraping_session.scraper.set_date_mmddyyyy(date_obj):
            scraping_session.set_error("Failed to set date")
            return
        
        scraping_session.step_completed["date_setting"] = True
        time.sleep(2)
        
        # STEP 8: CAPTCHA - Auto-solve with OCR, then wait for case type selection
        scraping_session.update_status("captcha_solving", 70, "Auto-solving CAPTCHA with OCR...")
        
        captcha_success, result = scraping_session.scraper.captcha_hybrid_solve(max_attempts=4)
        
        if not captcha_success:
            scraping_session.set_error("CAPTCHA auto-solve failed after 4 attempts")
            return
        
        # CAPTCHA auto-solved, now wait for user to select Civil/Criminal in Flask UI
        scraping_session.update_status("captcha_solving", 75, "CAPTCHA auto-solved! Waiting for case type selection...")
        
        scraping_session.set_waiting_for_input(
            "captcha_solving", 75,
            "CAPTCHA solved automatically! Now select case type: CIVIL or CRIMINAL",
            "case_type", ["Civil", "Criminal"]
        )
        
        print("\n⏳ Waiting for user to select case type in Flask UI...")
        
        if not wait_for_user_selection(scraping_session, 'case_type', timeout=180):
            scraping_session.set_error("Case type selection timeout - not selected within 3 minutes")
            return
        
        case_type = scraping_session.selected_case_type
        print(f"\n✅ User selected case type: {case_type}")
        print(f"   Clicking {case_type} button and validating...")
        
        scraping_session.update_status("captcha_solving", 80, f"Validating case type: {case_type}...")
        
        if not scraping_session.scraper.captcha_hybrid_click_and_validate(case_type):
            scraping_session.set_error("CAPTCHA validation failed after clicking button")
            return
        
        scraping_session.step_completed["captcha_solving"] = True
        scraping_session.step_completed["case_type_selection"] = True
        scraping_session.update_status("captcha_solving", 85, f"✅ CAPTCHA validated! Case type: {case_type}")
        time.sleep(2)
        
        # STEP 9: EXTRACT CASES
        scraping_session.update_status("scraping", 90, "Extracting cases from results...")
        time.sleep(2)
        
        cases = scraping_session.scraper.extract_cases_using_beautifulsoup()
        
        if cases:
            for case in cases:
                case['court_name'] = selected_judge
                case['date'] = date_obj.strftime("%Y-%m-%d")
                case['case_type'] = scraping_session.selected_case_type
                case['district'] = selected_district
                case['state'] = scraping_session.output_state
                case['court_complex'] = scraping_session.output_complex
            
            scraping_session.set_results(cases)
            scraping_session.update_status("completed", 100, f"✅ Successfully extracted {len(cases)} cases!")
            
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path, json_path = save_results(cases, f'web_cause_list_{session_id}_{timestamp}')
        else:
            scraping_session.set_error("No cases found in results page - court may be closed or no cases scheduled")
            
    except Exception as e:
        scraping_session.set_error(f"Error: {str(e)}")
        import traceback
        print(f"Scraping error: {traceback.format_exc()}")
        
    finally:
        if scraping_session.browser:
            try:
                scraping_session.browser.close()
            except:
                pass


@app.route('/')
def index():
    return render_template('index_interactive.html')


@app.route('/start_scraping', methods=['POST'])
def start_scraping():
    data = request.json
    district = data.get('district', '').strip()
    when = data.get('when', 'today')
    
    if not district:
        return jsonify({'error': 'District is required'}), 400
    
    session_id = f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    scraping_session = InteractiveScrapingSession(session_id, district, when, headless=True)
    active_sessions[session_id] = scraping_session
    
    thread = threading.Thread(target=run_interactive_scraping, args=(session_id,))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'session_id': session_id,
        'message': 'Scraping started successfully'
    })


@app.route('/scraping_status/<session_id>')
def scraping_status(session_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    scraping_session = active_sessions[session_id]
    
    response_data = {
        'status': scraping_session.status,
        'current_step': scraping_session.current_step,
        'progress': scraping_session.progress,
        'message': scraping_session.message,
        'error': scraping_session.error,
        'case_count': len(scraping_session.cases),
        'requires_user_input': scraping_session.waiting_for_input,
        'user_input_type': scraping_session.waiting_for_input_type,
        **scraping_session.get_step_data()
    }
    
    return jsonify(response_data)


@app.route('/provide_selection/<session_id>', methods=['POST'])
def provide_selection(session_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    scraping_session = active_sessions[session_id]
    data = request.json
    selection_type = data.get('type')
    selection_value = data.get('value')
    
    if not selection_type or not selection_value:
        return jsonify({'error': 'Type and value are required'}), 400
    
    if selection_type == 'state':
        scraping_session.selected_state = selection_value
    elif selection_type == 'district':
        scraping_session.selected_district = selection_value
    elif selection_type == 'complex':
        scraping_session.selected_complex = selection_value
    elif selection_type == 'judge':
        scraping_session.selected_judge = selection_value
    elif selection_type == 'case_type':
        scraping_session.selected_case_type = selection_value
        print(f"✅ Case type selection received: {selection_value}")
    else:
        return jsonify({'error': f'Unknown selection type: {selection_type}'}), 400
    
    return jsonify({
        'message': f'Selection received: {selection_value}',
        'type': selection_type,
        'session_id': session_id
    })


@app.route('/download_results/<session_id>')
def download_results(session_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    scraping_session = active_sessions[session_id]
    
    if not scraping_session.cases:
        return jsonify({'error': 'No cases available for download'}), 400
    
    csv_files = list(BASE_DIR.glob(f'*{session_id}*.csv'))
    if not csv_files:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path, _ = save_results(scraping_session.cases, f'download_{session_id}_{timestamp}')
    else:
        csv_path = csv_files[0]
    
    return send_file(
        csv_path,
        as_attachment=True,
        download_name=f'cause_list_{session_id}.csv',
        mimetype='text/csv'
    )


@app.route('/generate_pdf/<session_id>')
def generate_pdf(session_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    scraping_session = active_sessions[session_id]
    
    if not scraping_session.cases:
        return jsonify({'error': 'No cases available for PDF generation'}), 400
    
    first_case = scraping_session.cases[0]
    court_name = first_case.get('court_name', 'Unknown Court')
    date_str = first_case.get('date', datetime.date.today().strftime('%Y-%m-%d'))
    case_type = first_case.get('case_type', 'Unknown')
    state = scraping_session.output_state or 'Unknown'
    district = scraping_session.output_district or 'Unknown'
    court_complex = scraping_session.output_complex or 'Unknown'
    available_judges = scraping_session.available_judges or []
    
    pdf_filename = f"cause_list_report_{session_id}.pdf"
    pdf_path = generate_pdf_from_cases(
        scraping_session.cases,
        pdf_filename,
        court_name,
        date_str,
        case_type,
        state,
        district,
        court_complex,
        available_judges
    )
    
    if pdf_path:
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f'cause_list_report_{session_id}.pdf',
            mimetype='application/pdf'
        )
    else:
        return jsonify({'error': 'PDF generation failed'}), 500


@app.route('/cancel_scraping/<session_id>', methods=['POST'])
def cancel_scraping(session_id):
    if session_id in active_sessions:
        active_sessions[session_id].status = "cancelled"
        if active_sessions[session_id].browser:
            try:
                active_sessions[session_id].browser.close()
            except:
                pass
        return jsonify({'message': 'Scraping cancelled'})
    else:
        return jsonify({'error': 'Session not found'}), 404


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)