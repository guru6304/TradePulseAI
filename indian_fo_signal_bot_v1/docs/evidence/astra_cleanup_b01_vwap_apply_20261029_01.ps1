# Delete only inventory-listed, untracked project bytecode. Dry run is the default.
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Stage = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Stage)) {
    $Stage = if ($Apply) { 'b01_vwap_apply_20261029_01' } else { 'b01_vwap_dryrun_20261029_01' }
}
if ($Stage -notmatch '^[a-z0-9_]{2,60}$') { throw 'Use a unique simple lower-case stage.' }

$appRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $appRoot '..'))
$evidenceRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$inventoryPath = Join-Path $evidenceRoot 'astra_cleanup_inventory_b01_vwap_20261029_01.json'
$receiptPath = Join-Path $evidenceRoot ('astra_cleanup_' + $Stage + '.json')
$logPath = Join-Path $evidenceRoot ('astra_cleanup_' + $Stage + '.txt')
$cacheRoots = @(
    [IO.Path]::GetFullPath((Join-Path $appRoot '__pycache__')),
    [IO.Path]::GetFullPath((Join-Path $appRoot 'docs\evidence\__pycache__'))
)
$comparison = [StringComparison]::OrdinalIgnoreCase
$reparsePoint = [IO.FileAttributes]::ReparsePoint
$utf8 = New-Object Text.UTF8Encoding($false)
$results = New-Object 'Collections.Generic.List[object]'
$directoryResults = New-Object 'Collections.Generic.List[object]'
$errors = New-Object 'Collections.Generic.List[object]'
$targets = New-Object 'Collections.Generic.List[object]'
$seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$tracked = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$validated = $false
$removedCount = 0
$removedBytes = [long]0
$receiptStream = $null
$logStream = $null

function Get-ExistingItem([string]$LiteralPath) {
    try { return Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -eq [Management.Automation.ErrorCategory]::ObjectNotFound) {
            return $null
        }
        throw
    }
}

function Assert-NoReparseChain([string]$LiteralPath) {
    $cursor = [IO.Path]::GetFullPath($LiteralPath)
    while (-not [string]::IsNullOrEmpty($cursor)) {
        $item = Get-ExistingItem $cursor
        if ($null -ne $item -and ($item.Attributes -band $reparsePoint) -ne 0) {
            throw ('Reparse point rejected: ' + $cursor)
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ([string]::Equals($parent, $cursor, $comparison)) { break }
        $cursor = $parent
    }
}

function Assert-Contained([string]$LiteralPath) {
    $resolved = [IO.Path]::GetFullPath($LiteralPath)
    if (-not $resolved.StartsWith($workspaceRoot + [IO.Path]::DirectorySeparatorChar, $comparison)) {
        throw 'Target is outside the verified workspace.'
    }
}

function Assert-CacheTarget([string]$LiteralPath, [string]$RelativePath) {
    Assert-Contained $LiteralPath
    $resolved = [IO.Path]::GetFullPath($LiteralPath)
    $parent = [IO.Path]::GetDirectoryName($resolved)
    if (-not ($cacheRoots | Where-Object { [string]::Equals($_, $parent, $comparison) })) {
        throw 'Target is not an immediate child of an approved project cache directory.'
    }
    if ($RelativePath -notmatch '^indian_fo_signal_bot_v1/(?:__pycache__|docs/evidence/__pycache__)/[A-Za-z0-9_.-]+\.(?:pyc|pyo)$') {
        throw 'Target is not an exact ordinary project-bytecode path.'
    }
    $expected = [IO.Path]::GetFullPath((Join-Path $workspaceRoot $RelativePath.Replace('/', '\')))
    if (-not [string]::Equals($resolved, $expected, $comparison)) {
        throw 'Absolute and relative inventory targets disagree.'
    }
    if ($tracked.Contains($RelativePath)) { throw 'Tracked file rejected.' }
    Assert-NoReparseChain $resolved
    $item = Get-ExistingItem $resolved
    if ($null -ne $item -and ($item.PSIsContainer -or $item -isnot [IO.FileInfo])) {
        throw 'Only ordinary bytecode files may be removed.'
    }
    return $item
}

function Write-Log([object]$Record) {
    $logStream.WriteLine(($Record | ConvertTo-Json -Depth 10 -Compress))
    $logStream.Flush()
}

$receipt = [ordered]@{
    schema = 'tradepulse.exact-cache-cleanup.v1'
    status = 'IN_PROGRESS'
    mode = if ($Apply) { 'APPLY' } else { 'DRY_RUN' }
    started_at = [DateTime]::UtcNow.ToString('o')
    command = @('astra_cleanup_b01_vwap_apply_20261029_01.ps1', '-Stage', $Stage)
    allowed_cache_roots = $cacheRoots
    inventory = 'docs/evidence/astra_cleanup_inventory_b01_vwap_20261029_01.json'
    inventory_sha256_before = $null
    inventory_sha256_after = $null
    script_sha256 = $null
    planned_files = 0
    all_targets_validated_before_deletion = $false
    provider_requests = 0
    operational_database_accessed = $false
    environment_or_private_payloads_read = $false
    tracked_files_removed = 0
    images_removed = 0
    private_directories_descended = $false
    access_denied_history_directory = 'PRESERVED_UNINSPECTED'
    recursive_delete_used = $false
    directory_delete_policy = 'Directory.Delete(path,false); atomically refuses nonempty directories'
}
if ($Apply) { $receipt.command += '-Apply' }

try {
    Assert-NoReparseChain $workspaceRoot
    Assert-NoReparseChain $evidenceRoot
    Assert-NoReparseChain $PSCommandPath
    foreach ($root in $cacheRoots) { Assert-Contained $root; Assert-NoReparseChain $root }
    if ((Test-Path -LiteralPath $receiptPath) -or (Test-Path -LiteralPath $logPath)) {
        throw 'Existing cleanup evidence is immutable; choose a new stage.'
    }
    $receiptStream = [IO.File]::Open($receiptPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $logFile = [IO.File]::Open($logPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $logStream = New-Object IO.StreamWriter($logFile, $utf8)
    $receipt.script_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt.inventory_sha256_before = (Get-FileHash -LiteralPath $inventoryPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $inventory = [IO.File]::ReadAllText($inventoryPath, $utf8) | ConvertFrom-Json
    if ($inventory.schema -ne 'tradepulse.safe-cleanup-inventory.v1' -or
        $inventory.status -ne 'PASS_READ_ONLY_INVENTORY' -or
        -not [string]::Equals([IO.Path]::GetFullPath($inventory.workspace), $workspaceRoot, $comparison)) {
        throw 'Inventory identity or workspace validation failed.'
    }
    $gitRootOutput = @(& git -C $workspaceRoot rev-parse --show-toplevel)
    if ($LASTEXITCODE -ne 0 -or $gitRootOutput.Count -ne 1 -or
        -not [string]::Equals([IO.Path]::GetFullPath($gitRootOutput[0]), $workspaceRoot, $comparison)) {
        throw 'Git root must match the intended workspace.'
    }
    $trackedOutput = @(& git -C $workspaceRoot ls-files --full-name)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot establish tracked-file exclusions.' }
    foreach ($entry in $trackedOutput) { [void]$tracked.Add($entry.Replace('\', '/')) }
    $candidates = @($inventory.cache_deletion_candidates)
    if ($candidates.Count -ne $inventory.candidate_file_count -or $candidates.Count -ne 103) {
        throw 'The immutable inventory must declare exactly 103 candidates.'
    }
    $receipt.planned_files = $candidates.Count
    foreach ($candidate in $candidates) {
        if ($candidate.action -ne 'DELETE_CANDIDATE' -or
            $candidate.reason -ne 'UNTRACKED_REGENERABLE_PROJECT_PYTHON_BYTECODE') {
            throw 'Inventory contains a non-bytecode cleanup action.'
        }
        $relativePath = [string]$candidate.path
        $absolutePath = [IO.Path]::GetFullPath([string]$candidate.absolute_path)
        if (-not $seen.Add($absolutePath)) { throw 'Duplicate inventory target rejected.' }
        $item = Assert-CacheTarget $absolutePath $relativePath
        $targets.Add([pscustomobject]@{
            path = $relativePath
            absolute_path = $absolutePath
            inventory_size_bytes = [long]$candidate.size_bytes
            preflight_size_bytes = if ($null -ne $item) { [long]$item.Length } else { [long]0 }
            existed_at_preflight = $null -ne $item
        })
    }
    $currentManifestHash = (Get-FileHash -LiteralPath $inventoryPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($currentManifestHash -ne $receipt.inventory_sha256_before) { throw 'Inventory changed during preflight.' }
    $validated = $true
    $receipt.all_targets_validated_before_deletion = $true
    Write-Log ([ordered]@{ event = 'PREFLIGHT_PASS'; targets = $targets.Count; mode = $receipt.mode })
    foreach ($target in $targets) {
        try {
            # Recheck ancestors and type immediately before each removal.
            $item = Assert-CacheTarget $target.absolute_path $target.path
            if ($null -eq $item) {
                $outcome = [ordered]@{ path = $target.path; outcome = 'ALREADY_MISSING'; removed_bytes = 0 }
            } elseif (-not $Apply) {
                $outcome = [ordered]@{ path = $target.path; outcome = 'WOULD_REMOVE'; current_size_bytes = [long]$item.Length;
                    inventory_size_bytes = $target.inventory_size_bytes; removed_bytes = 0 }
            } else {
                $sizeBefore = [long]$item.Length
                Remove-Item -LiteralPath $target.absolute_path -ErrorAction Stop
                if ($null -ne (Get-ExistingItem $target.absolute_path)) { throw 'Target still exists after removal.' }
                $removedCount += 1
                $removedBytes += $sizeBefore
                $outcome = [ordered]@{ path = $target.path; outcome = 'REMOVED'; removed_bytes = $sizeBefore;
                    inventory_size_bytes = $target.inventory_size_bytes; existed_after = $false }
            }
            $results.Add([pscustomobject]$outcome)
            Write-Log $outcome
        } catch {
            $errorRecord = [ordered]@{ path = $target.path; outcome = 'ERROR_STOPPED_REMAINING_CLEANUP'; error = $_.Exception.Message }
            $errors.Add([pscustomobject]$errorRecord)
            Write-Log $errorRecord
            break
        }
    }
    if ($errors.Count -eq 0) {
        foreach ($root in $cacheRoots) {
            try {
                Assert-Contained $root
                Assert-NoReparseChain $root
                $directory = Get-ExistingItem $root
                if ($null -eq $directory) { $outcome = [ordered]@{ path = $root; outcome = 'ALREADY_MISSING' } }
                elseif (-not $directory.PSIsContainer) { throw 'Approved cache root is no longer a directory.' }
                elseif (-not $Apply) { $outcome = [ordered]@{ path = $root; outcome = 'NOT_REMOVED_DRY_RUN' } }
                elseif ([IO.Directory]::GetFileSystemEntries($root).Length -gt 0) {
                    $outcome = [ordered]@{ path = $root; outcome = 'KEPT_NONEMPTY_NO_RECURSION' }
                } else {
                    [IO.Directory]::Delete($root, $false)
                    $outcome = [ordered]@{ path = $root; outcome = 'REMOVED_EMPTY_DIRECTORY'; existed_after = [IO.Directory]::Exists($root) }
                    if ($outcome.existed_after) { throw 'Cache directory was recreated after removal.' }
                }
                $directoryResults.Add([pscustomobject]$outcome)
                Write-Log $outcome
            } catch {
                $errorRecord = [ordered]@{ path = $root; outcome = 'DIRECTORY_NOT_REMOVED'; error = $_.Exception.Message }
                $errors.Add([pscustomobject]$errorRecord)
                Write-Log $errorRecord
            }
        }
    }
} catch {
    $errorRecord = [ordered]@{ phase = if ($validated) { 'APPLY_OR_DRY_RUN' } else { 'PREFLIGHT' }; error = $_.Exception.Message }
    $errors.Add([pscustomobject]$errorRecord)
    if ($null -ne $logStream) { Write-Log $errorRecord }
} finally {
    $receipt.completed_at = [DateTime]::UtcNow.ToString('o')
    $receipt.removed_files = $removedCount
    $receipt.removed_bytes = $removedBytes
    $receipt.file_results = @($results.ToArray())
    $receipt.directory_results = @($directoryResults.ToArray())
    $receipt.errors = @($errors.ToArray())
    if ($null -ne $receipt.inventory_sha256_before) {
        try {
            $receipt.inventory_sha256_after = (Get-FileHash -LiteralPath $inventoryPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($receipt.inventory_sha256_after -ne $receipt.inventory_sha256_before) {
                $errors.Add([pscustomobject]@{ phase = 'FINAL_MANIFEST_CHECK'; error = 'Inventory changed during cleanup.' })
                $receipt.errors = @($errors.ToArray())
            }
        } catch {
            $errors.Add([pscustomobject]@{ phase = 'FINAL_MANIFEST_CHECK'; error = $_.Exception.Message })
            $receipt.errors = @($errors.ToArray())
        }
    }
    $receipt.status = if ($errors.Count -gt 0) { if ($validated -and $Apply) { 'PARTIAL' } else { 'FAIL' } }
        elseif ($Apply) { 'PASS' } else { 'PASS_DRY_RUN' }
    $receipt.exit_code = if ($errors.Count -gt 0) { 1 } else { 0 }
    if ($null -ne $logStream) {
        Write-Log ([ordered]@{ event = 'COMPLETE'; status = $receipt.status; removed_files = $removedCount; removed_bytes = $removedBytes })
        $logStream.Dispose()
        $receipt.log = 'docs/evidence/' + [IO.Path]::GetFileName($logPath)
        $receipt.log_sha256 = (Get-FileHash -LiteralPath $logPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    if ($null -ne $receiptStream) {
        $body = $utf8.GetBytes(($receipt | ConvertTo-Json -Depth 12) + [Environment]::NewLine)
        $receiptStream.SetLength(0)
        $receiptStream.Write($body, 0, $body.Length)
        $receiptStream.Flush()
        $receiptStream.Dispose()
    }
}

[ordered]@{ status = $receipt.status; mode = $receipt.mode; planned_files = $receipt.planned_files;
    removed_files = $removedCount; removed_bytes = $removedBytes; receipt = [IO.Path]::GetFileName($receiptPath);
    errors = $errors.Count; exit_code = $receipt.exit_code } | ConvertTo-Json -Compress
exit $receipt.exit_code
