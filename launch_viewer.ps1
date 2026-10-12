param(
    [string]$IndexPath,
    [switch]$NoBrowser
)

Add-Type -AssemblyName System.Windows.Forms

$defaultIndex = Join-Path $PSScriptRoot 'paper_index.json'
if ($IndexPath) {
    $selectedPath = [System.IO.Path]::GetFullPath($IndexPath)
} else {
    $selectedPath = $defaultIndex
}

try {
    $index = [System.IO.File]::ReadAllText($selectedPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $index.papers) { throw 'JSON 中没有 papers 列表。' }
    $indexDirectory = [System.IO.Path]::GetDirectoryName($selectedPath)
    $allowedRoot = $indexDirectory.TrimEnd('\') + [System.IO.Path]::DirectorySeparatorChar
    foreach ($paper in $index.papers) {
        foreach ($relative in @([string]$paper.metadata.relative_path, [string]$paper.method_document)) {
            if (-not $relative) { continue }
            $path = [System.IO.Path]::GetFullPath((Join-Path $indexDirectory $relative))
            if (-not $path.StartsWith($allowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "论文路径超出索引目录：$relative"
            }
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "找不到论文文件：$relative" }
        }
    }
    $pythonCommand = Get-Command python.exe -ErrorAction Stop
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'paper_server.py'))) { throw '找不到 paper_server.py。' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'paper_viewer.html'))) { throw '找不到 paper_viewer.html。' }

    $sessionId = [Guid]::NewGuid().ToString('N')
    $stdoutPath = Join-Path ([System.IO.Path]::GetTempPath()) "paper_viewer_$sessionId.out"
    $stderrPath = Join-Path ([System.IO.Path]::GetTempPath()) "paper_viewer_$sessionId.err"
    $argumentList = @('-u', ('"' + (Join-Path $PSScriptRoot 'paper_server.py') + '"'), '--index', ('"' + $selectedPath + '"'), '--viewer-dir', ('"' + $PSScriptRoot + '"'))
    $server = Start-Process -FilePath $pythonCommand.Source -ArgumentList $argumentList -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $url = $null
    for ($attempt = 0; $attempt -lt 100; $attempt++) {
        Start-Sleep -Milliseconds 100
        if (Test-Path -LiteralPath $stdoutPath) {
            $url = Get-Content -LiteralPath $stdoutPath -TotalCount 1 -ErrorAction SilentlyContinue
            if ($url -match '^http://127\.0\.0\.1:\d+/$') { break }
        }
        if ($server.HasExited) { break }
    }
    if ($url -notmatch '^http://127\.0\.0\.1:\d+/$') {
        $detail = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { '' }
        throw "本地服务未能启动。$detail"
    }
    if ($NoBrowser) { Write-Output $url } else { Start-Process $url }
} catch {
    [System.Windows.Forms.MessageBox]::Show(
        "无法打开论文查看器。`n`n$($_.Exception.Message)",
        '启动失败',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}
