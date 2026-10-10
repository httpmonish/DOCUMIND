$UvicornJob = Start-Job -ScriptBlock { python -m documind.interfaces.cli serve --port 8000 }

Write-Host "Waiting for backend..."
while ($true) {
    try {
        $health = Invoke-RestMethod -Uri http://127.0.0.1:8000/healthz -ErrorAction Stop
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

Write-Host "Backend is up! Healthz:"
$health | ConvertTo-Json -Depth 5

Write-Host "Indexing docs..."
python -m documind.interfaces.cli index ./docs

Write-Host "Running one question via ask..."
$body = @{ question = "What is documind?"; top_k = 2 } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/ask -Method Post -Body $body -ContentType "application/json" | ConvertTo-Json -Depth 5

Write-Host "Starting frontend..."
Set-Location Documind-frontend
$HttpJob = Start-Job -ScriptBlock { python -m http.server 5500 }

Write-Host "Open http://localhost:5500/stitch_documind_glass_box_ui/code.html"

try {
    Wait-Job -Job $UvicornJob, $HttpJob
} finally {
    Stop-Job -Job $UvicornJob, $HttpJob
}
