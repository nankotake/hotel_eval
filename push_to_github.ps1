# push_to_github.ps1 —— 把 hotel_eval 推到 GitHub（公开仓库）
#
# 用法：
#   .\push_to_github.ps1                 # 自动检测 gh / 手动 git 两种方式
#   .\push_to_github.ps1 -User <用户名>  # 指定 GitHub 用户名（跳过输入）
#
# 注意：脚本不做网络代理/认证，需在能连上 github.com 的机器上运行。
# 推送前会自动检查是否误把 config.json（含 API key）等敏感文件加进来。

param([string]$User = "")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== 安全检查：敏感文件是否被误跟踪 =="
$secrets = git grep -n -i -E "sk-[A-Za-z0-9]{10,}|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}"
if ($secrets) { Write-Warning "发现疑似敏感信息（请先处理再推送）：`n$secrets"; exit 1 }
$ignored = git check-ignore hotel_eval/data/config.json
if (-not $ignored) { Write-Warning "config.json 未被 .gitignore 忽略，请先处理！"; exit 1 }
Write-Host "  通过。"

# 1) 尝试 gh CLI
if (Get-Command gh -ErrorAction SilentlyContinue) {
    Write-Host "== 检测到 gh CLI =="
    gh auth status *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "gh 已登录，创建并推送..."
        gh repo create hotel_eval --public --source=. --remote=origin --push
        Write-Host "完成：https://github.com/$(gh repo view hotel_eval --json nameWithOwner -q .nameWithOwner)"
        exit 0
    } else {
        Write-Host "gh 未登录，回退到手动 git 方式..."
    }
}

# 2) 手动 git 方式
if (-not $User) { $User = Read-Host "GitHub 用户名" }
$url = "https://github.com/$User/hotel_eval.git"

Write-Host "== 手动推送 =="
Write-Host "请先在 https://github.com/new 创建公开空仓库 hotel_eval（不要勾选 README/.gitignore/license）。"
if (-not (git remote -v | Select-String "origin")) {
    git remote add origin $url
} else {
    git remote set-url origin $url
}
git push -u origin main
Write-Host "完成：$url"
