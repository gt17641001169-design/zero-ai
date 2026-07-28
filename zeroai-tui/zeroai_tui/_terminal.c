/**
 * zeroai-tui: Cross-platform terminal operations
 * 
 * Provides:
 * - Terminal size detection
 * - Raw mode toggle
 * - ANSI escape sequence output
 * - Cursor movement
 * - Color support detection
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>
#include <string.h>

// Platform-specific includes
#ifdef _WIN32
    #include <windows.h>
    #include <conio.h>
#else
    #include <unistd.h>
    #include <termios.h>
    #include <sys/ioctl.h>
    #include <signal.h>
#endif

// Global state
#ifdef _WIN32
    // Windows doesn't have termios
    static DWORD original_mode = 0;
#else
    static struct termios original_termios;
#endif
static int raw_mode_enabled = 0;

/**
 * Get terminal size (columns, rows)
 */
static PyObject* terminal_get_size(PyObject* self, PyObject* args) {
    int cols = 80;
    int rows = 24;
    
#ifdef _WIN32
    CONSOLE_SCREEN_BUFFER_INFO csbi;
    if (GetConsoleScreenBufferInfo(GetStdHandle(STD_OUTPUT_HANDLE), &csbi)) {
        cols = csbi.srWindow.Right - csbi.srWindow.Left + 1;
        rows = csbi.srWindow.Bottom - csbi.srWindow.Top + 1;
    }
#else
    struct winsize ws;
    if (ioctl(STDOUT_FILENO, TIOCGWINSZ, &ws) == 0) {
        cols = ws.ws_col;
        rows = ws.ws_row;
    }
#endif
    
    return Py_BuildValue("(ii)", cols, rows);
}

/**
 * Enable/disable raw mode for keyboard input
 */
static PyObject* terminal_set_raw_mode(PyObject* self, PyObject* args) {
    int enable;
    
    if (!PyArg_ParseTuple(args, "i", &enable)) {
        return NULL;
    }
    
#ifdef _WIN32
    HANDLE hStdin = GetStdHandle(STD_INPUT_HANDLE);
    DWORD mode;
    GetConsoleMode(hStdin, &mode);
    
    if (enable) {
        mode &= ~ENABLE_LINE_INPUT;
        mode &= ~ENABLE_ECHO_INPUT;
        mode |= ENABLE_VIRTUAL_TERMINAL_INPUT;
    } else {
        mode |= ENABLE_LINE_INPUT;
        mode |= ENABLE_ECHO_INPUT;
    }
    
    SetConsoleMode(hStdin, mode);
    raw_mode_enabled = enable;
#else
    if (enable) {
        tcgetattr(STDIN_FILENO, &original_termios);
        struct termios raw = original_termios;
        raw.c_lflag &= ~(ECHO | ICANON | IEXTEN | ISIG);
        raw.c_iflag &= ~(IXON | ICRNL);
        raw.c_cc[VMIN] = 1;
        raw.c_cc[VTIME] = 0;
        tcsetattr(STDIN_FILENO, TCSAFLUSH, &raw);
        raw_mode_enabled = 1;
    } else {
        tcsetattr(STDIN_FILENO, TCSAFLUSH, &original_termios);
        raw_mode_enabled = 0;
    }
#endif
    
    Py_RETURN_NONE;
}

/**
 * Write raw string to terminal (bypassing Python's buffering)
 */
static PyObject* terminal_write(PyObject* self, PyObject* args) {
    const char* text;
    int length;
    
    if (!PyArg_ParseTuple(args, "s#", &text, &length)) {
        return NULL;
    }
    
#ifdef _WIN32
    HANDLE hStdout = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD written;
    WriteConsoleA(hStdout, text, length, &written, NULL);
#else
    write(STDOUT_FILENO, text, length);
#endif
    
    Py_RETURN_NONE;
}

/**
 * Read single character (non-blocking in raw mode)
 */
static PyObject* terminal_read_char(PyObject* self, PyObject* args) {
    char c;
    
#ifdef _WIN32
    if (_kbhit()) {
        c = _getch();
        return Py_BuildValue("s#", &c, 1);
    }
#else
    if (read(STDIN_FILENO, &c, 1) == 1) {
        return Py_BuildValue("s#", &c, 1);
    }
#endif
    
    Py_RETURN_NONE;
}

/**
 * Clear terminal screen
 */
static PyObject* terminal_clear(PyObject* self, PyObject* args) {
#ifdef _WIN32
    system("cls");
#else
    write(STDOUT_FILENO, "\033[2J\033[H", 7);
#endif
    Py_RETURN_NONE;
}

/**
 * Move cursor to position (row, col)
 */
static PyObject* terminal_move_cursor(PyObject* self, PyObject* args) {
    int row, col;
    
    if (!PyArg_ParseTuple(args, "ii", &row, &col)) {
        return NULL;
    }
    
    char buffer[32];
    snprintf(buffer, sizeof(buffer), "\033[%d;%dH", row + 1, col + 1);
    
#ifdef _WIN32
    HANDLE hStdout = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD written;
    WriteConsoleA(hStdout, buffer, strlen(buffer), &written, NULL);
#else
    write(STDOUT_FILENO, buffer, strlen(buffer));
#endif
    
    Py_RETURN_NONE;
}

/**
 * Hide/show cursor
 */
static PyObject* terminal_set_cursor_visible(PyObject* self, PyObject* args) {
    int visible;
    
    if (!PyArg_ParseTuple(args, "i", &visible)) {
        return NULL;
    }
    
    const char* seq = visible ? "\033[?25h" : "\033[?25l";
    
#ifdef _WIN32
    HANDLE hStdout = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD written;
    WriteConsoleA(hStdout, seq, strlen(seq), &written, NULL);
#else
    write(STDOUT_FILENO, seq, strlen(seq));
#endif
    
    Py_RETURN_NONE;
}

/**
 * Check if terminal supports ANSI colors
 */
static PyObject* terminal_supports_color(PyObject* self, PyObject* args) {
    int supports = 0;
    
#ifdef _WIN32
    // Windows 10+ supports ANSI
    HANDLE hStdout = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD mode;
    if (GetConsoleMode(hStdout, &mode)) {
        supports = (mode & ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0;
    }
#else
    // Assume Unix terminals support colors
    const char* term = getenv("TERM");
    if (term && strstr(term, "color")) {
        supports = 1;
    } else if (isatty(STDOUT_FILENO)) {
        supports = 1;
    }
#endif
    
    return Py_BuildValue("i", supports);
}

// Method definitions
static PyMethodDef terminal_methods[] = {
    {"get_size", terminal_get_size, METH_NOARGS, "Get terminal size (cols, rows)"},
    {"set_raw_mode", terminal_set_raw_mode, METH_VARARGS, "Enable/disable raw mode"},
    {"write", terminal_write, METH_VARARGS, "Write string to terminal"},
    {"read_char", terminal_read_char, METH_NOARGS, "Read single character"},
    {"clear", terminal_clear, METH_NOARGS, "Clear terminal screen"},
    {"move_cursor", terminal_move_cursor, METH_VARARGS, "Move cursor to position"},
    {"set_cursor_visible", terminal_set_cursor_visible, METH_VARARGS, "Show/hide cursor"},
    {"supports_color", terminal_supports_color, METH_NOARGS, "Check color support"},
    {NULL, NULL, 0, NULL}
};

// Module definition
static struct PyModuleDef terminal_module = {
    PyModuleDef_HEAD_INIT,
    "_terminal",
    "Cross-platform terminal operations for zeroai-tui",
    -1,
    terminal_methods
};

// Module initialization
PyMODINIT_FUNC PyInit__terminal(void) {
    return PyModule_Create(&terminal_module);
}
