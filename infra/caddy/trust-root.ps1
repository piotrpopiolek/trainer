# Trust Caddy's local CA so https://localhost works in Chrome/Edge (FR-005a same-origin).
# Run from repo root:
#   powershell -ExecutionPolicy Bypass -File infra/caddy/trust-root.ps1

$ErrorActionPreference = "Stop"
$root = Join-Path $PSScriptRoot "data/caddy/pki/authorities/local/root.crt"

if (-not (Test-Path $root)) {
    Write-Host "Root CA not found at $root"
    Write-Host "Start the stack first: docker compose up -d"
    exit 1
}

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2((Resolve-Path $root))
$store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
    [System.Security.Cryptography.X509Certificates.StoreName]::Root,
    [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
)
$store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
try {
    $existing = $store.Certificates.Find(
        [System.Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint,
        $cert.Thumbprint,
        $false
    )
    if ($existing.Count -gt 0) {
        Write-Host "Caddy local CA already trusted ($($cert.Subject))."
    }
    else {
        $store.Add($cert)
        Write-Host "Trusted Caddy local CA ($($cert.Subject))."
    }
}
finally {
    $store.Close()
}

Write-Host "Restart the browser, then open https://localhost"
