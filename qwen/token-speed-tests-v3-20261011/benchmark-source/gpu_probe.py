"""Read-only NVML memory telemetry; no dependency installs or driver changes."""
import ctypes as c

class Memory(c.Structure):
    _fields_ = [('total', c.c_ulonglong), ('free', c.c_ulonglong), ('used', c.c_ulonglong)]

class GPU:
    def __init__(self):
        self.dll = c.WinDLL('C:/Windows/System32/nvml.dll')
        self.dll.nvmlInit_v2.argtypes, self.dll.nvmlInit_v2.restype = [], c.c_int
        self.dll.nvmlShutdown.argtypes, self.dll.nvmlShutdown.restype = [], c.c_int
        self.dll.nvmlDeviceGetHandleByIndex_v2.argtypes = [c.c_uint, c.POINTER(c.c_void_p)]
        self.dll.nvmlDeviceGetHandleByIndex_v2.restype = c.c_int
        self.dll.nvmlDeviceGetMemoryInfo.argtypes = [c.c_void_p, c.POINTER(Memory)]
        self.dll.nvmlDeviceGetMemoryInfo.restype = c.c_int
        self.check(self.dll.nvmlInit_v2())
        self.handle = c.c_void_p()
        self.check(self.dll.nvmlDeviceGetHandleByIndex_v2(0, c.byref(self.handle)))

    @staticmethod
    def check(code):
        if code:
            raise RuntimeError(f'NVML query failed: {code}')

    def snapshot(self):
        value = Memory()
        self.check(self.dll.nvmlDeviceGetMemoryInfo(self.handle, c.byref(value)))
        return {name+'_mib': round(getattr(value, name)/1048576, 2) for name in ('total','free','used')}

    def close(self):
        self.check(self.dll.nvmlShutdown())

if __name__ == '__main__':
    import json
    gpu = GPU()
    try:
        print(json.dumps(gpu.snapshot()))
    finally:
        gpu.close()
