# Artificial Analysis Benchmark Monitor

Monitors the AI benchmark indices from [artificialanalysis.ai](https://artificialanalysis.ai/) and sends Pushover notifications when changes are detected.

## Tracked Indices

1. **Intelligence Index** - Overall AI capability across 10 evaluations (MMLU-Pro, GPQA Diamond, etc.)
2. **Coding Index** - Coding benchmarks (LiveCodeBench, SciCode, Terminal-Bench Hard)
3. **Agentic Index** - Agentic capabilities (Terminal-Bench Hard, τ²-Bench Telecom)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install selenium webdriver-manager requests schedule certifi
```

### 2. Chrome Browser

Make sure Google Chrome is installed. The script uses ChromeDriver which is automatically managed.

### 3. Configure Environment Variables

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Pushover credentials:
```
PUSHOVER_USER_KEY=your-user-key-here
PUSHOVER_API_TOKEN=your-api-token-here
```

### 4. Pushover Setup (Required for Alerts)

To receive notifications when benchmark rankings change:

1. **Create a Pushover account** at https://pushover.net/ (if you don't have one)
2. **Get your User Key** from the Pushover dashboard
3. **Create an Application** at https://pushover.net/apps/build
   - Give it a name like "AI Benchmark Monitor"
   - Note the **API Token/Key** that's generated
4. **Add both keys to your `.env` file**

## Usage

### Run Once (Test)
```bash
python monitor.py --once
```

### Run Continuously (Default: every 30 minutes)
```bash
python monitor.py
```

### Custom Interval
```bash
python monitor.py --interval 15  # Check every 15 minutes
```

## Output Files

| File | Description |
|------|-------------|
| `benchmark_data.json` | Latest scraped data |
| `benchmark_history.json` | Historical data (last 500 entries) |
| `monitor.log` | Application logs |
| `latest_scrape.png` | Screenshot of last scrape |
| `debug_page.txt` | Page text for debugging |

## Data Format

```json
{
  "timestamp": "2024-01-15T10:30:00.000000",
  "source": "https://artificialanalysis.ai/",
  "data": {
    "intelligence_index": [
      {"rank": 1, "model": "Gemini 3 Pro (Preview)", "score": 73},
      {"rank": 2, "model": "Claude Opus 4.5", "score": 70}
    ],
    "coding_index": [...],
    "agentic_index": [...]
  }
}
```

## Alerts

You'll receive Pushover notifications when:
- **Monitor starts** - Confirmation with number of tracked models
- **New model enters** - A new model appears in an index
- **Model removed** - A model drops out of an index
- **Rank changes** - A model moves up/down in the top 15

## Running in Background (Windows)

### Using Task Scheduler
1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (e.g., "At startup")
4. Action: Start a program
   - Program: `python`
   - Arguments: `C:\APPL\quick_scripts\extract_graphs\monitor.py`
   - Start in: `C:\APPL\quick_scripts\extract_graphs`

### Using pythonw (No Console)
```bash
pythonw monitor.py
```

### Using NSSM (as a Windows Service)
```bash
nssm install BenchmarkMonitor python monitor.py
nssm set BenchmarkMonitor AppDirectory C:\APPL\quick_scripts\extract_graphs
nssm start BenchmarkMonitor
```

## Troubleshooting

### No data extracted
- Check `debug_page.txt` for page content
- Check `latest_scrape.png` for visual verification
- The website may have changed structure

### Pushover not working
- Verify your user key is correct
- Create an application at pushover.net and use its API token
- Check `monitor.log` for error details

### Chrome issues
- Ensure Chrome is installed
- Try updating: `pip install --upgrade webdriver-manager`
