$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot ".runtime"
$TempDir = Join-Path $ProjectRoot "tmp"
$Archive = Join-Path $TempDir "python-3.12.10-embed-amd64.zip"
$DownloadUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
$ExpectedMd5 = "FE8EF205F2E9C3BA44D0CF9954E1ABD3"

New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
if (-not (Test-Path -LiteralPath $Archive)) {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $Archive
}

$ActualMd5 = (Get-FileHash -Algorithm MD5 -LiteralPath $Archive).Hash
if ($ActualMd5 -ne $ExpectedMd5) {
    throw "Portable Python checksum mismatch. Expected $ExpectedMd5 but received $ActualMd5."
}

if (Test-Path -LiteralPath $RuntimeDir) {
    Remove-Item -LiteralPath $RuntimeDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $RuntimeDir -Force

$PathFile = Join-Path $RuntimeDir "python312._pth"
$Lines = Get-Content -LiteralPath $PathFile
if ($Lines -notcontains "..\src") {
    $InsertAt = [Array]::IndexOf($Lines, ".") + 1
    $Lines = @($Lines[0..($InsertAt - 1)]) + "..\src" + @($Lines[$InsertAt..($Lines.Length - 1)])
    [System.IO.File]::WriteAllLines($PathFile, $Lines, [System.Text.UTF8Encoding]::new($false))
}

& (Join-Path $RuntimeDir "python.exe") -X utf8 -c "import encodings; import shopee_listing_app; print('portable Python OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Portable Python validation failed."
}
