#!/usr/bin/env bash

set -euo pipefail

# Project directory: use MY_PROJECT_DIR if set, otherwise fallback to default
PROJECT_DIR="${MY_PROJECT_DIR:-/home/z/my-project}"
# Code package URL placeholders (replaced with actual URLs before upload by
# upload-to-oss.ts). CODE_TAR_URL 是首选源（OSS 内网 endpoint，同 region VPC
# 直连，~几百 ms）；CODE_TAR_FALLBACK_URL 是备用源（公网 CDN），仅当内网下载
# 失败时兜底——少数 FC instance 的 VPC 内网偶发劣化时不至于彻底卡死。
CODE_TAR_URL="https://sandbox-public.oss-cn-hongkong-internal.aliyuncs.com/fullstack/code_1785226337571.tar"
CODE_TAR_FALLBACK_URL="https://z-cdn.chatglm.cn/fullstack/code_1785226337571.tar"

# Fixed behavior: keep existing target directory contents; run dev.sh after extraction
SKIP_DEV="false"

TMP_ROOT=""

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

err() {
  printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

cleanup() {
  if [ -n "${TMP_ROOT}" ] && [ -d "${TMP_ROOT}" ]; then
    rm -rf "${TMP_ROOT}" || true
  fi
}

trap cleanup EXIT INT TERM

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "command not found: $cmd"
    exit 1
  fi
}

download_tarball() {
  local src="$1"
  local out="$2"
  # 第三参 = curl 的重试/超时策略。主源和备用源必须用不同的策略，理由见
  # download_tarball_with_fallback。默认值保持改造前的行为，这样漏传也不会变慢/变脆。
  local curl_opts="${3:---retry 3 --retry-delay 2 --connect-timeout 10}"

  case "$src" in
    http://*|https://*)
      log "Downloading package from HTTP(S): $src"
      # shellcheck disable=SC2086 -- $curl_opts 需要词分割成多个独立参数，不能加引号
      curl -fL ${curl_opts} --max-time 1800 "$src" -o "$out"
      ;;
    oss://*)
      if ! command -v ossutil >/dev/null 2>&1; then
        err "ossutil is required for oss:// URLs but was not found in PATH"
        err "install ossutil or provide a pre-signed https URL"
        exit 1
      fi

      log "Downloading package from OSS: $src"
      # If OSS credentials are provided as env vars, configure ossutil for this run.
      if [ -n "${OSS_ACCESS_KEY_ID:-}" ] && [ -n "${OSS_ACCESS_KEY_SECRET:-}" ] && [ -n "${OSS_ENDPOINT:-}" ]; then
        ossutil config -e "$OSS_ENDPOINT" -i "$OSS_ACCESS_KEY_ID" -k "$OSS_ACCESS_KEY_SECRET" >/dev/null
      fi

      ossutil cp "$src" "$out" -f
      ;;
    *)
      err "unsupported --code-tar-url scheme: $src"
      err "supported: https://..., http://..., oss://..."
      exit 1
      ;;
  esac
}

# download_tarball_with_fallback 先用首选源（OSS 内网）下载，失败再退到备用源
# （公网 CDN）。内网链路对绝大多数 instance 是 VPC 直连（~几百 ms），但个别
# instance 的 VPC 内网会偶发劣化——这时 connect-timeout 快速失败后自动切到公网
# CDN，避免像过去那样卡在单一公网源上 76s 直到 completion 整体超时。
download_tarball_with_fallback() {
  local primary="$1"
  local fallback="$2"
  local out="$3"

  # 主源**不重试**，3 秒建不上连就走 fallback。
  #
  # 为什么：主源是 HK 的 oss-*-internal 端点，BJ 跨区根本连不上，必然超时。
  # 原策略 --retry 3 --connect-timeout 10 = 4 次尝试 ≈ 46 秒白等（实测
  # 03:59:32 → 04:00:18）。而这 46 秒**不只是慢**：initFullstack 同步阻塞在
  # session ready 之前，46 秒会顶穿 wsmgr 的 20 秒 session 闸门 →
  # 闸门返回 503 session_pending → z-ai-backend 把 MCP init 的 503 当硬失败 →
  # 整个对话判 failed（raw_error: workspace tool initialization failed）。
  # 2026-09-24 实测：BJ 近 90 分钟 11 次闸门 503 / 5 次 ready，全部是这条链；
  # 「恢复」路径因为 init_fullstack 提前 return 只要 3 秒，所以表现为双峰。
  #
  # 韧性由 fallback 提供，不由 retry 提供 —— 对一个连不上的源重试，是纯粹的等待。
  # connect-timeout 只管 TCP 建连（HK VPC 内网是毫秒级，3 秒有 300 倍余量），
  # 传输慢不受影响，那由下面的 --max-time 1800 管。
  if download_tarball "$primary" "$out" "--retry 0 --connect-timeout 3"; then
    return 0
  fi

  # 备用源缺失（占位符未替换 / 与主源相同）时不重复尝试。
  # 占位符判据必须是「未渲染的模板串」本身，不能是渲染后的真实 URL——
  # 2026-09-23 修：原判据写成了 CODE_TAR_FALLBACK_URL 的实际值，导致
  # fallback 分支恒 return 1（HK 因主源可达从不暴露；BJ 沙盒跨区连不上
  # HK 的 oss-*-internal 端点，主源必失败，于是初始化 100% 卡死）。
  if [ -z "$fallback" ] || [ "$fallback" = "__CODE_TAR_FALLBACK_URL__" ] || [ "$fallback" = "$primary" ]; then
    err "primary download failed and no usable fallback URL"
    return 1
  fi

  err "primary source failed, falling back to: $fallback"
  # fallback 保留原重试强度：它是最后一道，失败就等于初始化失败。
  download_tarball "$fallback" "$out" "--retry 3 --retry-delay 2 --connect-timeout 10"
}

prepare_target_dir() {
  local dir="$1"

  mkdir -p "$dir"

  if [ -n "$(ls -A "$dir" 2>/dev/null || true)" ]; then
    log "Target directory is not empty, keeping existing contents: $dir"
  fi
}

extract_project() {
  local tar_file="$1"
  local target_dir="$2"
  local unpack_dir="$3"
  local tar_flags=""

  log "Validating tar package"
  if tar -tzf "$tar_file" >/dev/null 2>&1; then
    tar_flags="z"
  elif tar -tf "$tar_file" >/dev/null 2>&1; then
    tar_flags=""
  else
    err "invalid tar package: $tar_file"
    exit 1
  fi

  log "Extracting package to temp directory"
  mkdir -p "$unpack_dir"
  tar -x${tar_flags}f "$tar_file" -C "$unpack_dir"

  local source_root="$unpack_dir"
  local child_count
  child_count="$(find "$unpack_dir" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"

  if [ "$child_count" = "1" ] && [ -z "$(find "$unpack_dir" -mindepth 1 -maxdepth 1 -type f -print -quit)" ]; then
    source_root="$(find "$unpack_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  fi

  log "Copying project files into target directory"
  cp -a "$source_root"/. "$target_dir"/

  rewrite_lockfile_registry "$target_dir"
}

# 把 lockfile 里锁死的 registry 域名改成本 region 的镜像源。
#
# 为什么必须改 lockfile：脚手架自带的 bun.lock 把**每个包的下载地址**都写成了
# 绝对 URL（937 条 https://registry.npmjs.com/...）。bun install 按 lockfile 里的
# URL 直接取包，完全绕过 NPM_CONFIG_REGISTRY —— 所以给沙箱注入那个 env 对它无效。
#
# 国内站实测（BJ 沙箱 → 两个源，同一个 next@15.1.6）：
#   registry.npmjs.com      metadata 30s（撞超时）   tarball 25MB / 59.4s / 423KB/s
#   registry.npmmirror.com  metadata  1.6s           tarball 25MB /  0.89s / 28MB/s
# 937 个包累积起来 bun install 要跑 7 分钟（实测 14:58:07 → 15:05:13），
# 期间 dev server 起不来、3000 不监听、preview 恒 502，用户看到「起不来」。
# 香港访问 npmjs 只要 0.14s，所以这个缺陷只在国内站暴露。
#
# 位置：必须在 cp 完脚手架之后、run_dev_script（→ dev.sh → bun install）之前。
# 放在沙箱的 start.sh 里是无效的——那时脚手架还没解包，bun.lock 不存在。
#
# 香港不配 NPM_CONFIG_REGISTRY ⇒ 整段跳过，行为逐字节不变。
rewrite_lockfile_registry() {
  local target_dir="$1"

  if [ -z "${NPM_CONFIG_REGISTRY:-}" ]; then
    log "NPM_CONFIG_REGISTRY not set, keep lockfile registry as-is"
    return 0
  fi

  # 用 shell 参数展开取 host，不走 sed：提取和改写依赖同一个外部命令时，
  # 那个命令一出问题就变成「host 为空 → 静默跳过」，连告警都没有。
  local reg_host="${NPM_CONFIG_REGISTRY#*://}"
  reg_host="${reg_host%%/*}"
  reg_host="${reg_host%%:*}"
  if [ -z "$reg_host" ]; then
    err "NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY} 解析不出 host，lockfile 未改写"
    return 0
  fi

  # 本文件 set -euo pipefail：这一段里任何非 0 返回都会中断整个初始化，
  # 而改写 registry 只是优化，不该阻断脚手架启动。显式隔离。
  set +e
  local ok=0 failed=0 lock
  for lock in $(find "$target_dir" -maxdepth 4 -name bun.lock -not -path '*/node_modules/*' 2>/dev/null); do
    grep -q 'registry\.npmjs\.com' "$lock" 2>/dev/null || continue
    sed -i "s#registry\.npmjs\.com#${reg_host}#g" "$lock" 2>/dev/null
    # ★ 回读校验：不能只看 sed 的返回码。自测时在 BSD sed 上遇到
    #   "invalid command code"——sed 失败了而脚本照样报成功。
    if grep -q 'registry\.npmjs\.com' "$lock" 2>/dev/null; then
      err "lockfile registry rewrite FAILED (still npmjs): $lock"
      failed=$((failed+1))
    else
      ok=$((ok+1))
    fi
  done
  if [ -f "$target_dir/bun.lockb" ]; then
    err "bun.lockb (binary) found — registry rewrite does not apply to it"
  fi
  log "lockfile registry rewritten to ${reg_host} (ok=${ok} failed=${failed})"
  set -e
  return 0
}

run_dev_script() {
  local target_dir="$1"
  local dev_script="$target_dir/.zscripts/dev.sh"
  local log_file="$target_dir/.zscripts/dev.log"
  local pid_file="$target_dir/.zscripts/dev.pid"

  if [ "$SKIP_DEV" = "true" ]; then
    log "SKIP_DEV=true, skip running dev.sh"
    return 0
  fi

  if [ ! -f "$dev_script" ]; then
    err "dev script not found: $dev_script"
    exit 1
  fi

  chmod +x "$dev_script"
  log "Starting fullstack dev script in background: $dev_script"

  export DATABASE_URL="${DATABASE_URL:-file:${target_dir}/db/custom.db}"

  (
    cd "$target_dir"
    nohup bash "$dev_script" >>"$log_file" 2>&1 </dev/null &
    echo "$!" >"$pid_file"
  )

  log "dev.sh started in background"
  log "PID file: $pid_file"
  log "Log file: $log_file"
}

main() {
  local existing_package_json="$PROJECT_DIR/package.json"
  local existing_dev_script="$PROJECT_DIR/.zscripts/dev.sh"

  if [ -f "$existing_dev_script" ]; then
    log "Skipping code download and extraction, starting existing dev.sh"
    run_dev_script "$PROJECT_DIR"
    log "Initialization completed successfully"
    return 0
  fi

  if [ -f "$existing_package_json" ]; then
    log "Found existing package.json, skipping initialization"
    return 0
  fi

  require_cmd curl
  require_cmd tar

  TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/init-fullstack.XXXXXX")"
  local tar_path="$TMP_ROOT/package.tar"
  local unpack_path="$TMP_ROOT/unpacked"

  log "Initializing fullstack project"
  log "Target directory: $PROJECT_DIR"
  log "Package source (primary): $CODE_TAR_URL"
  log "Package source (fallback): $CODE_TAR_FALLBACK_URL"

  prepare_target_dir "$PROJECT_DIR"
  download_tarball_with_fallback "$CODE_TAR_URL" "$CODE_TAR_FALLBACK_URL" "$tar_path"
  extract_project "$tar_path" "$PROJECT_DIR" "$unpack_path"
  run_dev_script "$PROJECT_DIR"

  log "Initialization completed successfully"
}

main
