const std = @import("std");
const builtin = @import("builtin");

// ZeroAI TUI Zig 渲染层构建脚本
//
// 构建产物安装到 zeroai_tui/ 目录，便于 Python ctypes 直接加载：
//   - Windows: zeroai_tui/zig_render.dll
//   - macOS:   zeroai_tui/libzig_render.dylib
//   - Linux:   zeroai_tui/libzig_render.so
//
// 用法：
//   zig build            # 构建并安装到 zeroai_tui/
//   zig build test       # 运行单元测试
//   zig build -Doptimize=ReleaseFast  # 发布构建

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // 构建共享库
    const lib = b.addLibrary(.{
        .name = "zig_render",
        .linkage = .dynamic,
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/zig_render.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
        }),
    });

    // 安装到默认路径（zig-out/lib），同时复制到 zeroai_tui/ 目录
    b.installArtifact(lib);

    // 额外安装步骤：复制共享库到 zeroai_tui/ 目录
    // 这样 Python ctypes 加载时无需额外配置路径
    const copy_to_package = b.addInstallBinFile(
        lib.getEmittedBin(),
        // 安装到 zig-out/bin 下的相对路径，这里用 ../zeroai_tui/ 回到包目录
        // 注意：installBinFile 的路径是相对于 zig-out/bin 的
        "../zeroai_tui/" ++ libName(),
    );
    copy_to_package.step.dependOn(&lib.step);
    b.getInstallStep().dependOn(&copy_to_package.step);

    // 单元测试
    const test_mod = b.createModule(.{
        .root_source_file = b.path("src/zig_render.zig"),
        .target = target,
        .optimize = optimize,
    });

    const main_tests = b.addTest(.{
        .root_module = test_mod,
    });

    const run_main_tests = b.addRunArtifact(main_tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_main_tests.step);

    // 自检目标（构建后打印信息）
    const info_step = b.step("info", "Print build info");
    const info_action = b.addSystemCommand(&.{
        "echo",
        "ZeroAI Zig renderer built. Library installed to zeroai_tui/",
    });
    info_step.dependOn(&info_action.step);
}

// 根据目标平台返回共享库文件名（comptime 已知）
inline fn libName() []const u8 {
    return switch (builtin.os.tag) {
        .windows => "zig_render.dll",
        .macos => "libzig_render.dylib",
        else => "libzig_render.so",
    };
}
