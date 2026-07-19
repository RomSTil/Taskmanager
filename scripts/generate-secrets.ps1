$jwtBytes = New-Object byte[] 48
[Security.Cryptography.RandomNumberGenerator]::Fill($jwtBytes)
$setupBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($setupBytes)
$encryptionBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($encryptionBytes)

Write-Output "TASKMAN_JWT_SECRET=$([Convert]::ToBase64String($jwtBytes))"
Write-Output "TASKMAN_SETUP_TOKEN=$([Convert]::ToBase64String($setupBytes))"
$fernetKey = [Convert]::ToBase64String($encryptionBytes).Replace('+', '-').Replace('/', '_')
Write-Output "TASKMAN_ENCRYPTION_KEY=$fernetKey"
