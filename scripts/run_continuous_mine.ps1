$ErrorActionPreference = "Stop"

$env:WQ_AUTH_MODE = "basic"
$env:WQ_MAX_POLL_ATTEMPTS = "120"
$env:WQ_POLL_INTERVAL_SECONDS = "5"
$env:WQ_STORAGE_PATH = "data/continuous_mine.db"
$env:WQ_OUTPUT_DIR = "outputs_continuous"
$env:WQ_LOG_DIR = "logs"

C:\Users\USER\anaconda3\python.exe -m app mine --cycles 999999 --sleep-seconds 5
