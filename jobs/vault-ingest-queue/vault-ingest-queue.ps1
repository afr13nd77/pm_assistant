# vault-ingest-queue — ночная обработка очереди raw по ingest_dod (BL-118)
# Headless Claude Code, модель закреплена: claude-sonnet-4-6
# Регистрация: см. README.md в этой папке

$Vault   = "I:\Work\Sutochno_ru\08 project hotels claude"
$JobDir  = "I:\ai_projects\pm_assistant\jobs\vault-ingest-queue"
$LogDir  = Join-Path $JobDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$RunLog  = Join-Path $LogDir ("run-" + (Get-Date -Format "yyyy-MM-dd_HHmm") + ".log")

function Log($msg) { "[{0}] {1}" -f (Get-Date -Format o), $msg | Add-Content -Encoding UTF8 $RunLog }

# Защита от параллельного запуска (ручной + Task Scheduler)
$Lock = Join-Path $JobDir ".lock"
if (Test-Path $Lock) {
    $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
    if ($age.TotalHours -lt 3) {
        Log "SKIP: уже идёт прогон ($(Get-Content $Lock -Raw)); lock-возраст $([int]$age.TotalMinutes) мин"
        exit 0
    }
    Log "WARN: устаревший lock (>3ч) — перехватываю"
}
"pid=$PID started=$(Get-Date -Format o)" | Set-Content -Encoding UTF8 $Lock

Log "START pid=$PID user=$env:USERNAME"

try {
    $Claude = Get-Command claude -ErrorAction Stop
    Log "claude: $($Claude.Source)"
    Log ("version: " + (& claude --version 2>&1 | Out-String).Trim())

    $Prompt = Get-Content -Raw -Encoding UTF8 (Join-Path $JobDir "vault-ingest-queue.prompt.md")
    Set-Location $Vault
    Log "cwd: $Vault; запускаю прогон..."

    # acceptEdits: автоодобрение файловых правок; bash ограничен командами чтения
    & claude -p $Prompt `
        --model claude-sonnet-4-6 `
        --permission-mode acceptEdits `
        --allowedTools "Read" "Glob" "Grep" "Write" "Edit" "Bash(grep:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(find:*)" `
        *>> $RunLog

    Log "EXIT code=$LASTEXITCODE"
}
catch {
    Log "FATAL: $($_.Exception.Message)"
    Log $_.ScriptStackTrace
    Remove-Item $Lock -Force -ErrorAction SilentlyContinue
    exit 1
}
Remove-Item $Lock -Force -ErrorAction SilentlyContinue

# Ротация: храним 30 последних логов
Get-ChildItem $LogDir -Filter "run-*.log" |
  Sort-Object Name -Descending | Select-Object -Skip 30 | Remove-Item -Force
