param(
    [string]$ApiUrl = "http://localhost:8000/api/emergency-packets",
    [string]$Packet = "v1|AIT001|21:04|170|18|WARNING|REQ_WATER"
)

$body = @{
    packet = $Packet
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri $ApiUrl `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
