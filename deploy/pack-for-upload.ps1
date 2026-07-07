# 打包 poster 上传包（排除本地开发文件）
# 用法: powershell -File deploy/pack-for-upload.ps1

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Out = Join-Path $Root "poster-upload.zip"

if (Test-Path $Out) { Remove-Item $Out -Force }

$exclude = @(
    ".env",
    ".env.example",
    ".git",
    "__pycache__",
    "*.pyc",
    "server-8010*.err.log",
    "test_*.py",
    "data\poster.db",
    "data\config.json",
    "data\apiclient_key.pem",
    "data\payment-screenshots\*",
    "data\reference-images\*",
    "outputs\*"
)

Push-Location $Root
try {
    $items = Get-ChildItem -Force | Where-Object {
        $name = $_.Name
        if ($name -eq ".env") { return $false }
        if ($name -match "^server-8010") { return $false }
        if ($name -match "^test_") { return $false }
        return $true
    }
    Compress-Archive -Path $items.FullName -DestinationPath $Out -Force
    Write-Host "已生成: $Out"
    Write-Host "上传到 /www/wwwroot/poster.ms1001.com 解压后执行:"
    Write-Host "  bash deploy/setup-production.sh"
}
finally {
    Pop-Location
}
