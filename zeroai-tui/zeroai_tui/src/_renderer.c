/**
 * _renderer.c - ZeroAI TUI Rendering Core
 *
 * 作为 Python 的唯一 C 入口，内部按以下优先级分发：
 *   1. Zig 路径（zig_render.dll / libzig_render.so / libzig_render.dylib）
 *      - 动态加载，零编译期依赖
 *      - 把 Python list 扁平化为 C 数组后调用 zig_diff_buffers
 *      - 失败（库不存在/函数不存在/调用返回错误）则自动回退
 *   2. C 路径（本文件内的标量实现）
 *      - 直接操作 Python list 对象
 *      - 无外部依赖，保证可运行性
 *
 * StyleStruct ABI（8 字节，与 zig_render.zig 的 StyleStruct 完全一致）：
 *   offset 0: bold      (u8)
 *   offset 1: dim       (u8)
 *   offset 2: italic    (u8)
 *   offset 3: underline (u8)
 *   offset 4: fg_id     (i16)  -1=None, 0-15=16色表
 *   offset 6: bg_id     (i16)  -1=None, 0-15=16色表
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>
#include <stdlib.h>

/* ===========================================================================
 * 平台相关动态加载头文件
 * =========================================================================== */
#ifdef _WIN32
    #include <windows.h>
    typedef HMODULE dynlib_handle_t;
    #define DYNLIB_LOAD(path)        LoadLibraryA(path)
    #define DYNLIB_GET_SYM(h, name) GetProcAddress(h, name)
    #define DYNLIB_CLOSE(h)         FreeLibrary(h)
    #define PATH_SEP                 '\\'
#else
    #include <dlfcn.h>
    typedef void* dynlib_handle_t;
    #define DYNLIB_LOAD(path)        dlopen(path, RTLD_LAZY)
    #define DYNLIB_GET_SYM(h, name)  dlsym(h, name)
    #define DYNLIB_CLOSE(h)          dlclose(h)
    #define PATH_SEP                 '/'
#endif

/* 前向声明 */
PyMODINIT_FUNC PyInit__renderer(void);

/* ===========================================================================
 * StyleStruct（必须与 zig_render.zig 的 StyleStruct 完全一致，8 字节）
 * =========================================================================== */
typedef struct {
    unsigned char  bold;
    unsigned char  dim;
    unsigned char  italic;
    unsigned char  underline;
    short          fg_id;   /* i16 */
    short          bg_id;   /* i16 */
} StyleStruct;

/* 编译期断言：保证 ABI 稳定 */
typedef char static_assert_style_struct_size[(sizeof(StyleStruct) == 8) ? 1 : -1];

/* ===========================================================================
 * zig_diff_buffers 函数指针类型
 *
 * c_int zig_diff_buffers(
 *     [*]const u8, [*]const StyleStruct,
 *     [*]const u8, [*]const StyleStruct,
 *     usize, usize,
 *     [*]u8, usize, *usize
 * )
 * =========================================================================== */
typedef int (*zig_diff_buffers_fn_t)(
    const unsigned char* current_chars,
    const StyleStruct*   current_styles,
    const unsigned char* next_chars,
    const StyleStruct*   next_styles,
    size_t rows, size_t cols,
    unsigned char* output, size_t output_capacity,
    size_t* output_len
);

/* ===========================================================================
 * Zig 库全局状态（懒加载，线程不安全——TUI 单线程渲染足够）
 * =========================================================================== */
static dynlib_handle_t g_zig_lib = 0;
static zig_diff_buffers_fn_t g_zig_diff_buffers = NULL;
static int g_zig_load_attempted = 0;  /* 是否已尝试加载过 */

/* 颜色字符串 -> ID 映射表
 * 与 terminal.py 的 Color 类保持一致
 * 返回 -1 表示无法识别 */
static int color_str_to_id(const char* s) {
    if (!s || !s[0]) return -1;
    /* 前景色 \033[30m .. \033[37m -> 0..7 */
    if (s[0] == 0x1b && s[1] == '[') {
        /* 解析 \033[NNm 形式 */
        int num = 0;
        int i = 2;
        int has_digit = 0;
        while (s[i] >= '0' && s[i] <= '9') {
            num = num * 10 + (s[i] - '0');
            i++;
            has_digit = 1;
        }
        if (has_digit && s[i] == 'm') {
            if (num >= 30 && num <= 37) return num - 30;       /* 基本前景色 */
            if (num >= 90 && num <= 97) return num - 90 + 8;   /* 亮色前景色 */
            if (num >= 40 && num <= 47) return num - 40;       /* 基本背景色（与前景同 ID 空间） */
            if (num >= 100 && num <= 107) return num - 100 + 8;/* 亮色背景色 */
        }
    }
    return -1;
}

/* 获取当前扩展模块所在目录
 * 用于优先从包内加载 zig_render.dll */
static int get_module_dir(char* out, size_t out_size) {
#ifdef _WIN32
    HMODULE hModule = NULL;
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
                           (LPCSTR)PyInit__renderer,
                           &hModule)) {
        DWORD len = GetModuleFileNameA(hModule, out, (DWORD)out_size);
        if (len > 0 && len < out_size) {
            /* 去掉文件名，保留目录 */
            for (int i = (int)len - 1; i >= 0; i--) {
                if (out[i] == '\\' || out[i] == '/') {
                    out[i] = '\0';
                    return 0;
                }
            }
        }
    }
#else
    Dl_info info;
    if (dladdr((void*)PyInit__renderer, &info) && info.dli_fname) {
        size_t len = strlen(info.dli_fname);
        if (len > 0 && len < out_size) {
            strcpy(out, info.dli_fname);
            for (int i = (int)len - 1; i >= 0; i--) {
                if (out[i] == '/') {
                    out[i] = '\0';
                    return 0;
                }
            }
        }
    }
#endif
    return -1;
}

/* 尝试加载 Zig 共享库
 * 搜索顺序：
 *   1. 扩展模块所在目录（zeroai_tui/）
 *   2. 当前工作目录
 *   3. 系统库路径（LoadLibrary/dlopen 默认行为） */
static void try_load_zig(void) {
    if (g_zig_load_attempted) return;
    g_zig_load_attempted = 1;

    char module_dir[1024] = {0};
    int has_module_dir = (get_module_dir(module_dir, sizeof(module_dir)) == 0);

    /* 候选路径列表 */
#ifdef _WIN32
    const char* lib_names[] = {
        "zig_render.dll",
        "libzig_render.dll",
        NULL
    };
#else
    const char* lib_names[] = {
        "libzig_render.so",
        "zig_render.so",
        "libzig_render.dylib",
        "zig_render.dylib",
        NULL
    };
#endif

    /* 先尝试模块所在目录 */
    if (has_module_dir) {
        for (int i = 0; lib_names[i] != NULL; i++) {
            char full_path[1100];
            snprintf(full_path, sizeof(full_path), "%s%c%s",
                     module_dir, PATH_SEP, lib_names[i]);
            g_zig_lib = DYNLIB_LOAD(full_path);
            if (g_zig_lib) {
                g_zig_diff_buffers = (zig_diff_buffers_fn_t)DYNLIB_GET_SYM(g_zig_lib, "zig_diff_buffers");
                if (g_zig_diff_buffers) {
                    /* 加载成功 */
                    return;
                }
                DYNLIB_CLOSE(g_zig_lib);
                g_zig_lib = 0;
            }
        }
    }

    /* 再尝试每个候选名（默认搜索路径） */
    for (int i = 0; lib_names[i] != NULL; i++) {
        g_zig_lib = DYNLIB_LOAD(lib_names[i]);
        if (g_zig_lib) {
            g_zig_diff_buffers = (zig_diff_buffers_fn_t)DYNLIB_GET_SYM(g_zig_lib, "zig_diff_buffers");
            if (g_zig_diff_buffers) {
                /* 加载成功 */
                return;
            }
            /* 库存在但符号未找到，关闭后继续尝试 */
            DYNLIB_CLOSE(g_zig_lib);
            g_zig_lib = 0;
        }
    }
}

/* 从 Python Style 对象提取 StyleStruct
 * 兼容 zeroai_tui.renderer.Style 和鸭子类型 */
static void style_to_struct(PyObject* style_obj, StyleStruct* out) {
    memset(out, 0, sizeof(StyleStruct));
    out->fg_id = -1;
    out->bg_id = -1;

    if (!style_obj || style_obj == Py_None) {
        return;
    }

    /* bold */
    PyObject* bold_attr = PyObject_GetAttrString(style_obj, "bold");
    if (bold_attr) {
        out->bold = PyObject_IsTrue(bold_attr) ? 1 : 0;
        Py_DECREF(bold_attr);
    }
    /* dim */
    PyObject* dim_attr = PyObject_GetAttrString(style_obj, "dim");
    if (dim_attr) {
        out->dim = PyObject_IsTrue(dim_attr) ? 1 : 0;
        Py_DECREF(dim_attr);
    }
    /* italic */
    PyObject* italic_attr = PyObject_GetAttrString(style_obj, "italic");
    if (italic_attr) {
        out->italic = PyObject_IsTrue(italic_attr) ? 1 : 0;
        Py_DECREF(italic_attr);
    }
    /* underline */
    PyObject* underline_attr = PyObject_GetAttrString(style_obj, "underline");
    if (underline_attr) {
        out->underline = PyObject_IsTrue(underline_attr) ? 1 : 0;
        Py_DECREF(underline_attr);
    }
    /* fg */
    PyObject* fg_attr = PyObject_GetAttrString(style_obj, "fg");
    if (fg_attr && fg_attr != Py_None) {
        const char* fg_str = PyUnicode_AsUTF8(fg_attr);
        if (fg_str) {
            out->fg_id = (short)color_str_to_id(fg_str);
        }
    }
    Py_XDECREF(fg_attr);
    /* bg */
    PyObject* bg_attr = PyObject_GetAttrString(style_obj, "bg");
    if (bg_attr && bg_attr != Py_None) {
        const char* bg_str = PyUnicode_AsUTF8(bg_attr);
        if (bg_str) {
            out->bg_id = (short)color_str_to_id(bg_str);
        }
    }
    Py_XDECREF(bg_attr);
}

/* 把 Python 二维字符列表扁平化为字节数组
 * 每个 cell 取首字符的 ASCII 码（< 256），非 ASCII 用空格替代 */
static int flatten_buffer(
    PyObject* list_2d,
    int rows, int cols,
    unsigned char* out_chars,
    StyleStruct* out_styles,
    int is_styles_list
) {
    for (int row = 0; row < rows; row++) {
        PyObject* row_list = PyList_GetItem(list_2d, row);
        if (!row_list) return -1;

        for (int col = 0; col < cols; col++) {
            int idx = row * cols + col;
            PyObject* cell = PyList_GetItem(row_list, col);
            if (!cell) return -1;

            if (is_styles_list) {
                /* styles list：cell 是 Style 对象或 None */
                style_to_struct(cell, &out_styles[idx]);
            } else {
                /* chars list：cell 是单字符字符串 */
                if (PyUnicode_Check(cell)) {
                    Py_ssize_t len = 0;
                    const char* s = PyUnicode_AsUTF8AndSize(cell, &len);
                    if (s && len > 0) {
                        /* 取首字节（简化处理，只支持 ASCII） */
                        unsigned char ch = (unsigned char)s[0];
                        out_chars[idx] = (ch < 128) ? ch : ' ';
                    } else {
                        out_chars[idx] = ' ';
                    }
                } else {
                    out_chars[idx] = ' ';
                }
            }
        }
    }
    return 0;
}

/* ===========================================================================
 * Zig 路径：调用 zig_diff_buffers
 * 成功返回 PyObject*（ANSI 字符串），失败返回 NULL（调用方应回退到 C 路径）
 * 注意：不会设置 Python 异常，调用方需自行回退
 * =========================================================================== */
static PyObject* diff_buffers_via_zig(
    PyObject* current_list, PyObject* current_styles_list,
    PyObject* next_list, PyObject* next_styles_list,
    int rows, int cols
) {
    if (!g_zig_diff_buffers) return NULL;
    if (rows <= 0 || cols <= 0) return NULL;

    size_t total = (size_t)rows * (size_t)cols;

    /* 分配扁平化缓冲区 */
    unsigned char* curr_chars = (unsigned char*)PyMem_Malloc(total);
    unsigned char* next_chars = (unsigned char*)PyMem_Malloc(total);
    StyleStruct*   curr_styles = (StyleStruct*)PyMem_Malloc(total * sizeof(StyleStruct));
    StyleStruct*   next_styles = (StyleStruct*)PyMem_Malloc(total * sizeof(StyleStruct));

    if (!curr_chars || !next_chars || !curr_styles || !next_styles) {
        PyMem_Free(curr_chars);
        PyMem_Free(next_chars);
        PyMem_Free(curr_styles);
        PyMem_Free(next_styles);
        return NULL;
    }

    /* 扁平化输入缓冲区 */
    if (flatten_buffer(current_list, rows, cols, curr_chars, curr_styles, 0) != 0 ||
        flatten_buffer(next_list, rows, cols, next_chars, next_styles, 0) != 0 ||
        flatten_buffer(current_styles_list, rows, cols, curr_chars, curr_styles, 1) != 0 ||
        flatten_buffer(next_styles_list, rows, cols, next_chars, next_styles, 1) != 0) {
        PyMem_Free(curr_chars);
        PyMem_Free(next_chars);
        PyMem_Free(curr_styles);
        PyMem_Free(next_styles);
        return NULL;
    }

    /* 分配输出缓冲区
     * 最坏情况：每个 cell 都变化，每个 cell 最多输出：
     *   光标序列(14) + 样式序列(30) + 字符(1) = 45 字节
     * + 末尾重置(4) */
    size_t output_capacity = total * 48 + 16;
    unsigned char* output_buf = (unsigned char*)PyMem_Malloc(output_capacity);
    if (!output_buf) {
        PyMem_Free(curr_chars);
        PyMem_Free(next_chars);
        PyMem_Free(curr_styles);
        PyMem_Free(next_styles);
        return NULL;
    }

    size_t output_len = 0;
    int rc = g_zig_diff_buffers(
        curr_chars, curr_styles,
        next_chars, next_styles,
        (size_t)rows, (size_t)cols,
        output_buf, output_capacity,
        &output_len
    );

    PyObject* result = NULL;
    if (rc == 0) {
        /* 成功：构造 Python 字符串 */
        result = PyUnicode_DecodeUTF8((const char*)output_buf, output_len, "replace");
    }
    /* rc != 0 表示 Zig 调用失败，返回 NULL 让调用方回退 */

    PyMem_Free(curr_chars);
    PyMem_Free(next_chars);
    PyMem_Free(curr_styles);
    PyMem_Free(next_styles);
    PyMem_Free(output_buf);

    return result;
}

/* ===========================================================================
 * C 路径：标量实现（直接操作 Python list 对象）
 * 作为 Zig 不可用时的回退路径
 * =========================================================================== */
static PyObject* diff_buffers_via_c(
    PyObject* current_list, PyObject* current_styles_list,
    PyObject* next_list, PyObject* next_styles_list,
    int rows, int cols
) {
    PyObject *output = PyUnicode_FromString("");
    if (!output) return NULL;

    int changes = 0;

    for (int row = 0; row < rows; row++) {
        PyObject *current_row = PyList_GetItem(current_list, row);
        PyObject *current_style_row = PyList_GetItem(current_styles_list, row);
        PyObject *next_row = PyList_GetItem(next_list, row);
        PyObject *next_style_row = PyList_GetItem(next_styles_list, row);

        for (int col = 0; col < cols; col++) {
            PyObject *current_char = PyList_GetItem(current_row, col);
            PyObject *next_char = PyList_GetItem(next_row, col);
            PyObject *current_style = PyList_GetItem(current_style_row, col);
            PyObject *next_style = PyList_GetItem(next_style_row, col);

            /* Skip if unchanged */
            if (PyObject_RichCompareBool(current_char, next_char, Py_EQ) &&
                PyObject_RichCompareBool(current_style, next_style, Py_EQ)) {
                continue;
            }

            changes++;

            /* Move cursor */
            char cursor_buf[32];
            snprintf(cursor_buf, sizeof(cursor_buf), "\033[%d;%dH", row + 1, col + 1);

            PyObject *cursor_str = PyUnicode_FromString(cursor_buf);
            PyObject *temp = PyUnicode_Concat(output, cursor_str);
            Py_DECREF(output);
            Py_DECREF(cursor_str);
            output = temp;

            /* Apply style if changed */
            if (!PyObject_RichCompareBool(current_style, next_style, Py_EQ)) {
                if (next_style && next_style != Py_None) {
                    /* Call style.apply(char) */
                    PyObject *apply_method = PyObject_GetAttrString(next_style, "apply");
                    if (apply_method) {
                        PyObject *styled_char = PyObject_CallFunctionObjArgs(apply_method, next_char, NULL);
                        if (styled_char) {
                            temp = PyUnicode_Concat(output, styled_char);
                            Py_DECREF(output);
                            Py_DECREF(styled_char);
                            output = temp;
                        }
                        Py_DECREF(apply_method);
                    }
                } else {
                    /* Reset style */
                    PyObject *reset_str = PyUnicode_FromString("\033[0m");
                    temp = PyUnicode_Concat(output, reset_str);
                    Py_DECREF(output);
                    Py_DECREF(reset_str);
                    output = temp;
                }
            } else {
                /* Same style, just write the character */
                PyObject *char_str = PyObject_Str(next_char);
                if (char_str) {
                    temp = PyUnicode_Concat(output, char_str);
                    Py_DECREF(output);
                    Py_DECREF(char_str);
                    output = temp;
                }
            }
        }
    }

    /* Add final reset if there were changes */
    if (changes > 0) {
        PyObject *reset_str = PyUnicode_FromString("\033[0m");
        PyObject *temp = PyUnicode_Concat(output, reset_str);
        Py_DECREF(output);
        Py_DECREF(reset_str);
        output = temp;
    }

    return output;
}

/* ===========================================================================
 * 对外暴露的 diff_buffers 函数
 * 优先 Zig，失败回退 C
 * =========================================================================== */
static PyObject* renderer_diff_buffers(PyObject* self, PyObject* args) {
    PyObject *current_list, *current_styles_list;
    PyObject *next_list, *next_styles_list;
    int rows, cols;

    if (!PyArg_ParseTuple(args, "OOOOii",
                          &current_list, &current_styles_list,
                          &next_list, &next_styles_list,
                          &rows, &cols)) {
        return NULL;
    }

    /* 首次调用时尝试加载 Zig 库 */
    if (!g_zig_load_attempted) {
        try_load_zig();
    }

    /* 优先 Zig 路径 */
    if (g_zig_diff_buffers) {
        PyObject* result = diff_buffers_via_zig(
            current_list, current_styles_list,
            next_list, next_styles_list,
            rows, cols
        );
        if (result != NULL) {
            return result;
        }
        /* Zig 路径失败，回退到 C 路径
         * 注意：此处不清除 Python 异常（diff_buffers_via_zig 不设置异常），
         * 但为安全起见，在回退前清除任何潜在异常，避免污染 C 路径 */
        PyErr_Clear();
    }

    /* 回退到 C 路径 */
    return diff_buffers_via_c(
        current_list, current_styles_list,
        next_list, next_styles_list,
        rows, cols
    );
}

/* ===========================================================================
 * 查询 Zig 是否可用
 * =========================================================================== */
static PyObject* renderer_zig_available(PyObject* self, PyObject* args) {
    if (!g_zig_load_attempted) {
        try_load_zig();
    }
    if (g_zig_diff_buffers) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

/* ===========================================================================
 * 强制重新加载 Zig 库（用于开发期 zig build 后热加载）
 * =========================================================================== */
static PyObject* renderer_reload_zig(PyObject* self, PyObject* args) {
    /* 关闭旧库 */
    if (g_zig_lib) {
        DYNLIB_CLOSE(g_zig_lib);
        g_zig_lib = 0;
        g_zig_diff_buffers = NULL;
    }
    g_zig_load_attempted = 0;
    try_load_zig();

    if (g_zig_diff_buffers) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

/* ===========================================================================
 * 生成样式 ANSI 序列（保留原接口）
 * =========================================================================== */
static PyObject* renderer_make_style(PyObject* self, PyObject* args) {
    int bold, dim, italic, underline;
    const char *fg, *bg;

    if (!PyArg_ParseTuple(args, "iiiiss",
                          &bold, &dim, &italic, &underline, &fg, &bg)) {
        return NULL;
    }

    char buf[256];
    char *p = buf;

    /* Add attributes */
    if (bold) { strcpy(p, "\033[1m"); p += 4; }
    if (dim) { strcpy(p, "\033[2m"); p += 4; }
    if (italic) { strcpy(p, "\033[3m"); p += 4; }
    if (underline) { strcpy(p, "\033[4m"); p += 4; }

    /* Add foreground color */
    if (fg && fg[0]) {
        strcpy(p, fg);
        p += strlen(fg);
    }

    /* Add background color */
    if (bg && bg[0]) {
        strcpy(p, bg);
        p += strlen(bg);
    }

    *p = '\0';

    return PyUnicode_FromString(buf);
}

/* ===========================================================================
 * Module method definition
 * =========================================================================== */
static PyMethodDef RendererMethods[] = {
    {"diff_buffers", renderer_diff_buffers, METH_VARARGS,
     "Compare buffers and generate ANSI diff (Zig first, C fallback)"},
    {"make_style", renderer_make_style, METH_VARARGS,
     "Generate ANSI escape sequence for style"},
    {"zig_available", renderer_zig_available, METH_NOARGS,
     "Check if Zig renderer is available"},
    {"reload_zig", renderer_reload_zig, METH_NOARGS,
     "Force reload Zig library (for development)"},
    {NULL, NULL, 0, NULL}
};

/* ===========================================================================
 * Module definition
 * =========================================================================== */
static struct PyModuleDef renderer_module = {
    PyModuleDef_HEAD_INIT,
    "_renderer",
    "ZeroAI TUI Rendering Core (C extension with Zig acceleration)",
    -1,
    RendererMethods
};

/* ===========================================================================
 * Module initialization
 * =========================================================================== */
PyMODINIT_FUNC PyInit__renderer(void) {
    /* 模块加载时不立即加载 Zig 库，首次调用 diff_buffers 时才懒加载 */
    return PyModule_Create(&renderer_module);
}
