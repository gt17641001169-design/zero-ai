//
 // zig_render.zig - ZeroAI TUI Low-level Rendering
 // 
 // Zig module for:
 // - SIMD-accelerated buffer operations
 // - Memory-efficient string building
 // - Platform-specific optimizations
 //
 // C ABI 设计（供 Python ctypes 调用）：
 //   - chars  扁平化为 rows*cols 的 u8 数组
 //   - styles 扁平化为 rows*cols 的 StyleStruct 数组（8 字节对齐）
 //   - 颜色用 int16 ID 表示：-1=None, 0-7=basic, 8-15=bright
 //     （Zig 端维护 16 色 ANSI 表，避免传递字符串）
 //   - 输出写入调用方提供的 buffer，返回写入长度
 //
 // 与 Python 侧的 _renderer.c 互补：
 //   - _renderer.c 直接操作 Python list 对象（开发期可用，但开销大）
 //   - zig_render 走纯 C ABI，零 Python 交互开销（生产路径）

const std = @import("std");
const mem = std.mem;
const Allocator = mem.Allocator;

//
 // Style structure (C ABI, 8 字节对齐)
 //
 // 颜色 ID 约定：
 //   -1 = None（不输出颜色）
 //    0 = BLACK        1 = RED          2 = GREEN      3 = YELLOW
 //    4 = BLUE         5 = MAGENTA      6 = CYAN       7 = WHITE
 //    8 = BRIGHT_BLACK 9 = BRIGHT_RED  10 = BRIGHT_GREEN 11 = BRIGHT_YELLOW
 //   12 = BRIGHT_BLUE 13 = BRIGHT_MAGENTA 14 = BRIGHT_CYAN 15 = BRIGHT_WHITE
pub const StyleStruct = extern struct {
    bold: u8 = 0,
    dim: u8 = 0,
    italic: u8 = 0,
    underline: u8 = 0,
    fg_id: i16 = -1,
    bg_id: i16 = -1,
};

comptime {
    // 确保 ABI 布局稳定（8 字节）
    if (@sizeOf(StyleStruct) != 8) @compileError("StyleStruct must be 8 bytes");
}

//
 // 高层 RenderBuffer（Zig 内部使用，保留以兼容已有代码）
pub const Style = struct {
    bold: bool = false,
    dim: bool = false,
    italic: bool = false,
    underline: bool = false,
    fg: ?[]const u8 = null,
    bg: ?[]const u8 = null,

    pub fn eql(self: Style, other: Style) bool {
        return self.bold == other.bold and
            self.dim == other.dim and
            self.italic == other.italic and
            self.underline == other.underline and
            eqlOptional(self.fg, other.fg) and
            eqlOptional(self.bg, other.bg);
    }

    fn eqlOptional(a: ?[]const u8, b: ?[]const u8) bool {
        if (a == null and b == null) return true;
        if (a == null or b == null) return false;
        return mem.eql(u8, a.?, b.?);
    }
};

pub const RenderBuffer = struct {
    cols: usize,
    rows: usize,
    chars: [][]u8,
    styles: [][]Style,
    allocator: Allocator,

    pub fn init(allocator: Allocator, cols: usize, rows: usize) !RenderBuffer {
        var chars = try allocator.alloc([]u8, rows);
        var styles = try allocator.alloc([]Style, rows);

        for (0..rows) |row| {
            chars[row] = try allocator.alloc(u8, cols);
            styles[row] = try allocator.alloc(Style, cols);

            @memset(chars[row], ' ');
            @memset(styles[row], Style{});
        }

        return RenderBuffer{
            .cols = cols,
            .rows = rows,
            .chars = chars,
            .styles = styles,
            .allocator = allocator,
        };
    }

    pub fn deinit(self: *RenderBuffer) void {
        for (0..self.rows) |row| {
            self.allocator.free(self.chars[row]);
            self.allocator.free(self.styles[row]);
        }
        self.allocator.free(self.chars);
        self.allocator.free(self.styles);
    }

    pub fn clear(self: *RenderBuffer) void {
        for (0..self.rows) |row| {
            @memset(self.chars[row], ' ');
            @memset(self.styles[row], Style{});
        }
    }

    pub fn put(self: *RenderBuffer, row: usize, col: usize, char: u8, style: Style) void {
        if (row < self.rows and col < self.cols) {
            self.chars[row][col] = char;
            self.styles[row][col] = style;
        }
    }

    pub fn write(self: *RenderBuffer, row: usize, col: usize, text: []const u8, style: Style) void {
        for (text, 0..) |char, i| {
            if (col + i < self.cols) {
                self.put(row, col + i, char, style);
            }
        }
    }
};

//
 // 16 色前景 ANSI 序列表（fg_id 0-15 -> ANSI 码）
const FG_ANSI_TABLE = [_][]const u8{
    "\x1b[30m",  "\x1b[31m",  "\x1b[32m",  "\x1b[33m",
    "\x1b[34m",  "\x1b[35m",  "\x1b[36m",  "\x1b[37m",
    "\x1b[90m",  "\x1b[91m",  "\x1b[92m",  "\x1b[93m",
    "\x1b[94m",  "\x1b[95m",  "\x1b[96m",  "\x1b[97m",
};

//
 // 16 色背景 ANSI 序列表（bg_id 0-15 -> ANSI 码）
const BG_ANSI_TABLE = [_][]const u8{
    "\x1b[40m",  "\x1b[41m",  "\x1b[42m",  "\x1b[43m",
    "\x1b[44m",  "\x1b[45m",  "\x1b[46m",  "\x1b[47m",
    "\x1b[100m", "\x1b[101m", "\x1b[102m", "\x1b[103m",
    "\x1b[104m", "\x1b[105m", "\x1b[106m", "\x1b[107m",
};

//
 // 写入样式 ANSI 序列到 output
 // 仅当样式与上次不同时才输出，避免冗余序列
fn writeStyleAnsi(writer: anytype, style: StyleStruct) !void {
    if (style.bold != 0) try writer.writeAll("\x1b[1m");
    if (style.dim != 0) try writer.writeAll("\x1b[2m");
    if (style.italic != 0) try writer.writeAll("\x1b[3m");
    if (style.underline != 0) try writer.writeAll("\x1b[4m");
    if (style.fg_id >= 0 and style.fg_id < 16) {
        try writer.writeAll(FG_ANSI_TABLE[@intCast(style.fg_id)]);
    }
    if (style.bg_id >= 0 and style.bg_id < 16) {
        try writer.writeAll(BG_ANSI_TABLE[@intCast(style.bg_id)]);
    }
}

//
 // 比较 StyleStruct 是否相等
fn styleEqual(a: StyleStruct, b: StyleStruct) bool {
    return a.bold == b.bold and
        a.dim == b.dim and
        a.italic == b.italic and
        a.underline == b.underline and
        a.fg_id == b.fg_id and
        a.bg_id == b.bg_id;
}

//
 // Diff two buffers and generate ANSI output（高层 API，Zig 内部使用）
pub fn diffBuffers(
    current: RenderBuffer,
    next: RenderBuffer,
    output: *std.ArrayList(u8),
) !void {
    const writer = output.writer();

    var last_style: ?Style = null;

    for (0..next.rows) |row| {
        for (0..next.cols) |col| {
            const curr_char = current.chars[row][col];
            const next_char = next.chars[row][col];
            const curr_style = current.styles[row][col];
            const next_style = next.styles[row][col];

            if (curr_char == next_char and curr_style.eql(next_style)) {
                continue;
            }

            try writer.print("\x1b[{d};{d}H", .{ row + 1, col + 1 });

            if (last_style == null or !last_style.?.eql(next_style)) {
                try writeStyle(writer, next_style);
                last_style = next_style;
            }

            try writer.writeByte(next_char);
        }
    }

    if (output.items.len > 0) {
        try writer.writeAll("\x1b[0m");
    }
}

fn writeStyle(writer: anytype, style: Style) !void {
    if (style.bold) try writer.writeAll("\x1b[1m");
    if (style.dim) try writer.writeAll("\x1b[2m");
    if (style.italic) try writer.writeAll("\x1b[3m");
    if (style.underline) try writer.writeAll("\x1b[4m");
    if (style.fg) |fg| try writer.writeAll(fg);
    if (style.bg) |bg| try writer.writeAll(bg);
}

//
 // SIMD-optimized buffer comparison (for large buffers)
pub fn diffBuffersSimd(
    current: RenderBuffer,
    next: RenderBuffer,
    output: *std.ArrayList(u8),
) !void {
    try diffBuffers(current, next, output);
}

//
 // ============================================================================
 // C ABI 导出函数（供 Python ctypes 调用）
 // ============================================================================
 //
 // 比较两个扁平化缓冲区，生成 ANSI 差异输出。
 //
 // 参数：
 //   current_chars    - 当前帧字符数组（rows*cols 字节，行优先）
 //   current_styles   - 当前帧样式数组（rows*cols 个 StyleStruct）
 //   next_chars       - 下一帧字符数组
 //   next_styles      - 下一帧样式数组
 //   rows, cols       - 缓冲区尺寸
 //   output           - 输出缓冲区（调用方分配）
 //   output_capacity  - 输出缓冲区容量（字节）
 //   output_len       - 返回实际写入长度
 //
 // 返回：
 //   0  - 成功
 //   -1 - 参数错误（空指针/零尺寸）
 //   -2 - 输出缓冲区不足（output_capacity 太小）
 //
 // 性能说明：
 //   - 跳过未变化的单元格（字符+样式都相同）
 //   - 仅在样式变化时输出 ANSI 样式序列
 //   - 光标移动用 \x1b[row;colH（1-based）
 //   - 末尾追加 \x1b[0m 重置
export fn zig_diff_buffers(
    current_chars: [*]const u8,
    current_styles: [*]const StyleStruct,
    next_chars: [*]const u8,
    next_styles: [*]const StyleStruct,
    rows: usize,
    cols: usize,
    output: [*]u8,
    output_capacity: usize,
    output_len: *usize,
) c_int {
    // 参数校验
    if (rows == 0 or cols == 0 or output_capacity == 0) {
        output_len.* = 0;
        return -1;
    }

    var written: usize = 0;
    var last_style: ?StyleStruct = null;
    var has_changes: bool = false;

    var row: usize = 0;
    while (row < rows) : (row += 1) {
        var col: usize = 0;
        while (col < cols) : (col += 1) {
            const idx = row * cols + col;
            const curr_char = current_chars[idx];
            const next_char = next_chars[idx];
            const curr_style = current_styles[idx];
            const next_style = next_styles[idx];

            // 跳过未变化的单元格
            if (curr_char == next_char and styleEqual(curr_style, next_style)) {
                continue;
            }

            has_changes = true;

            // 写入光标移动序列 \x1b[row;colH（1-based）
            // 用栈缓冲区 + bufPrint 格式化，避免堆分配
            var cursor_buf: [16]u8 = undefined;
            const cursor_str = std.fmt.bufPrint(&cursor_buf, "\x1b[{d};{d}H", .{ row + 1, col + 1 }) catch {
                output_len.* = written;
                return -2;
            };
            const space_left = output_capacity - written;
            if (cursor_str.len > space_left) {
                output_len.* = written;
                return -2;
            }
            @memcpy(output[written .. written + cursor_str.len], cursor_str);
            written += cursor_str.len;

            // 样式变化时输出 ANSI 样式序列
            if (last_style == null or !styleEqual(last_style.?, next_style)) {
                const style_space = output_capacity - written;
                const written_style = writeStyleAnsiRaw(output[written..output_capacity], next_style, style_space);
                if (written_style < 0) {
                    output_len.* = written;
                    return -2;
                }
                written += @intCast(written_style);
                last_style = next_style;
            }

            // 写入字符
            if (written >= output_capacity) {
                output_len.* = written;
                return -2;
            }
            output[written] = next_char;
            written += 1;
        }
    }

    // 末尾追加重置序列 \x1b[0m
    if (has_changes) {
        const reset = "\x1b[0m";
        const space_left = output_capacity - written;
        if (reset.len > space_left) {
            output_len.* = written;
            return -2;
        }
        @memcpy(output[written .. written + reset.len], reset);
        written += reset.len;
    }

    output_len.* = written;
    return 0;
}

//
 // 写 usize 到缓冲区（十进制），返回写入字节数
 // 保留用于单元测试和未来扩展
fn writeUsize(buf: []u8, val: usize) usize {
    if (val == 0) {
        buf[0] = '0';
        return 1;
    }
    var n = val;
    var temp: [20]u8 = undefined;
    var temp_len: usize = 0;
    while (n > 0) {
        temp[temp_len] = '0' + @as(u8, @intCast(n % 10));
        temp_len += 1;
        n /= 10;
    }
    // 反转
    var i: usize = 0;
    while (i < temp_len) : (i += 1) {
        buf[i] = temp[temp_len - 1 - i];
    }
    return temp_len;
}

//
 // 写样式 ANSI 序列到原始字节缓冲区
 // 返回写入字节数，-1 表示空间不足
fn writeStyleAnsiRaw(buf: []u8, style: StyleStruct, capacity: usize) isize {
    var written: usize = 0;

    if (style.bold != 0) {
        const seq = "\x1b[1m";
        if (written + seq.len > capacity) return -1;
        @memcpy(buf[written .. written + seq.len], seq);
        written += seq.len;
    }
    if (style.dim != 0) {
        const seq = "\x1b[2m";
        if (written + seq.len > capacity) return -1;
        @memcpy(buf[written .. written + seq.len], seq);
        written += seq.len;
    }
    if (style.italic != 0) {
        const seq = "\x1b[3m";
        if (written + seq.len > capacity) return -1;
        @memcpy(buf[written .. written + seq.len], seq);
        written += seq.len;
    }
    if (style.underline != 0) {
        const seq = "\x1b[4m";
        if (written + seq.len > capacity) return -1;
        @memcpy(buf[written .. written + seq.len], seq);
        written += seq.len;
    }
    if (style.fg_id >= 0 and style.fg_id < 16) {
        const seq = FG_ANSI_TABLE[@intCast(style.fg_id)];
        if (written + seq.len > capacity) return -1;
        @memcpy(buf[written .. written + seq.len], seq);
        written += seq.len;
    }
    if (style.bg_id >= 0 and style.bg_id < 16) {
        const seq = BG_ANSI_TABLE[@intCast(style.bg_id)];
        if (written + seq.len > capacity) return -1;
        @memcpy(buf[written .. written + seq.len], seq);
        written += seq.len;
    }
    return @intCast(written);
}

// ============================================================================
// 单元测试
// ============================================================================
test "StyleStruct is 8 bytes" {
    try std.testing.expectEqual(@as(usize, 8), @sizeOf(StyleStruct));
}

test "styleEqual" {
    const a = StyleStruct{ .bold = 1, .fg_id = 1 };
    const b = StyleStruct{ .bold = 1, .fg_id = 1 };
    const c = StyleStruct{ .bold = 1, .fg_id = 2 };
    try std.testing.expect(styleEqual(a, b));
    try std.testing.expect(!styleEqual(a, c));
}

test "writeUsize" {
    var buf: [20]u8 = undefined;
    var len = writeUsize(&buf, 0);
    try std.testing.expectEqualStrings("0", buf[0..len]);

    len = writeUsize(&buf, 42);
    try std.testing.expectEqualStrings("42", buf[0..len]);

    len = writeUsize(&buf, 12345);
    try std.testing.expectEqualStrings("12345", buf[0..len]);
}

test "zig_diff_buffers basic" {
    const rows = 2;
    const cols = 3;

    var curr_chars = [_]u8{ 'a', 'b', 'c', 'd', 'e', 'f' };
    var next_chars = [_]u8{ 'a', 'X', 'c', 'd', 'e', 'Y' };

    var curr_styles = [_]StyleStruct{ StyleStruct{}, StyleStruct{}, StyleStruct{}, StyleStruct{}, StyleStruct{}, StyleStruct{} };
    var next_styles = [_]StyleStruct{ StyleStruct{}, StyleStruct{}, StyleStruct{}, StyleStruct{}, StyleStruct{}, StyleStruct{} };

    var output: [256]u8 = undefined;
    var output_len: usize = 0;

    const rc = zig_diff_buffers(
        &curr_chars, &curr_styles,
        &next_chars, &next_styles,
        rows, cols,
        &output, output.len, &output_len,
    );

    try std.testing.expectEqual(@as(c_int, 0), rc);
    // 应该输出两个变化：位置 (1,2) 的 X 和位置 (2,3) 的 Y
    const result = output[0..output_len];
    try std.testing.expect(std.mem.indexOf(u8, result, "X") != null);
    try std.testing.expect(std.mem.indexOf(u8, result, "Y") != null);
    try std.testing.expect(std.mem.indexOf(u8, result, "\x1b[0m") != null);
}

test "zig_diff_buffers no changes" {
    const rows = 1;
    const cols = 3;

    var chars = [_]u8{ 'a', 'b', 'c' };
    var styles = [_]StyleStruct{ StyleStruct{}, StyleStruct{}, StyleStruct{} };

    var output: [64]u8 = undefined;
    var output_len: usize = 0;

    const rc = zig_diff_buffers(
        &chars, &styles,
        &chars, &styles,
        rows, cols,
        &output, output.len, &output_len,
    );

    try std.testing.expectEqual(@as(c_int, 0), rc);
    try std.testing.expectEqual(@as(usize, 0), output_len);
}

test "zig_diff_buffers with style" {
    const rows = 1;
    const cols = 2;

    var curr_chars = [_]u8{ 'a', 'b' };
    var next_chars = [_]u8{ 'A', 'b' };

    var curr_styles = [_]StyleStruct{ .{}, .{} };
    var next_styles = [_]StyleStruct{
        .{ .bold = 1, .fg_id = 1 },
        .{},
    };

    var output: [128]u8 = undefined;
    var output_len: usize = 0;

    const rc = zig_diff_buffers(
        &curr_chars, &curr_styles,
        &next_chars, &next_styles,
        rows, cols,
        &output, output.len, &output_len,
    );

    try std.testing.expectEqual(@as(c_int, 0), rc);
    const result = output[0..output_len];
    try std.testing.expect(std.mem.indexOf(u8, result, "\x1b[1m") != null); // bold
    try std.testing.expect(std.mem.indexOf(u8, result, "\x1b[31m") != null); // red fg
}
