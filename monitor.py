"""
Artificial Analysis Benchmark Monitor - Simple Version

Scrapes benchmark indices from artificialanalysis.ai using Selenium.
Monitors for changes and sends Pushover notifications.

Usage:
    python monitor.py              # Run continuously (every 30 min)
    python monitor.py --once       # Run once and exit
    python monitor.py --interval 15  # Check every 15 minutes
"""

import json
import time
import re
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv

import ssl
import certifi
import urllib3

# Load environment variables from .env file
load_dotenv()

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Fix SSL certificate issues for all requests
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
os.environ['WDM_SSL_VERIFY'] = '0'  # Disable SSL verify for webdriver-manager

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("Required packages not installed. Run:")
    print("pip install selenium webdriver-manager requests schedule certifi")
    exit(1)

# ============================================================================
# CONFIGURATION
# ============================================================================

PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "")  # CREATE YOUR APP AT https://pushover.net/apps/build - leave empty to skip notifications
SCRAPE_INTERVAL_MINUTES = 30
DATA_FILE = "benchmark_data.json"
HISTORY_FILE = "benchmark_history.json"
BASE_URL = "https://artificialanalysis.ai/"

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# PUSHOVER NOTIFICATIONS
# ============================================================================

def validate_pushover_credentials() -> bool:
    """Validate Pushover API credentials. Raises exception if invalid."""
    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        raise ValueError("PUSHOVER_USER_KEY and PUSHOVER_API_TOKEN must be set")
    
    try:
        response = requests.post(
            "https://api.pushover.net/1/users/validate.json",
            data={
                "token": PUSHOVER_API_TOKEN,
                "user": PUSHOVER_USER_KEY
            },
            timeout=10,
            verify=False
        )
        
        result = response.json()
        
        if response.status_code == 200 and result.get("status") == 1:
            logger.info("✓ Pushover credentials validated successfully")
            return True
        else:
            error_msg = result.get("errors", ["Unknown error"])
            raise ValueError(f"Invalid Pushover credentials: {error_msg}")
            
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Failed to validate Pushover credentials: {e}")


def send_pushover(title: str, message: str, priority: int = 0, image_path: str = None) -> bool:
    """Send a Pushover notification with optional image attachment."""
    if not PUSHOVER_API_TOKEN:
        logger.warning("Pushover API token not set - skipping notification")
        return False
        
    try:
        data = {
            "token": PUSHOVER_API_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": message[:1024],  # Pushover limit
            "priority": priority
        }
        
        files = None
        if image_path and os.path.exists(image_path):
            try:
                files = {
                    "attachment": ("benchmark.png", open(image_path, "rb"), "image/png")
                }
                logger.info(f"Attaching image: {image_path}")
            except Exception as e:
                logger.warning(f"Failed to attach image: {e}")
        
        response = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=data,
            files=files,
            timeout=30,
            verify=False  # Disable SSL verification due to cert issues
        )
        
        # Close the file if it was opened
        if files and "attachment" in files:
            try:
                files["attachment"][1].close()
            except:
                pass
        
        if response.status_code == 200:
            logger.info(f"✓ Pushover sent: {title}")
            return True
        else:
            logger.error(f"Pushover error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Pushover failed: {e}")
        return False

# ============================================================================
# SCRAPER
# ============================================================================

class BenchmarkScraper:
    """Scrapes benchmark data from artificialanalysis.ai"""
    
    # Text to ignore (UI elements, navigation, descriptions)
    # Use word boundaries or full phrases to avoid partial matches
    IGNORE_PATTERNS = [
        'add model', 'specific provider', 'artificial analysis', 
        'benchmark', 'leaderboard', 'filter',
        'incorporates', 'evaluations', 'represents', 'average',
        'open weights', 'proprietary', 'non-reasoning',
        'coding index', 'agentic index', 'intelligence index', 
        'click here', 'select', 'compare models', 'view all', 
        'show more', 'hide', 'show less',
        'subscribe', 'newsletter', 'contact us', 'about us', 'privacy',
        'terms of', 'cookie', 'sign in', 'log in', 'register'
    ]
    
    def __init__(self):
        self.driver = None
    
    def _setup_driver(self):
        """Initialize Chrome in headless mode."""
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1200")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.implicitly_wait(10)
    
    def _close_driver(self):
        """Clean up driver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def _is_model_name(self, text: str) -> bool:
        """
        Check if text looks like an AI model name.
        Uses heuristics instead of keyword matching to handle new/unknown models.
        """
        if not text or len(text) < 2 or len(text) > 80:
            return False
            
        text_lower = text.lower().strip()
        
        # Check if it's UI text to ignore
        if any(ignore in text_lower for ignore in self.IGNORE_PATTERNS):
            return False
        
        # Reject "X of Y models" patterns (e.g., "25 of 342 models", "25 of 345 models")
        if re.match(r'^\d+\s+of\s+\d+\s+models?$', text_lower):
            return False
        
        # Reject common UI patterns
        if text.startswith(('+', '×', '•', '→', '←', '↑', '↓')):
            return False
            
        # Reject if it's just a number or very short
        if text.isdigit() or len(text_lower) < 2:
            return False
            
        # Reject if it looks like a sentence (too many spaces, ends with punctuation)
        if text.count(' ') > 6:
            return False
        if text.endswith(('.', '!', '?', ':')):
            return False
            
        # Reject pure URLs
        if text_lower.startswith(('http://', 'https://', 'www.')):
            return False
        
        # Model names typically have:
        # - Alphanumeric characters with optional hyphens, underscores, dots
        # - Version numbers (1.5, 2.0, v2, etc.)
        # - Size indicators (7B, 70B, etc.)
        
        # Check if it matches typical model name patterns
        # Allow: letters, numbers, spaces, hyphens, underscores, dots, parentheses
        if not re.match(r'^[\w\s\-\.\(\)]+$', text, re.UNICODE):
            return False
        
        # Must contain at least one letter
        if not any(c.isalpha() for c in text):
            return False
            
        return True
    
    def _is_score(self, text: str) -> Optional[int]:
        """Check if text is a valid score (10-99)."""
        if re.match(r'^\d{1,2}$', text.strip()):
            score = int(text.strip())
            if 10 <= score <= 99:
                return score
        return None
    
    def _extract_chart_data(self, index_type: str = "intelligence") -> List[Dict]:
        """Extract model data from the currently visible chart.
        
        Args:
            index_type: One of "intelligence", "coding", or "agentic"
        """
        models = []
        try:
            # Get page text
            body = self.driver.find_element(By.TAG_NAME, "body")
            page_text = body.text
            lines = page_text.split('\n')
            
            # For Intelligence and Coding, use the Highlights section at the top
            # For Agentic, use the main chart section
            
            if index_type == "intelligence":
                # Look for "INTELLIGENCE" section in Highlights
                in_chart = False
                chart_lines = []
                for i, line in enumerate(lines):
                    line = line.strip()
                    if line == "INTELLIGENCE":
                        in_chart = True
                        continue
                    if in_chart and line in ["SPEED", "PRICE"]:
                        break
                    if in_chart and line:
                        # Skip the header line
                        if "Higher is better" in line:
                            continue
                        chart_lines.append(line)
                        
            elif index_type == "coding":
                # For Coding Index, look for the section after clicking the tab
                # The coding data appears after "Coding Index" description
                in_chart = False
                chart_lines = []
                found_coding_section = False
                
                for i, line in enumerate(lines):
                    line = line.strip()
                    
                    # Look for the Coding Index chart header
                    if "Artificial Analysis Coding Index" in line or \
                       ("Coding Index" in line and "of 342 models" in lines[i+1] if i+1 < len(lines) else False):
                        found_coding_section = True
                        continue
                    
                    if found_coding_section and ("of 342 models" in line or "+ Add model" in line):
                        in_chart = True
                        continue
                        
                    if in_chart and '{"@context"' in line:
                        break
                        
                    if in_chart and line:
                        chart_lines.append(line)
                
                # Fallback: use the main chart if coding-specific not found
                if not chart_lines:
                    in_chart = False
                    for i, line in enumerate(lines):
                        line = line.strip()
                        if "of 342 models" in line or "+ Add model" in line:
                            in_chart = True
                            continue
                        if in_chart and '{"@context"' in line:
                            break
                        if in_chart and line:
                            chart_lines.append(line)
                            
            else:  # agentic
                # Look for Agentic Index section
                in_chart = False
                chart_lines = []
                found_agentic = False
                
                for i, line in enumerate(lines):
                    line = line.strip()
                    
                    # Look for Agentic Index header
                    if "Artificial Analysis Agentic Index" in line:
                        found_agentic = True
                        continue
                    
                    if found_agentic and ("of 342 models" in line or "+ Add model" in line):
                        in_chart = True
                        continue
                        
                    if in_chart and '{"@context"' in line:
                        break
                        
                    if in_chart and line:
                        chart_lines.append(line)
            
            # Parse chart lines - models come first, then scores
            names = []
            scores = []
            
            for line in chart_lines:
                # Skip "Artificial Analysis" label
                if line == "Artificial Analysis":
                    continue
                    
                score = self._is_score(line)
                if score:
                    scores.append(score)
                elif self._is_model_name(line):
                    clean = re.sub(r'[\U0001F300-\U0001F9FF]', '', line)
                    clean = re.sub(r'\s+', ' ', clean).strip()
                    if clean and len(clean) > 2:
                        names.append(clean)
            
            # Match names with scores (they appear in same order)
            for i, (name, score) in enumerate(zip(names, scores)):
                models.append({
                    "rank": i + 1,
                    "model": name,
                    "score": score
                })
                
            logger.info(f"Extracted {len(models)} models from {index_type} chart")
            
        except Exception as e:
            logger.error(f"Error extracting chart data: {e}")
            
        return models
    
    def _click_tab(self, tab_name: str) -> bool:
        """Click on a specific tab (Intelligence Index, Coding Index, Agentic Index)."""
        try:
            # Try different selectors for the tab
            selectors = [
                f"//button[contains(text(), '{tab_name}')]",
                f"//div[contains(text(), '{tab_name}')]",
                f"//*[contains(@class, 'tab') and contains(text(), '{tab_name}')]",
                f"//*[text()='{tab_name}']"
            ]
            
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            elem.click()
                            time.sleep(2)  # Wait for chart to update
                            logger.info(f"Clicked tab: {tab_name}")
                            return True
                except:
                    continue
                    
            logger.warning(f"Could not find tab: {tab_name}")
            return False
            
        except Exception as e:
            logger.error(f"Error clicking tab {tab_name}: {e}")
            return False
    
    def scrape(self) -> Optional[Dict]:
        """Scrape all benchmark indices by clicking through each tab."""
        try:
            logger.info("Starting scrape...")
            self._setup_driver()
            
            # Load page
            self.driver.get(BASE_URL)
            time.sleep(8)  # Wait for JS rendering
            
            # Scroll down to the Intelligence section
            self.driver.execute_script("window.scrollTo(0, 800);")
            time.sleep(2)
            
            data = {
                "intelligence_index": [],
                "coding_index": [],
                "agentic_index": []
            }
            
            # Extract Intelligence Index (default tab)
            logger.info("Extracting Intelligence Index...")
            self._click_tab("Artificial Analysis Intelligence Index")
            time.sleep(1)
            data["intelligence_index"] = self._extract_chart_data("intelligence")
            
            # Take screenshot of Intelligence Index
            #self.driver.save_screenshot("screenshot_intelligence.png")
            
            # Click Coding Index tab and extract
            logger.info("Extracting Coding Index...")
            if self._click_tab("Coding Index"):
                time.sleep(2)
                data["coding_index"] = self._extract_chart_data("coding")
                #self.driver.save_screenshot("screenshot_coding.png")
            
            # Click Agentic Index tab and extract  
            logger.info("Extracting Agentic Index...")
            if self._click_tab("Agentic Index"):
                time.sleep(2)
                data["agentic_index"] = self._extract_chart_data("agentic")
                #self.driver.save_screenshot("screenshot_agentic.png")
            
            # Take final combined screenshot
            self.driver.execute_script("window.scrollTo(0, 600);")
            time.sleep(1)
            self.driver.save_screenshot("latest_scrape.png")
            
            # Debug: save page content
            body = self.driver.find_element(By.TAG_NAME, "body")
            with open("debug_page.txt", "w", encoding="utf-8") as f:
                f.write(body.text)
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "source": BASE_URL,
                "data": data
            }
            
            total = sum(len(v) for v in data.values())
            logger.info(f"Scraped {total} total models")
            for idx, models in data.items():
                if models:
                    logger.info(f"  {idx}: {len(models)} models (top: {models[0]['model']} @ {models[0]['score']})")
            
            return result
            
        except Exception as e:
            logger.error(f"Scrape failed: {e}", exc_info=True)
            return None
        finally:
            self._close_driver()

# ============================================================================
# MONITOR
# ============================================================================

class BenchmarkMonitor:
    """Monitors for benchmark changes and sends alerts."""
    
    def __init__(self):
        self.scraper = BenchmarkScraper()
    
    def _load_data(self) -> Optional[Dict]:
        """Load saved data."""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Load failed: {e}")
        return None
    
    def _save_data(self, data: Dict):
        """Save data to file."""
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved to {DATA_FILE}")
            
            # Append to history
            history = []
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                except:
                    pass
            history.append(data)
            history = history[-500:]  # Keep last 500
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Save failed: {e}")
    
    def _compare(self, old: Dict, new: Dict) -> List[str]:
        """Find differences between old and new data."""
        changes = []
        
        if not old or not new:
            return changes
        
        index_labels = {
            "intelligence_index": "🧠 Intelligence",
            "coding_index": "💻 Coding", 
            "agentic_index": "🤖 Agentic"
        }
        
        for idx_key, label in index_labels.items():
            old_models = {m["model"]: m for m in old.get("data", {}).get(idx_key, [])}
            new_models = {m["model"]: m for m in new.get("data", {}).get(idx_key, [])}
            
            # New models
            for name, data in new_models.items():
                if name not in old_models:
                    changes.append(f"🆕 {label}: {name} (#{data['rank']}, score {data['score']})")
            
            # Removed models
            for name in old_models:
                if name not in new_models:
                    changes.append(f"❌ {label}: {name} removed")
            
            # Rank changes (top 15 only)
            for name, new_data in new_models.items():
                if name in old_models:
                    old_data = old_models[name]
                    old_rank = old_data.get("rank", 0)
                    new_rank = new_data.get("rank", 0)
                    
                    if old_rank != new_rank and (old_rank <= 15 or new_rank <= 15):
                        diff = old_rank - new_rank
                        arrow = "📈" if diff > 0 else "📉"
                        changes.append(f"{arrow} {label}: {name} #{old_rank}→#{new_rank}")
        
        return changes
    
    def check(self) -> Tuple[bool, List[str]]:
        """Run one check cycle."""
        logger.info("=" * 50)
        logger.info(f"Checking at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Scrape
        new_data = self.scraper.scrape()
        if not new_data:
            logger.error("Scrape failed!")
            return False, []
        
        # Check if we got data
        total = sum(len(new_data.get("data", {}).get(k, [])) for k in ["intelligence_index", "coding_index", "agentic_index"])
        if total == 0:
            logger.warning("No data extracted")
            return False, []
        
        # Load old data
        old_data = self._load_data()
        
        if old_data is None:
            # First run
            logger.info("First run - saving initial state")
            self._save_data(new_data)
            #send_pushover(
            #    "🤖 Benchmark Monitor Started",
            #    f"Tracking {total} models.\nMonitoring Intelligence, Coding & Agentic indices.",
            #    image_path="screenshot_intelligence.png"
            #)
            return False, []
        
        # Compare
        changes = self._compare(old_data, new_data)
        
        if changes:
            logger.info(f"🚨 {len(changes)} changes detected!")
            for c in changes:
                logger.info(f"  {c}")
            
            # Send alert with screenshot
            msg = "\n".join(changes[:10])
            if len(changes) > 10:
                msg += f"\n+{len(changes)-10} more..."
            send_pushover("🚨 Benchmark Changes!", msg, priority=1, image_path="latest_scrape.png")
        else:
            logger.info("✓ No changes")
        
        # Save new data
        self._save_data(new_data)
        
        return len(changes) > 0, changes

# ============================================================================
# MAIN
# ============================================================================

def run_continuous(interval: int = SCRAPE_INTERVAL_MINUTES):
    """Run monitor continuously."""
    import schedule
    
    monitor = BenchmarkMonitor()
    
    print("\n" + "=" * 60)
    print("  Artificial Analysis Benchmark Monitor")
    print(f"  Checking every {interval} minutes")
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    # Initial check
    monitor.check()
    
    # Schedule
    schedule.every(interval).minutes.do(monitor.check)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n\nMonitor stopped.")

def run_once():
    """Single check."""
    monitor = BenchmarkMonitor()
    has_changes, changes = monitor.check()
    
    print("\n" + "=" * 50)
    if has_changes:
        print("CHANGES:")
        for c in changes:
            print(f"  {c}")
    else:
        print("No changes (or first run)")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor AI benchmark changes")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=SCRAPE_INTERVAL_MINUTES, 
                        help=f"Check interval in minutes (default: {SCRAPE_INTERVAL_MINUTES})")
    
    args = parser.parse_args()
    
    # Validate Pushover credentials before starting
    try:
        validate_pushover_credentials()
    except ValueError as e:
        logger.error(f"❌ {e}")
        exit(1)
    
    if args.once:
        run_once()
    else:
        run_continuous(args.interval)
