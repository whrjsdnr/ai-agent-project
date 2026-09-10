"""Windows directory handles preserve safe export's no-reparse-point guarantee."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def protected_directory_chain(directory: Path) -> Iterator[None]:
    # Imported only on Windows. Denying write/delete sharing prevents replacing
    # or retargeting an ancestor while the export is published.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    info = kernel.GetFileInformationByHandleEx
    info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    info.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    handles = []
    try:
        for path in (*reversed(directory.parents), directory):
            handle = create(str(path), 0x80, 1, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise OSError("Cannot protect export directory")
            handles.append(handle)
            attributes = AttributeTagInfo()
            if not info(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
                raise OSError("Cannot inspect export directory")
            if attributes.attributes & 0x400 or not attributes.attributes & 0x10:
                raise OSError(
                    "Export ancestors must be directories without reparse points"
                )
        yield
    finally:
        for handle in reversed(handles):
            close(handle)
