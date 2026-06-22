#!/bin/bash

# =============================================================================
# 数据增量聚合同步脚本
# 用于 crontab 定时执行增量同步任务
# =============================================================================

# ==================== 配置部分 ====================
# API 地址
API_BASE_URL="http://127.0.0.1:8001"
SYNC_ENDPOINT="/api/sync/incremental"

# 触发者标识（便于日志追踪）
TRIGGER_BY="crontab_$(hostname)_$(date +%Y%m%d_%H%M%S)"

# 日志配置
LOG_DIR="/home/liyanqi/workspace/ruijie/ruijie-cdp/logs/sync"
LOG_FILE="${LOG_DIR}/incremental_sync_$(date +%Y%m%d).log"

# 锁文件（防止重复运行）
LOCK_DIR="/tmp"
LOCK_FILE="${LOCK_DIR}/incremental_sync.lock"

# 超时时间（秒）
TIMEOUT=300

# API 请求最大时间（秒）
MAX_TIME=280

# ==================== 初始化 ====================
# 创建日志目录
mkdir -p "${LOG_DIR}"

# 日志函数
log() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] [${level}] ${message}" | tee -a "${LOG_FILE}"
}

# ==================== 检查锁文件 ====================
check_lock() {
    if [ -f "${LOCK_FILE}" ]; then
        local lock_pid=$(cat "${LOCK_FILE}" 2>/dev/null)
        if [ -n "${lock_pid}" ] && kill -0 "${lock_pid}" 2>/dev/null; then
            log "WARN" "上一次同步任务仍在运行 (PID: ${lock_pid})，跳过本次执行"
            exit 0
        else
            log "WARN" "发现残留的锁文件，清理后继续"
            rm -f "${LOCK_FILE}"
        fi
    fi
}

# ==================== 创建锁文件 ====================
create_lock() {
    echo $$ > "${LOCK_FILE}"
    log "INFO" "创建锁文件: ${LOCK_FILE} (PID: $$)"
}

# ==================== 释放锁文件 ====================
release_lock() {
    if [ -f "${LOCK_FILE}" ]; then
        rm -f "${LOCK_FILE}"
        log "INFO" "释放锁文件: ${LOCK_FILE}"
    fi
}

# ==================== 检查服务状态 ====================
check_service() {
    log "INFO" "检查后端服务状态..."
    
    local response=$(curl -s -o /dev/null -w "%{http_code}" \
        --connect-timeout 10 \
        --max-time 15 \
        "${API_BASE_URL}/api/sync/status" 2>/dev/null)
    
    if [ "$?" -ne 0 ] || [ "${response}" != "200" ]; then
        log "ERROR" "后端服务不可用 (HTTP: ${response})，请检查服务是否运行"
        return 1
    fi
    
    log "INFO" "后端服务正常"
    return 0
}

# ==================== 执行增量同步 ====================
run_sync() {
    log "INFO" "开始执行增量同步 (trigger_by: ${TRIGGER_BY})"
    log "INFO" "API: ${API_BASE_URL}${SYNC_ENDPOINT}?trigger_by=${TRIGGER_BY}"
    
    local start_time=$(date +%s)
    
    # 调用 API
    local response=$(curl -s -w "\n%{http_code}" \
        -X POST \
        --connect-timeout 30 \
        --max-time ${MAX_TIME} \
        "${API_BASE_URL}${SYNC_ENDPOINT}?trigger_by=${TRIGGER_BY}" 2>&1)
    
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    
    # 分离响应体和状态码
    local http_code=$(echo "${response}" | tail -n1)
    local response_body=$(echo "${response}" | sed '$d')
    
    log "INFO" "API 响应 (耗时: ${elapsed}s, HTTP: ${http_code})"
    log "INFO" "响应内容: ${response_body}"
    
    # 检查 HTTP 状态码
    if [ "${http_code}" != "200" ]; then
        log "ERROR" "同步请求失败 (HTTP: ${http_code})"
        return 1
    fi
    
    # 解析响应（检查是否成功）
    local status=$(echo "${response_body}" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    
    if [ "${status}" = "ok" ]; then
        local sync_id=$(echo "${response_body}" | grep -o '"sync_id":[0-9]*' | cut -d':' -f2)
        local message=$(echo "${response_body}" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)
        log "INFO" "同步成功 (sync_id: ${sync_id})"
        log "INFO" "消息: ${message}"
        return 0
    else
        log "ERROR" "同步失败: ${response_body}"
        return 1
    fi
}

# ==================== 验证同步结果 ====================
verify_sync() {
    log "INFO" "验证同步结果..."
    
    sleep 2  # 等待数据库写入
    
    local status_response=$(curl -s --max-time 10 "${API_BASE_URL}/api/sync/status" 2>/dev/null)
    
    if [ "$?" -ne 0 ]; then
        log "WARN" "无法获取同步状态，跳过验证"
        return 0
    fi
    
    local last_status=$(echo "${status_response}" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    local rows_synced=$(echo "${status_response}" | grep -o '"rows_synced":[0-9]*' | cut -d':' -f2)
    
    if [ "${last_status}" = "success" ]; then
        log "INFO" "验证通过: 最近一次同步状态为成功，同步行数: ${rows_synced:-未知}"
    else
        log "WARN" "验证警告: 最近一次同步状态为 ${last_status:-未知}"
    fi
}

# ==================== 清理旧日志 ====================
cleanup_logs() {
    log "INFO" "清理 30 天前的日志文件..."
    find "${LOG_DIR}" -name "incremental_sync_*.log" -mtime +30 -delete 2>/dev/null
}

# ==================== 主函数 ====================
main() {
    log "INFO" "=========================================="
    log "INFO" "增量同步任务开始"
    log "INFO" "=========================================="
    
    # 检查锁文件
    check_lock
    
    # 创建锁文件
    create_lock
    
    # 注册退出时释放锁文件
    trap release_lock EXIT
    
    # 检查服务状态
    if ! check_service; then
        log "ERROR" "服务检查失败，退出"
        exit 1
    fi
    
    # 执行同步
    if run_sync; then
        # 验证结果
        verify_sync
        log "INFO" "增量同步任务完成"
    else
        log "ERROR" "增量同步任务失败"
        exit 1
    fi
    
    # 清理旧日志
    cleanup_logs
    
    log "INFO" "=========================================="
    log "INFO" "增量同步任务结束"
    log "INFO" "=========================================="
}

# ==================== 脚本入口 ====================
main "$@"
