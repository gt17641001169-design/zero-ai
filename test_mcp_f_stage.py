"""F 阶段 MCP 生态系统测试"""
import sys
import os
import asyncio
sys.path.insert(0, r"d:\C\C")

from zeroai.mcp import (
    get_health_monitor,
    get_audit_logger,
    get_ecosystem_manager,
    MCPHealthMonitor,
    MCPAuditLogger,
    MCPEcosystemManager,
    HealthRecord,
    ReconnectPolicy,
    AuditRecord,
    ToolConflict,
    EcosystemStatus,
)


def test_health_monitor():
    """F.3: 健康监控器创建和配置"""
    print("[F.3.1] Health monitor creation...")
    monitor = get_health_monitor()
    assert isinstance(monitor, MCPHealthMonitor)
    assert isinstance(monitor.policy, ReconnectPolicy)
    assert monitor.policy.max_attempts == 5
    assert monitor.policy.initial_delay == 1.0
    assert monitor.policy.backoff_factor == 2.0

    # 测试退避延迟计算
    assert monitor.policy.get_delay(0) == 1.0
    assert monitor.policy.get_delay(1) == 2.0
    assert monitor.policy.get_delay(2) == 4.0
    assert monitor.policy.get_delay(3) == 8.0
    assert monitor.policy.get_delay(10) == 60.0  # 上限
    print("  [OK] Health monitor with exponential backoff")
    return True


def test_health_record():
    """F.3: 健康记录数据结构"""
    print("[F.3.2] Health record structure...")
    record = HealthRecord(server_name="test_server")
    assert record.server_name == "test_server"
    assert record.is_healthy is False
    assert record.failure_count == 0
    assert record.success_count == 0
    assert record.is_degraded is False

    # 测试 to_dict
    d = record.to_dict()
    assert d["server_name"] == "test_server"
    assert d["is_healthy"] is False
    assert "history" in d
    print("  [OK] Health record serialization")
    return True


def test_audit_logger():
    """F.4: 审计日志器创建和记录"""
    print("[F.4.1] Audit logger creation...")
    logger = get_audit_logger()
    assert isinstance(logger, MCPAuditLogger)
    assert logger.buffer_size == 0

    # 测试记录
    record = logger.record(
        server_name="filesystem",
        tool_name="read_file",
        full_tool_name="mcp__filesystem__read_file",
        arguments={"path": "/tmp/test.txt", "api_key": "sk-1234567890abcdef"},
        success=True,
        duration=0.123,
        result_length=100,
        result_preview="file content here",
    )
    assert isinstance(record, AuditRecord)
    assert record.server_name == "filesystem"
    assert record.success is True
    assert record.duration == 0.123
    print("  [OK] Audit record created")
    return True


def test_audit_sanitization():
    """F.4: 敏感数据脱敏"""
    print("[F.4.2] Sensitive data sanitization...")
    from zeroai.mcp.audit import _sanitize_arguments, _sanitize_result

    # 测试参数脱敏
    args = {
        "path": "/tmp/test.txt",
        "api_key": "sk-1234567890abcdef",
        "password": "my_secret_password",
        "token": "Bearer abc123xyz",
        "normal_field": "normal_value",
    }
    sanitized = _sanitize_arguments(args)
    assert sanitized["path"] == "/tmp/test.txt"  # 普通字段不脱敏
    assert sanitized["api_key"] != "sk-1234567890abcdef"  # api_key 脱敏
    assert "***" in sanitized["api_key"]
    assert sanitized["password"] != "my_secret_password"  # password 脱敏
    assert sanitized["normal_field"] == "normal_value"

    # 测试结果脱敏
    result = "Token: Bearer abc123xyz789"
    sanitized_result = _sanitize_result(result)
    assert "abc123xyz789" not in sanitized_result
    print("  [OK] Sensitive data sanitized")
    return True


def test_audit_query():
    """F.4: 审计记录查询"""
    print("[F.4.3] Audit record query...")
    logger = get_audit_logger()
    logger.clear_memory()  # 清空之前的记录，确保测试隔离

    # 添加多条记录
    for i in range(5):
        logger.record(
            server_name="filesystem" if i < 3 else "git",
            tool_name="read_file" if i < 3 else "git_status",
            full_tool_name=f"mcp__{'filesystem' if i < 3 else 'git'}__{'read_file' if i < 3 else 'git_status'}",
            arguments={"path": f"/tmp/{i}.txt"},
            success=i != 2,  # 第 3 条失败
            duration=0.1 * i,
        )

    # 查询所有
    all_records = logger.query_records(limit=100)
    assert len(all_records) == 5

    # 按服务器查询
    fs_records = logger.query_records(server_name="filesystem")
    assert len(fs_records) == 3

    # 按成功状态查询
    failed = logger.query_records(success=False)
    assert len(failed) == 1

    # 统计
    stats = logger.get_statistics(hours=1)
    assert stats["total_calls"] == 5
    assert stats["success_count"] == 4
    assert stats["fail_count"] == 1
    assert "filesystem" in stats["by_server"]
    print(f"  [OK] Query: {len(all_records)} records, stats: {stats['total_calls']} calls")
    return True


def test_ecosystem_presets():
    """F.1: 预设管理"""
    print("[F.1.1] Ecosystem preset listing...")
    mgr = get_ecosystem_manager()
    presets = mgr.list_available_presets()
    assert len(presets) >= 8  # 8 个预设

    # 验证预设结构
    for p in presets:
        assert "name" in p
        assert "description" in p
        assert "deps_available" in p
        assert "is_installed" in p

    # 检查已知预设
    preset_names = [p["name"] for p in presets]
    assert "filesystem" in preset_names
    assert "git" in preset_names
    assert "sqlite" in preset_names
    print(f"  [OK] {len(presets)} presets available: {preset_names[:3]}...")
    return True


def test_conflict_detection():
    """F.2: 冲突检测"""
    print("[F.2.1] Conflict detection...")
    mgr = get_ecosystem_manager()
    conflicts = mgr.detect_conflicts()
    # 无 MCP 服务器连接时应该无冲突
    assert isinstance(conflicts, list)
    print(f"  [OK] Conflicts detected: {len(conflicts)}")
    return True


def test_status():
    """F.1/F.2: 状态报告"""
    print("[F.1.2] Ecosystem status...")
    mgr = get_ecosystem_manager()
    status = mgr.get_status()
    assert isinstance(status, EcosystemStatus)
    assert status.total_presets >= 8
    assert isinstance(status.builtin_tools, int)
    assert isinstance(status.details, dict)
    print(f"  [OK] Status: {status.total_presets} presets, {status.builtin_tools} builtin tools")
    return True


def main():
    print("=" * 60)
    print("ZeroAI MCP F-Stage Tests (F.1-F.4)")
    print("=" * 60)
    print()

    tests = [
        ("F.3 Health Monitor", test_health_monitor),
        ("F.3 Health Record", test_health_record),
        ("F.4 Audit Logger", test_audit_logger),
        ("F.4 Sanitization", test_audit_sanitization),
        ("F.4 Audit Query", test_audit_query),
        ("F.1 Presets", test_ecosystem_presets),
        ("F.2 Conflict Detection", test_conflict_detection),
        ("F.1 Status Report", test_status),
    ]

    passed = 0
    failed = 0
    for name, test in tests:
        print()
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
