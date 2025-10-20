# eCourts Case List Scraper

A Python-based web scraper for extracting case information from Indian eCourts website with Flask web interface for interactive selection.

## Project Overview

This application automates the process of scraping court case lists from the eCourts India website. It features:

- **Interactive Web Interface** - User-friendly Flask web application
- **Automated CAPTCHA Solving** - OCR-based automatic CAPTCHA solving with manual fallback
- **Interactive Dropdowns** - Select State, District, Court Complex, and Judge through web UI
- **Case Extraction** - Automatically extracts case numbers, parties, advocates, and hearing dates
- **Multiple Export Formats** - Download results as CSV or PDF with comprehensive formatting
- **Professional PDF Reports** - Landscape PDF with court information, judge list, and formatted case data

## Requirements

- Ubuntu/Linux OS (tested on Ubuntu 20.04+)
- Python 3.12
- Google Chrome browser
- 4GB RAM minimum

## Installation & Setup

### Step 1: Install Python 3.12

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv
```

### Step 2: Clone or Create Project Directory

```bash
mkdir ecourts-scraper
cd ecourts-scraper
```

### Step 3: Create Virtual Environment

```bash
python3.12 -m venv venv
```

### Step 4: Activate Virtual Environment

```bash
source venv/bin/activate
```

You should see `(venv)` at the beginning of your terminal prompt.

### Step 5: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 6: Install Additional System Dependencies (for OCR)

```bash
sudo apt install tesseract-ocr libtesseract-dev
```

## Running the Application

### Start Flask Development Server

```bash
python run.py
```

Expected output:
```
 * Serving Flask app 'app'
 * Debug mode: on
 * Running on http://0.0.0.0:5000
```

### Access Web Interface

Open your web browser and navigate to:

```
http://localhost:5000
```

## How to Use

### 1. Enter District and Date

- **District**: Enter the district name (e.g., "Srinagar")
- **Date**: Optional - Select a date or leave for today's date
- Click "Start Scraping" button

### 2. Select State

- A dropdown will appear with all available states
- Select the state from the dropdown
- System waits for your selection (max 2 minutes)

### 3. Select District

- After state selection, district dropdown appears
- Choose your district
- System waits for confirmation (max 2 minutes)

### 4. Select Court Complex

- Court complex dropdown appears
- Select the court complex
- System waits for confirmation (max 2 minutes)

### 5. Select Judge/Court Name

- List of judges in the complex appears
- Select the judge whose cases you want to retrieve
- System waits for confirmation (max 2 minutes)

### 6. Automatic Date Setting & CAPTCHA Solving

- Date is automatically set (or defaults to today)
- CAPTCHA is automatically solved using OCR
- If OCR fails, you'll be prompted to enter it manually
- System shows CAPTCHA image and verification code field

### 7. Select Case Type

After CAPTCHA is solved, select the case type:
- **CIVIL** - Civil cases
- **CRIMINAL** - Criminal cases

Click the appropriate button.

### 8. View and Download Results

Once scraping completes:
- **Case Count** - Shows number of cases extracted
- **Download CSV** - Export data as spreadsheet
- **Download PDF** - Generate professional report
- **Start New Scraping** - Begin another search

## Output Files

Results are saved in `ecourts_output/` directory:

```
ecourts_output/
├── web_cause_list_[SESSION_ID]_[TIMESTAMP].csv
├── web_cause_list_[SESSION_ID]_[TIMESTAMP].json
├── cause_list_report_[SESSION_ID].pdf
└── debug_page.html
```

### CSV Format

Includes columns:
- Serial No
- Case Number (with hearing date)
- Party Names
- Advocate Name
- Court Name
- Date
- Case Type
- State
- District
- Court Complex

### PDF Format

Professional landscape PDF containing:
- Blue header with State, District, Court Complex
- Selected Court Name, Date, and Case Type
- Complete list of available judges (selected one highlighted in blue)
- Formatted cases table with all details
- Generated timestamp and case count footer

## Troubleshooting

### CAPTCHA Not Solving

If OCR fails to solve CAPTCHA automatically:
1. CAPTCHA image will display in browser
2. Enter the 6-digit code manually in the text field
3. Click Civil or Criminal button to continue
4. Maximum 4 attempts before timeout

### Judge Dropdown Not Appearing

- Court complex may not have judges associated
- Try selecting a different court complex
- Refresh page and start over if needed

### Cases Not Found

Possible reasons:
- Court may be closed
- No cases scheduled for selected date
- Selected judge may have no cases
- Try different date (within 30 days)

### Chrome Driver Issues

If Chrome driver fails to download:
```bash
pip install --upgrade webdriver-manager
```

### Timeout Errors

Each selection step has 2-minute timeout. If you need more time:
- Increase timeout values in `app.py` (change `timeout=120` to higher value in seconds)

## Project Structure

```
ecourts-scraper/
├── app.py                 # Flask application & scraping logic
├── imp.py                 # eCourts scraper & PDF generation
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── templates/
│   └── index_interactive.html  # Web interface
└── ecourts_output/       # Output directory (auto-created)
    ├── *.csv
    ├── *.json
    ├── *.pdf
    └── debug_page.html
```

## Key Features

### Interactive Web Interface
- Real-time progress tracking
- Visual feedback for each step
- Responsive design
- Mobile-friendly layout

### Automatic Features
- Chrome driver auto-download
- CAPTCHA auto-solving with OCR
- Date auto-setting
- Case type auto-detection

### Data Extraction
- Complete case information capture
- Automatic party name parsing
- Hearing date extraction
- Advocate information
- Next hearing date preservation

### Export Options
- CSV for spreadsheet analysis
- JSON for data processing
- PDF for professional reports
- HTML debug pages for troubleshooting

## Browser Support

- Chrome/Chromium (required for Selenium)
- Firefox may work but not tested
- Safari not supported

## Technical Stack

- **Backend**: Flask (Python 3.12)
- **Browser Automation**: Selenium
- **HTML Parsing**: BeautifulSoup4
- **Data Processing**: pandas
- **PDF Generation**: ReportLab
- **OCR**: pytesseract + Tesseract
- **Image Processing**: OpenCV, Pillow

## Notes

- Application runs on `0.0.0.0:5000` (accessible from any machine on network)
- Browser window opens automatically with Selenium (headless mode)
- All selections are case-sensitive
- Maximum date range is 30 days from today
- Session data is kept in memory (resets on Flask restart)

## Support

For issues or questions:
1. Check debug output in terminal
2. Review `ecourts_output/debug_page.html` for page structure
3. Check browser console for JavaScript errors
4. Ensure all dependencies installed: `pip install -r requirements.txt`

## License

This project is for educational and personal use only. Ensure compliance with eCourts India terms of service.

## Disclaimer

This scraper is provided as-is. Users are responsible for ensuring their use complies with applicable laws and website terms of service.
