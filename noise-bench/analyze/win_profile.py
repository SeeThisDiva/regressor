#!/usr/bin/env python3
"""
Windows-capable profiling and instruction-attribution path for differential flamegraphs.

On Windows hosts without Administrator elevation (`SeSystemProfilePrivilege`),
ETW-based profilers (`cargo-flamegraph` / `blondie` and `samply`) fail with
`Access is denied` when opening the kernel trace session. This module provides
two elevation-free profiling backends for PE32+/DWARF binaries (such as
`x86_64-pc-windows-gnu` Rust release builds with `debug = true`):

1. `sample`: Win32 user-mode stack sampler (`OpenProcess` + `OpenThread` +
   `SuspendThread` + `GetThreadContext` + `ReadProcessMemory`) that unwinds x64
   stacks offline using PE `.pdata`/`.xdata` exception tables and expands
   inlined Rust frames via `llvm-nm` + `llvm-objdump --debug-inlined-funcs=ascii`.
2. `insn`: Deterministic static instruction-count, stack-spill (`(%rsp)`), and
   inlined call-stack attribution using `llvm-tools`, emitting folded stacks
   and JSON instruction diffs without executing benchmarks.

Both backends emit Brendan Gregg folded stacks (`frame1;frame2 <count>`) that
feed directly into `noise-bench/analyze/flamegraph.py`.
"""

from __future__ import annotations

import argparse
import bisect
import ctypes
import ctypes.wintypes as wt
import json
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ANALYZE_DIR = Path(__file__).resolve().parent
if str(ANALYZE_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYZE_DIR))

import flamegraph  # noqa: E402

# Win32 constants for user-mode process/thread inspection (no Admin needed for owned child).
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
THREAD_SUSPEND_RESUME = 0x0002
THREAD_GET_CONTEXT = 0x0008
THREAD_QUERY_INFORMATION = 0x0040
TH32CS_SNAPTHREAD = 0x00000004
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
CONTEXT_AMD64_CONTROL_INT = 0x00100003  # CONTEXT_AMD64 | CONTEXT_CONTROL | CONTEXT_INTEGER
CONTEXT_SIZE = 1232

# x64 register numbers used in PE UNWIND_INFO opcodes -> byte offsets in CONTEXT.
_CTX_REG_OFFSETS = {
    0: 0x78,   # RAX
    1: 0x80,   # RCX
    2: 0x88,   # RDX
    3: 0x90,   # RBX
    4: 0x98,   # RSP
    5: 0xA0,   # RBP
    6: 0xA8,   # RSI
    7: 0xB0,   # RDI
    8: 0xB8,   # R8
    9: 0xC0,   # R9
    10: 0xC8,  # R10
    11: 0xD0,  # R11
    12: 0xD8,  # R12
    13: 0xE0,  # R13
    14: 0xE8,  # R14
    15: 0xF0,  # R15
}

_HEX_INSN_RE = re.compile(r"^([0-9a-f]+):\s+(?:[0-9a-f]{2}\s+)+")
_NM_LINE_RE = re.compile(r"^([0-9a-fA-F]+)\s+([tTrRdDbBwWiI])\s+(.+)$")
_HDR_MARKER_RE = re.compile(r"^((?:[|]\s+)*)[|/]-+\s+(.+?)\s*$")
_CALL_TARGET_RE = re.compile(r"\bcallq?\s+0x([0-9a-f]+)(?:\s+<([^>]+)>)?")
_RSP_MEM_RE = re.compile(r"\(%rsp\)")
_JCC_BRANCH_RE = re.compile(r"\bj[a-z]+\s+0x([0-9a-f]+)")

MAX_MODULE_CACHE_BYTES = 16 * 1024 * 1024


# ---------------------------------------------------------------------------
# Tool Discovery & Path Sanitization
# ---------------------------------------------------------------------------


def find_llvm_tool(tool_name: str) -> str:
    """Locate an LLVM binary (`llvm-nm`, `llvm-objdump`) from PATH or rustup sysroot."""
    exe_name = f"{tool_name}.exe" if platform.system() == "Windows" else tool_name
    found = shutil.which(tool_name) or shutil.which(exe_name)
    if found:
        return found

    rustc = shutil.which("rustc")
    if rustc:
        try:
            sysroot = subprocess.check_output([rustc, "--print", "sysroot"], text=True, timeout=10).strip()
            candidates = list(Path(sysroot).glob(f"lib/rustlib/*/bin/{exe_name}"))
            if candidates:
                return str(candidates[0])
        except (OSError, subprocess.SubprocessError):
            pass

    raise FileNotFoundError(
        f"'{exe_name}' not found on PATH or inside rustup sysroot. "
        "Install it with: rustup component add llvm-tools"
    )


def _clean_frame_name(name: str) -> str:
    """Normalize a Rust symbol or inline frame name for folded stack lines."""
    cleaned = name.strip()
    if " = inlined into " in cleaned:
        cleaned = cleaned.split(" = inlined into ", 1)[0].strip()
    elif cleaned.endswith(" ="):
        cleaned = cleaned[:-2].strip()
    # Folded stack traces use ';' as frame separator and space before count.
    cleaned = cleaned.replace(";", "::")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "unknown"


# ---------------------------------------------------------------------------
# PE32+ .pdata / .xdata Unwind Parser (Offline x64 Unwinding)
# ---------------------------------------------------------------------------


class PEUnwindTable:
    """Parses PE32+ `.pdata` (`RUNTIME_FUNCTION`) and `.xdata` (`UNWIND_INFO`) tables."""

    def __init__(self, image_bytes: bytes, *, mapped: bool = False) -> None:
        self.data = image_bytes
        self.mapped = mapped
        self.image_base = 0
        self.size_of_image = 0
        self.sections: List[Tuple[int, int, int, int]] = []  # (va, vsz, ra, rsz)
        self.begins: List[int] = []
        self.entries: List[Tuple[int, int, int]] = []
        self.export_addrs: List[int] = []
        self.export_names: List[str] = []
        self._parse_pe()

    def _rva_to_off(self, rva: int) -> Optional[int]:
        if self.mapped:
            return rva if 0 <= rva < len(self.data) else None
        for va, vsz, ra, rsz in self.sections:
            span = max(vsz, rsz)
            if va <= rva < va + span:
                off = ra + (rva - va)
                return off if off < len(self.data) else None
        return None

    def _read_cstr(self, off: int, limit: int = 256) -> str:
        end = self.data.find(b"\x00", off, min(len(self.data), off + limit))
        if end == -1:
            end = min(len(self.data), off + limit)
        return self.data[off:end].decode("ascii", errors="replace")

    def _parse_exports(self, exp_rva: int, exp_size: int) -> None:
        if exp_rva == 0 or exp_size < 40:
            return
        eoff = self._rva_to_off(exp_rva)
        if eoff is None or eoff + 40 > len(self.data):
            return
        num_funcs, num_names, addr_funcs_rva, addr_names_rva, addr_ords_rva = struct.unpack_from(
            "<IIIII", self.data, eoff + 20
        )
        funcs_off = self._rva_to_off(addr_funcs_rva)
        names_off = self._rva_to_off(addr_names_rva)
        ords_off = self._rva_to_off(addr_ords_rva)
        if funcs_off is None or names_off is None or ords_off is None:
            return
        pairs: Dict[int, str] = {}
        for i in range(min(num_names, 16384)):
            if names_off + i * 4 + 4 > len(self.data) or ords_off + i * 2 + 2 > len(self.data):
                break
            name_rva = struct.unpack_from("<I", self.data, names_off + i * 4)[0]
            ord_idx = struct.unpack_from("<H", self.data, ords_off + i * 2)[0]
            if ord_idx >= num_funcs or funcs_off + ord_idx * 4 + 4 > len(self.data):
                continue
            fn_rva = struct.unpack_from("<I", self.data, funcs_off + ord_idx * 4)[0]
            if exp_rva <= fn_rva < exp_rva + exp_size:
                continue  # Skip forwarder strings
            name_off = self._rva_to_off(name_rva)
            if name_off is not None:
                pairs.setdefault(fn_rva, self._read_cstr(name_off))
        ordered = sorted(pairs.items())
        self.export_addrs = [a for a, _ in ordered]
        self.export_names = [n for _, n in ordered]

    def resolve_export(self, rva: int) -> Optional[str]:
        """Return nearest preceding PE export name for `rva` (within 64 KB), if available."""
        if not self.export_addrs:
            return None
        idx = bisect.bisect_right(self.export_addrs, rva) - 1
        if idx >= 0 and (rva - self.export_addrs[idx]) < 65536:
            return self.export_names[idx]
        return None

    def _parse_pe(self) -> None:
        if len(self.data) < 0x100 or self.data[:2] != b"MZ":
            return
        pe_off = struct.unpack_from("<I", self.data, 0x3C)[0]
        if pe_off + 24 > len(self.data) or self.data[pe_off : pe_off + 4] != b"PE\x00\x00":
            return

        num_sections, = struct.unpack_from("<H", self.data, pe_off + 6)
        opt_size, = struct.unpack_from("<H", self.data, pe_off + 20)
        opt_off = pe_off + 24
        if opt_off + opt_size > len(self.data):
            return

        magic, = struct.unpack_from("<H", self.data, opt_off)
        if magic != 0x20B:  # PE32+ only
            return
        self.image_base, = struct.unpack_from("<Q", self.data, opt_off + 24)
        self.size_of_image, = struct.unpack_from("<I", self.data, opt_off + 56)
        num_rvas, = struct.unpack_from("<I", self.data, opt_off + 108)

        sec_off = opt_off + opt_size
        for i in range(num_sections):
            off = sec_off + i * 40
            if off + 40 > len(self.data):
                break
            vsz, va, rsz, ra = struct.unpack_from("<IIII", self.data, off + 8)
            self.sections.append((va, vsz, ra, rsz))

        if num_rvas > 0:
            exp_rva, exp_size = struct.unpack_from("<II", self.data, opt_off + 112)
            self._parse_exports(exp_rva, exp_size)

        if num_rvas <= 3:
            return
        exc_rva, exc_size = struct.unpack_from("<II", self.data, opt_off + 112 + 3 * 8)
        if exc_rva == 0 or exc_size < 12:
            return
        pdata_off = self._rva_to_off(exc_rva)
        if pdata_off is None:
            return

        n_entries = min(exc_size // 12, max(0, (len(self.data) - pdata_off) // 12))
        raw_entries: List[Tuple[int, int, int]] = []
        for i in range(n_entries):
            beg, end, uw = struct.unpack_from("<III", self.data, pdata_off + i * 12)
            if beg == 0 and end == 0:
                continue
            raw_entries.append((beg, end, uw))
        raw_entries.sort(key=lambda e: e[0])
        self.entries = raw_entries
        self.begins = [e[0] for e in raw_entries]

    def lookup(self, rva: int) -> Optional[Tuple[int, int, int]]:
        """Find the `RUNTIME_FUNCTION` `(BeginRVA, EndRVA, UnwindInfoRVA)` covering `rva`."""
        idx = bisect.bisect_right(self.begins, rva) - 1
        if idx < 0:
            return None
        entry = self.entries[idx]
        if entry[0] <= rva < entry[1]:
            return entry
        return None

    def unwind_step(
        self,
        rva: int,
        regs: List[int],
        read_u64,
    ) -> Optional[int]:
        """Unwind one stack frame at `rva` in place, returning caller return address."""
        entry = self.lookup(rva)
        if entry is None:
            # x64 leaf function: no stack frame allocated; return address sits at [RSP].
            ret = read_u64(regs[4])
            if ret is None:
                return None
            regs[4] += 8
            return ret

        beg, _, uw_rva = entry
        prolog_off = rva - beg
        if not self._apply_unwind_info(uw_rva, prolog_off, regs, read_u64, depth=0):
            return None

        ret = read_u64(regs[4])
        if ret is None:
            return None
        regs[4] += 8
        return ret

    def _apply_unwind_info(
        self,
        uw_rva: int,
        prolog_off: int,
        regs: List[int],
        read_u64,
        depth: int,
    ) -> bool:
        if depth > 8:
            return False
        uoff = self._rva_to_off(uw_rva)
        if uoff is None or uoff + 4 > len(self.data):
            return False

        ver_flags, size_of_prolog, count_of_codes, frame_byte = struct.unpack_from("<BBBB", self.data, uoff)
        flags = ver_flags >> 3
        frame_reg = frame_byte & 0xF
        frame_off = (frame_byte >> 4) * 16
        in_prolog = prolog_off < size_of_prolog

        # Codes are ordered descending by CodeOffset; apply all codes <= prolog_off if in prolog.
        code_base = uoff + 4
        idx = 0
        while idx < count_of_codes:
            coff = code_base + idx * 2
            if coff + 2 > len(self.data):
                return False
            code_offset, op_info = struct.unpack_from("<BB", self.data, coff)
            op = op_info & 0xF
            info = op_info >> 4
            active = (not in_prolog) or (code_offset <= prolog_off)

            if op == 0:  # UWOP_PUSH_NONVOL
                if active:
                    val = read_u64(regs[4])
                    if val is not None and info < 16:
                        regs[info] = val
                    regs[4] += 8
                idx += 1
            elif op == 1:  # UWOP_ALLOC_LARGE
                if info == 0:
                    if coff + 4 > len(self.data):
                        return False
                    sz = struct.unpack_from("<H", self.data, coff + 2)[0] * 8
                    idx += 2
                else:
                    if coff + 6 > len(self.data):
                        return False
                    sz = struct.unpack_from("<I", self.data, coff + 2)[0]
                    idx += 3
                if active:
                    regs[4] += sz
            elif op == 2:  # UWOP_ALLOC_SMALL
                if active:
                    regs[4] += info * 8 + 8
                idx += 1
            elif op == 3:  # UWOP_SET_FPREG
                if active and 0 < frame_reg < 16:
                    regs[4] = regs[frame_reg] - frame_off
                idx += 1
            elif op == 4:  # UWOP_SAVE_NONVOL
                if coff + 4 > len(self.data):
                    return False
                slot = struct.unpack_from("<H", self.data, coff + 2)[0] * 8
                if active and info < 16:
                    base_ptr = regs[frame_reg] if (0 < frame_reg < 16) else regs[4]
                    val = read_u64(base_ptr + slot)
                    if val is not None:
                        regs[info] = val
                idx += 2
            elif op == 5:  # UWOP_SAVE_NONVOL_FAR
                if coff + 6 > len(self.data):
                    return False
                slot = struct.unpack_from("<I", self.data, coff + 2)[0]
                if active and info < 16:
                    base_ptr = regs[frame_reg] if (0 < frame_reg < 16) else regs[4]
                    val = read_u64(base_ptr + slot)
                    if val is not None:
                        regs[info] = val
                idx += 3
            elif op == 8:  # UWOP_SAVE_XMM128
                idx += 2
            elif op == 9:  # UWOP_SAVE_XMM128_FAR
                idx += 3
            elif op == 10:  # UWOP_PUSH_MACHFRAME
                if active:
                    regs[4] += 48 if info == 1 else 40
                idx += 1
            else:
                idx += 1

        if flags & 0x04:  # UNW_FLAG_CHAININFO
            aligned_codes = count_of_codes + (count_of_codes & 1)
            chain_off = code_base + aligned_codes * 2
            if chain_off + 12 > len(self.data):
                return False
            _, _, chained_uw_rva = struct.unpack_from("<III", self.data, chain_off)
            return self._apply_unwind_info(chained_uw_rva, prolog_off, regs, read_u64, depth + 1)

        return True


# ---------------------------------------------------------------------------
# DWARF Symbol & Inline-Frame Attribution (llvm-nm + llvm-objdump)
# ---------------------------------------------------------------------------


def parse_inline_objdump(lines: Sequence[str], root_symbol: str) -> List[Dict[str, Any]]:
    """Parse `llvm-objdump -d --demangle --debug-inlined-funcs=ascii` into per-instruction records.

    Returns a list of dicts `{addr, mnem, text, stack}` where `stack` is the full
    inlined frame chain `[root_symbol, ...inlined_callees...]`.
    """
    records: List[Dict[str, Any]] = []
    # Map slot column index -> (callee_name, caller_name)
    open_slots: Dict[int, str] = {}
    base_col: Optional[int] = None

    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            continue

        # Detect inline header declarations: `[| ]*/- callee = inlined into caller`
        stripped_leading = line.lstrip()
        if not _HEX_INSN_RE.match(line):
            hdr_pos = None
            for marker in ("/-", "|-"):
                idx = line.find(marker)
                if idx != -1 and (" = " in line[idx:] or line.rstrip().endswith(" =")):
                    # Step backwards to find any leading '| ' slot prefixes.
                    pos = idx
                    while pos >= 2 and line[pos - 2 : pos] == "| ":
                        pos -= 2
                    hdr_pos = pos
                    break
            if hdr_pos is not None:
                if base_col is None and not stripped_leading.startswith(";"):
                    base_col = hdr_pos
                m_hdr = _HDR_MARKER_RE.match(line[hdr_pos:])
                if m_hdr:
                    slot = m_hdr.group(1).count("|")
                    callee = _clean_frame_name(m_hdr.group(2))
                    # Opening slot `k` supersedes any previously stale slot >= k.
                    for stale in [s for s in open_slots if s >= slot]:
                        del open_slots[stale]
                    open_slots[slot] = callee
            continue

        m_insn = _HEX_INSN_RE.match(line)
        if not m_insn:
            continue
        addr = int(m_insn.group(1), 16)

        # Extract trailing bar characters (`^`, `|`, `v`) aligned to slot columns.
        col_start = base_col if base_col is not None else 92
        active_slots: List[int] = []
        closing_slots: List[int] = []

        # Locate where trailing bar markers begin.
        marker_tail = ""
        if len(line) > col_start and re.fullmatch(r"[\s|^v]*", line[col_start:]):
            marker_tail = line[col_start:]
        else:
            m_tail = re.search(r"\s([|^v](?:\s+[|^v])*)\s*$", line)
            if m_tail:
                # Instruction text pushed bars right; slot 0 starts at m_tail.start(1).
                marker_tail = m_tail.group(1)

        if marker_tail:
            for slot in sorted(open_slots):
                pos = slot * 2
                if pos < len(marker_tail):
                    ch = marker_tail[pos]
                    if ch in ("^", "|", "v"):
                        active_slots.append(slot)
                    if ch == "v":
                        closing_slots.append(slot)
            # Handle 1-instruction scopes marked only by `^` on a single slot.
            # When the next instruction has no marker for that slot, we still
            # close slots that didn't appear if they weren't active on the line.
        elif open_slots:
            # Long instruction line whose inline bar was omitted or truncated: keep current slots.
            pass

        stack = [root_symbol]
        for slot in active_slots:
            if slot in open_slots:
                stack.append(open_slots[slot])

        # Strip bar tail before capturing instruction text.
        insn_body = line[:col_start] if (len(line) > col_start and re.fullmatch(r"[\s|^v]*", line[col_start:])) else line
        records.append({
            "addr": addr,
            "text": insn_body.strip(),
            "stack": stack,
        })

        for slot in closing_slots:
            open_slots.pop(slot, None)

    return records


class SymbolResolver:
    """Resolves binary VAs to demangled functions and DWARF inline call stacks."""

    def __init__(self, exe_path: Path) -> None:
        self.exe_path = Path(exe_path)
        self.llvm_nm = find_llvm_tool("llvm-nm")
        self.llvm_objdump = find_llvm_tool("llvm-objdump")
        self.pe = PEUnwindTable(self.exe_path.read_bytes(), mapped=False)
        self.sym_addrs: List[int] = []
        self.sym_names: List[str] = []
        self.sym_ranges: Dict[str, Tuple[int, int]] = {}
        self._func_insns: Dict[int, Tuple[List[int], List[List[str]]]] = {}
        self._func_records: Dict[int, List[Dict[str, Any]]] = {}
        self._load_symbols()

    def _run_objdump(self, extra_args: Sequence[str]) -> List[str]:
        cmd = [
            self.llvm_objdump,
            "-d",
            "--demangle",
            "--debug-inlined-funcs=ascii",
            *extra_args,
            str(self.exe_path),
        ]
        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                out = subprocess.check_output(
                    cmd,
                    text=True,
                    encoding="utf-8",
                    stderr=subprocess.PIPE,
                    errors="replace",
                    timeout=60,
                )
                return out.splitlines()
            except subprocess.CalledProcessError as exc:
                last_err = exc
                if "Permission denied" in (exc.stderr or "") and attempt < 3:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(f"llvm-objdump failed: {last_err}")

    def preload_all_functions(self) -> None:
        """Disassemble `.text` once and index instruction records by function start VA."""
        if self._func_records or not self.sym_addrs:
            return
        lines = self._run_objdump([])
        current_start: Optional[int] = None
        current_name = "unknown"
        buf: List[str] = []
        sym_hdr_re = re.compile(r"^([0-9a-f]+)\s+<(.+)>:\s*$")

        def flush() -> None:
            if current_start is not None and buf:
                recs = parse_inline_objdump(buf, _clean_frame_name(current_name))
                self._func_records[current_start] = recs
                self._func_insns[current_start] = ([r["addr"] for r in recs], [r["stack"] for r in recs])

        for line in lines:
            m = sym_hdr_re.match(line)
            if m:
                flush()
                current_start = int(m.group(1), 16)
                current_name = m.group(2)
                buf = []
            elif current_start is not None:
                buf.append(line)
        flush()

    def _load_symbols(self) -> None:
        out = subprocess.check_output(
            [self.llvm_nm, "-n", "--demangle", str(self.exe_path)],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        text_syms: List[Tuple[int, str]] = []
        for line in out.splitlines():
            m = _NM_LINE_RE.match(line.strip())
            if not m:
                continue
            addr = int(m.group(1), 16)
            kind = m.group(2)
            name = m.group(3).strip()
            if kind in ("t", "T"):
                text_syms.append((addr, name))

        # Collapse duplicate addresses while keeping the first meaningful symbol name.
        seen_addr: Dict[int, str] = {}
        for addr, name in text_syms:
            seen_addr.setdefault(addr, name)
        ordered = sorted(seen_addr.items())
        self.sym_addrs = [a for a, _ in ordered]
        self.sym_names = [n for _, n in ordered]

        for i, (start_addr, name) in enumerate(ordered):
            end_addr = ordered[i + 1][0] if i + 1 < len(ordered) else start_addr + 0x1000
            if end_addr > start_addr:
                self.sym_ranges.setdefault(name, (start_addr, end_addr))

    def find_symbol_interval(self, addr: int) -> Optional[Tuple[int, int, str]]:
        """Return `(start_va, end_va, demangled_name)` containing `addr`, or None."""
        idx = bisect.bisect_right(self.sym_addrs, addr) - 1
        if idx < 0:
            return None
        start = self.sym_addrs[idx]
        end = self.sym_addrs[idx + 1] if idx + 1 < len(self.sym_addrs) else start + 0x10000
        if start <= addr < end:
            return start, end, self.sym_names[idx]
        return None

    def find_symbols_matching(self, substring: str) -> List[Tuple[int, int, str]]:
        """Return `(start_va, end_va, name)` for text symbols matching `substring`."""
        hits: List[Tuple[int, int, str]] = []
        for i, name in enumerate(self.sym_names):
            if substring in name:
                start = self.sym_addrs[i]
                end = self.sym_addrs[i + 1] if i + 1 < len(self.sym_addrs) else start + 0x1000
                hits.append((start, end, name))
        return hits

    def disassemble_interval(self, start_va: int, stop_va: int, root_name: str) -> List[Dict[str, Any]]:
        """Disassemble `[start_va, stop_va)` with DWARF inline frames via `llvm-objdump`."""
        if start_va in self._func_records:
            return self._func_records[start_va]
        lines = self._run_objdump([f"--start-address=0x{start_va:x}", f"--stop-address=0x{stop_va:x}"])
        recs = parse_inline_objdump(lines, _clean_frame_name(root_name))
        self._func_records[start_va] = recs
        self._func_insns[start_va] = ([r["addr"] for r in recs], [r["stack"] for r in recs])
        return recs

    def resolve_va_frames(self, va: int) -> List[str]:
        """Resolve an image VA inside `exe_path` into `[outer_fn, ...inlined_callees...]`."""
        info = self.find_symbol_interval(va)
        if info is None:
            return [f"unknown@0x{va:x}"]
        start, end, name = info
        clean_name = _clean_frame_name(name)
        if start not in self._func_insns:
            # Cap single gigantic functions at 256 KB so disassembly stays snappy.
            stop = min(end, start + 262144)
            records = self.disassemble_interval(start, stop, clean_name)
            addrs = [r["addr"] for r in records]
            stacks = [r["stack"] for r in records]
            self._func_insns[start] = (addrs, stacks)
        addrs, stacks = self._func_insns[start]
        if not addrs:
            return [clean_name]
        idx = bisect.bisect_right(addrs, va) - 1
        if idx < 0:
            return [clean_name]
        return stacks[idx]


# ---------------------------------------------------------------------------
# Win32 User-Mode CPU Stack Sampler (Zero Admin / Zero ETW)
# ---------------------------------------------------------------------------


def _win32_sample_child(
    exe_path: Path,
    bench_args: Sequence[str],
    freq_hz: int = 1000,
    max_depth: int = 64,
    high_priority: bool = False,
) -> Dict[str, Any]:
    """Run `exe_path` as a child process and collect Win32 user-mode stack samples."""
    if platform.system() != "Windows":
        raise RuntimeError("Win32 user-mode sampling is only supported on Windows.")

    k32 = ctypes.windll.kernel32
    winmm = ctypes.windll.winmm

    # Structures for Toolhelp32 module & thread enumeration.
    class THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("cntUsage", wt.DWORD),
            ("th32ThreadID", wt.DWORD),
            ("th32OwnerProcessID", wt.DWORD),
            ("tpBasePri", wt.LONG),
            ("tpDeltaPri", wt.LONG),
            ("dwFlags", wt.DWORD),
        ]

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("th32ModuleID", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("GlblcntUsage", wt.DWORD),
            ("ProccntUsage", wt.DWORD),
            ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
            ("modBaseSize", wt.DWORD),
            ("hModule", wt.HMODULE),
            ("szModule", wt.WCHAR * 256),
            ("szExePath", wt.WCHAR * 260),
        ]

    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenThread.restype = wt.HANDLE
    k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.SuspendThread.restype = wt.DWORD
    k32.SuspendThread.argtypes = [wt.HANDLE]
    k32.ResumeThread.restype = wt.DWORD
    k32.ResumeThread.argtypes = [wt.HANDLE]
    k32.GetThreadContext.restype = wt.BOOL
    k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.c_void_p]
    k32.ReadProcessMemory.restype = wt.BOOL
    k32.ReadProcessMemory.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k32.CloseHandle.argtypes = [wt.HANDLE]

    creation_flags = 0x00000080 if high_priority else 0  # HIGH_PRIORITY_CLASS
    proc = subprocess.Popen(
        [str(exe_path), *bench_args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
    )

    h_proc = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, proc.pid)
    if not h_proc:
        proc.kill()
        raise PermissionError(f"OpenProcess failed for PID {proc.pid} (err={ctypes.GetLastError()})")

    # Locate main thread (first thread matching PID).
    main_tid = None
    for _ in range(50):
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if snap and snap != -1:
            te = THREADENTRY32()
            te.dwSize = ctypes.sizeof(THREADENTRY32)
            if k32.Thread32First(snap, ctypes.byref(te)):
                while True:
                    if te.th32OwnerProcessID == proc.pid:
                        main_tid = te.th32ThreadID
                        break
                    if not k32.Thread32Next(snap, ctypes.byref(te)):
                        break
            k32.CloseHandle(snap)
        if main_tid is not None:
            break
        time.sleep(0.002)

    if main_tid is None:
        k32.CloseHandle(h_proc)
        proc.wait()
        raise RuntimeError("Could not locate main thread of target process.")

    h_thread = k32.OpenThread(
        THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,
        False,
        main_tid,
    )
    if not h_thread:
        k32.CloseHandle(h_proc)
        proc.wait()
        raise PermissionError(f"OpenThread failed for TID {main_tid} (err={ctypes.GetLastError()})")

    # Enumerate loaded modules so ASLR bases & system DLL unwind tables are known.
    modules: List[Tuple[int, int, str, str]] = []
    for _ in range(25):
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, proc.pid)
        if snap and snap != -1:
            me = MODULEENTRY32W()
            me.dwSize = ctypes.sizeof(MODULEENTRY32W)
            if k32.Module32FirstW(snap, ctypes.byref(me)):
                while True:
                    base = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value or 0
                    modules.append((base, me.modBaseSize, me.szModule, me.szExePath))
                    if not k32.Module32NextW(snap, ctypes.byref(me)):
                        break
            k32.CloseHandle(snap)
        if modules:
            break
        time.sleep(0.002)

    # Prepare 16-byte-aligned CONTEXT_AMD64 buffer & stack snapshot buffer.
    raw_ctx = (ctypes.c_ubyte * (CONTEXT_SIZE + 32))()
    ctx_addr = (ctypes.addressof(raw_ctx) + 15) & ~15
    ctx_view = (ctypes.c_ubyte * CONTEXT_SIZE).from_address(ctx_addr)
    stack_buf = (ctypes.c_ubyte * 16384)()
    bytes_read = ctypes.c_size_t(0)

    interval_s = 1.0 / max(1, freq_hz)
    raw_samples: List[Tuple[Tuple[int, ...], int, bytes]] = []  # (regs_0..15 + rip, rsp_base, stack_bytes)

    winmm.timeBeginPeriod(1)
    t_start = time.monotonic()
    try:
        while proc.poll() is None:
            struct.pack_into("<I", ctx_view, 0x30, CONTEXT_AMD64_CONTROL_INT)
            prev_susp = k32.SuspendThread(h_thread)
            if prev_susp == 0xFFFFFFFF:
                break
            try:
                if k32.GetThreadContext(h_thread, ctypes.c_void_p(ctx_addr)):
                    ctx_bytes = bytes(ctx_view)
                    regs = struct.unpack_from("<16Q", ctx_bytes, 0x78)
                    rip = struct.unpack_from("<Q", ctx_bytes, 0xF8)[0]
                    rsp = regs[4]
                    # Read up to 16 KB contiguously from stack top in page-bounded chunks.
                    chunks = []
                    cur = rsp
                    for _ in range(5):
                        to_read = min(4096 - (cur & 0xFFF), 16384 - (cur - rsp))
                        if to_read <= 0:
                            break
                        ok = k32.ReadProcessMemory(
                            h_proc,
                            ctypes.c_void_p(cur),
                            stack_buf,
                            to_read,
                            ctypes.byref(bytes_read),
                        )
                        if not ok or bytes_read.value == 0:
                            break
                        chunks.append(bytes(stack_buf[: bytes_read.value]))
                        cur += bytes_read.value
                        if bytes_read.value < to_read:
                            break
                    raw_samples.append(((*regs, rip), rsp, b"".join(chunks)))
            finally:
                k32.ResumeThread(h_thread)

            # Refresh module list once if only partial modules were visible at startup.
            if len(modules) <= 2 and proc.poll() is None:
                snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, proc.pid)
                if snap and snap != -1:
                    me = MODULEENTRY32W()
                    me.dwSize = ctypes.sizeof(MODULEENTRY32W)
                    new_mods = []
                    if k32.Module32FirstW(snap, ctypes.byref(me)):
                        while True:
                            base = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value or 0
                            new_mods.append((base, me.modBaseSize, me.szModule, me.szExePath))
                            if not k32.Module32NextW(snap, ctypes.byref(me)):
                                break
                    k32.CloseHandle(snap)
                    if len(new_mods) > len(modules):
                        modules = new_mods

            time.sleep(interval_s)
    finally:
        winmm.timeEndPeriod(1)
        k32.CloseHandle(h_thread)
        k32.CloseHandle(h_proc)

    wall_s = time.monotonic() - t_start
    _, stderr_bytes = proc.communicate()
    if proc.returncode != 0:
        err_txt = (stderr_bytes or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"Profiled child exited with code {proc.returncode}: {err_txt}")

    # Load PE unwind tables for every loaded module (EXE + DLLs).
    mod_tables: List[Tuple[int, int, str, Optional[PEUnwindTable]]] = []
    main_mod_name = exe_path.name.lower()
    main_base = None
    for base, size, mod_name, mod_path in modules:
        if mod_name.lower() == main_mod_name:
            main_base = base
        tbl = None
        p = Path(mod_path)
        if p.is_file() and p.stat().st_size <= MAX_MODULE_CACHE_BYTES * 4:
            try:
                tbl = PEUnwindTable(p.read_bytes(), mapped=False)
            except OSError:
                tbl = None
        mod_tables.append((base, base + size, mod_name, tbl))
    mod_tables.sort(key=lambda m: m[0])
    mod_starts = [m[0] for m in mod_tables]

    def find_mod(pc: int):
        idx = bisect.bisect_right(mod_starts, pc) - 1
        if idx >= 0:
            b, e, name, tbl = mod_tables[idx]
            if b <= pc < e:
                return b, name, tbl
        return None

    resolver = SymbolResolver(exe_path)
    image_base = resolver.pe.image_base

    folded: Counter = Counter()
    total_samples = 0
    in_main_samples = 0

    for reg_tuple, rsp_base, stack_bytes in raw_samples:
        regs = list(reg_tuple[:16])
        pc = reg_tuple[16]

        def read_u64(addr: int, _base: int = rsp_base, _buf: bytes = stack_bytes) -> Optional[int]:
            off = addr - _base
            if 0 <= off and off + 8 <= len(_buf):
                return struct.unpack_from("<Q", _buf, off)[0]
            return None

        frames: List[str] = []
        seen_pcs = set()
        for step in range(max_depth):
            if pc == 0 or (step > 0 and pc in seen_pcs and len(frames) > 2):
                break
            seen_pcs.add(pc)
            mod = find_mod(pc)
            if mod is None:
                frames.append(f"unknown@0x{pc:x}")
                break
            mbase, mname, tbl = mod
            rva = pc - mbase
            if main_base is not None and mbase == main_base:
                va = image_base + rva
                # Resolve innermost instruction (step == 0) vs call site return addr (pc - 1).
                lookup_va = va if step == 0 else max(image_base, va - 1)
                inlined = resolver.resolve_va_frames(lookup_va)
                # Append inner-to-outer so reversing gives root -> leaf.
                frames.extend(reversed(inlined))
            else:
                exp = tbl.resolve_export(rva) if tbl is not None else None
                frames.append(f"{mname}!{exp}" if exp else f"{mname}!+0x{rva:x}")

            if tbl is None:
                break
            next_pc = tbl.unwind_step(rva, regs, read_u64)
            if next_pc is None or next_pc == 0 or find_mod(next_pc) is None:
                break
            pc = next_pc

        if not frames:
            continue
        root_to_leaf = list(reversed(frames))
        # Trim C runtime / Rust lang_start preamble above `noise_bench::main` (or `main`) when present.
        for anchor_idx, fname in enumerate(root_to_leaf):
            if fname.endswith("::main"):
                root_to_leaf = root_to_leaf[anchor_idx:]
                in_main_samples += 1
                break
        else:
            for anchor_idx, fname in enumerate(root_to_leaf):
                if fname == "main":
                    root_to_leaf = root_to_leaf[anchor_idx:]
                    in_main_samples += 1
                    break
        folded[";".join(root_to_leaf)] += 1
        total_samples += 1

    return {
        "folded": dict(folded),
        "total_samples": total_samples,
        "in_main_samples": in_main_samples,
        "wall_seconds": round(wall_s, 3),
        "freq_hz": freq_hz,
    }


def write_folded(folded: Dict[str, int], out_path: Path) -> None:
    """Write folded stacks (`frame1;frame2 <count>`) sorted by descending weight."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{stack} {count}"
        for stack, count in sorted(folded.items(), key=lambda kv: (-kv[1], kv[0]))
        if count > 0
    ]
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# ---------------------------------------------------------------------------
# Static Instruction-Count & Assembly Attribution
# ---------------------------------------------------------------------------


def _extract_loop_addresses(records: Sequence[Dict[str, Any]]) -> set[int]:
    """Identify addresses inside natural loops (targets of backward branches)."""
    if not records:
        return set()
    addrs = [r["addr"] for r in records]
    loop_addrs: set[int] = set()
    for r in records:
        text = r["text"]
        # Match any conditional or unconditional jump backwards within this function.
        m = re.search(r"\b(?:j[a-z]+)\s+0x([0-9a-f]+)", text)
        if m:
            target = int(m.group(1), 16)
            if addrs[0] <= target < r["addr"]:
                lo = bisect.bisect_left(addrs, target)
                hi = bisect.bisect_right(addrs, r["addr"])
                loop_addrs.update(addrs[lo:hi])
    return loop_addrs


def _is_relevant_callee(name: str) -> bool:
    """Keep regex/noise-bench callees while skipping cold panic/unwind/std formatting stubs."""
    skip_tokens = (
        "panicking",
        "panic_",
        "begin_unwind",
        "drop_in_place",
        "fmt::",
        "unwrap_failed",
        "slice_index_",
        "capacity_overflow",
    )
    if any(tok in name for tok in skip_tokens):
        return False
    return any(
        pkg in name
        for pkg in ("noise_bench", "regex", "memchr", "aho_corasick")
    )


def analyze_binary_instructions(
    exe_path: Path,
    symbol_query: str = "noise_bench::bench_",
    max_call_depth: int = 3,
) -> Dict[str, Any]:
    """Disassemble benchmark symbol(s) + regex callees and compute instruction & spill attribution."""
    resolver = SymbolResolver(exe_path)
    resolver.preload_all_functions()
    roots = resolver.find_symbols_matching(symbol_query)
    if not roots:
        raise ValueError(f"No symbols matching {symbol_query!r} found in {exe_path.name}")

    folded: Counter = Counter()
    function_stats: Dict[str, Dict[str, Any]] = {}
    visited_starts: set[int] = set()

    queue: List[Tuple[int, int, str, Tuple[str, ...], int]] = [
        (start, end, _clean_frame_name(name), (_clean_frame_name(name),), 0)
        for start, end, name in roots
    ]

    while queue:
        start, end, name, prefix_stack, depth = queue.pop(0)
        if start in visited_starts:
            continue
        visited_starts.add(start)

        stop = min(end, start + 262144)
        records = resolver.disassemble_interval(start, stop, name)
        loop_addrs = _extract_loop_addresses(records)

        total_insns = len(records)
        loop_insns = 0
        rsp_loads = 0
        rsp_stores = 0
        calls: List[str] = []

        for r in records:
            text = r["text"]
            # Build folded stack combining call chain + DWARF inlined frames.
            inline_tail = r["stack"][1:] if len(r["stack"]) > 1 else []
            full_stack = [*prefix_stack, *inline_tail]
            folded[";".join(full_stack)] += 1

            if r["addr"] in loop_addrs:
                loop_insns += 1
            if _RSP_MEM_RE.search(text):
                # AT&T syntax: `movq 0x80(%rsp), %rax` -> load; `movq %rax, 0x80(%rsp)` -> store.
                after_comma = text.split(",", 1)[1] if "," in text else ""
                if "(%rsp)" in after_comma:
                    rsp_stores += 1
                else:
                    rsp_loads += 1

            m_call = _CALL_TARGET_RE.search(text)
            if m_call:
                target_addr = int(m_call.group(1), 16)
                target_info = resolver.find_symbol_interval(target_addr)
                if target_info is not None:
                    c_start, c_end, c_name = target_info
                    clean_c = _clean_frame_name(c_name)
                    calls.append(clean_c)
                    if depth < max_call_depth and c_start not in visited_starts and _is_relevant_callee(clean_c):
                        queue.append((c_start, c_end, clean_c, (*full_stack, clean_c), depth + 1))

        function_stats[name] = {
            "start_va": hex(start),
            "static_insns": total_insns,
            "loop_insns": loop_insns,
            "rsp_loads": rsp_loads,
            "rsp_stores": rsp_stores,
            "unique_callees": sorted(set(calls)),
        }

    # Summarize by leaf frame as well.
    leaf_counts: Counter = Counter()
    for stack_str, cnt in folded.items():
        leaf_counts[stack_str.rsplit(";", 1)[-1]] += cnt

    return {
        "binary": exe_path.name,
        "symbol_query": symbol_query,
        "total_static_insns": sum(folded.values()),
        "functions": function_stats,
        "top_leaves": dict(leaf_counts.most_common(25)),
        "folded": dict(folded),
    }


def compare_asm_metrics(base_info: Dict[str, Any], cand_info: Dict[str, Any]) -> Dict[str, Any]:
    """Compute per-function and total static instruction/spill deltas between base and cand."""
    all_funcs = sorted(set(base_info["functions"]) | set(cand_info["functions"]))
    per_func = []
    for fn in all_funcs:
        b = base_info["functions"].get(fn, {})
        c = cand_info["functions"].get(fn, {})
        b_ins = b.get("static_insns", 0)
        c_ins = c.get("static_insns", 0)
        b_loop = b.get("loop_insns", 0)
        c_loop = c.get("loop_insns", 0)
        b_ld = b.get("rsp_loads", 0)
        c_ld = c.get("rsp_loads", 0)
        per_func.append({
            "function": fn,
            "base_insns": b_ins,
            "cand_insns": c_ins,
            "insn_delta": c_ins - b_ins,
            "base_loop_insns": b_loop,
            "cand_loop_insns": c_loop,
            "loop_delta": c_loop - b_loop,
            "base_rsp_loads": b_ld,
            "cand_rsp_loads": c_ld,
            "rsp_load_delta": c_ld - b_ld,
        })
    per_func.sort(key=lambda r: abs(r["insn_delta"]) + abs(r["loop_delta"]), reverse=True)
    return {
        "base_total_static_insns": base_info["total_static_insns"],
        "cand_total_static_insns": cand_info["total_static_insns"],
        "total_insn_delta": cand_info["total_static_insns"] - base_info["total_static_insns"],
        "function_diffs": per_func,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_sample(args: argparse.Namespace) -> int:
    exe = Path(args.exe).resolve()
    if not exe.exists():
        print(f"Error: binary not found: {exe}", file=sys.stderr)
        return 1
    bench_args = [args.bench, str(args.iters), str(args.warmup), "0", "--format=raw"]
    res = _win32_sample_child(
        exe,
        bench_args,
        freq_hz=args.freq,
        high_priority=args.high_priority,
    )
    out = Path(args.out)
    write_folded(res["folded"], out)
    print(
        f"[win_profile] sampled {res['total_samples']} stacks ({res['in_main_samples']} rooted in main) "
        f"in {res['wall_seconds']}s @ {res['freq_hz']} Hz -> {out.name}"
    )
    return 0


def _cmd_insn(args: argparse.Namespace) -> int:
    exe = Path(args.exe).resolve()
    if not exe.exists():
        print(f"Error: binary not found: {exe}", file=sys.stderr)
        return 1
    info = analyze_binary_instructions(exe, symbol_query=args.symbol, max_call_depth=args.depth)
    out = Path(args.out)
    write_folded(info["folded"], out)
    if args.json:
        json_out = Path(args.json)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in info.items() if k != "folded"}
        json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[win_profile] static instruction attribution: {info['total_static_insns']} insns across "
        f"{len(info['functions'])} functions -> {out.name}"
    )
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    base_exe = Path(args.base_exe).resolve()
    cand_exe = Path(args.cand_exe).resolve()
    for p in (base_exe, cand_exe):
        if not p.exists():
            print(f"Error: binary not found: {p}", file=sys.stderr)
            return 1

    base_folded_path = Path(args.base_folded)
    cand_folded_path = Path(args.cand_folded)

    if args.mode == "sample":
        bench_args = [args.bench, str(args.iters), str(args.warmup), "0", "--format=raw"]
        res_b = _win32_sample_child(base_exe, bench_args, freq_hz=args.freq, high_priority=args.high_priority)
        res_c = _win32_sample_child(cand_exe, bench_args, freq_hz=args.freq, high_priority=args.high_priority)
        stacks_a, stacks_b = res_b["folded"], res_c["folded"]
        print(
            f"[win_profile] sample mode: base={res_b['total_samples']} samples ({res_b['wall_seconds']}s), "
            f"cand={res_c['total_samples']} samples ({res_c['wall_seconds']}s)"
        )
    else:
        sym = args.symbol or _default_symbol_for_bench(args.bench)
        info_b = analyze_binary_instructions(base_exe, symbol_query=sym, max_call_depth=args.depth)
        info_c = analyze_binary_instructions(cand_exe, symbol_query=sym, max_call_depth=args.depth)
        stacks_a, stacks_b = info_b["folded"], info_c["folded"]
        asm_diff = compare_asm_metrics(info_b, info_c)
        print(
            f"[win_profile] insn mode ({sym}): base={asm_diff['base_total_static_insns']} insns, "
            f"cand={asm_diff['cand_total_static_insns']} insns (delta={asm_diff['total_insn_delta']:+d})"
        )
        if args.asm_json:
            Path(args.asm_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.asm_json).write_text(json.dumps(asm_diff, indent=2), encoding="utf-8")

    write_folded(stacks_a, base_folded_path)
    write_folded(stacks_b, cand_folded_path)

    total_a = sum(stacks_a.values())
    total_b = sum(stacks_b.values())
    svg_content, num_boxes = flamegraph.generate_diff_svg(
        stacks_a,
        total_a,
        stacks_b,
        total_b,
        title=args.title,
    )
    out_svg = Path(args.out_svg)
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_svg.write_text(svg_content, encoding="utf-8")
    print(f"[win_profile] wrote {base_folded_path.name}, {cand_folded_path.name}, and {out_svg.name} ({num_boxes} frames)")
    return 0


def _default_symbol_for_bench(bench: str) -> str:
    mapping = {
        "compile_moderate": "bench_compile",
        "find_iter_userid": "bench_find_all",
        "is_match_status": "bench_is_match",
        "rebar_curated_04_ruff_noqa_tweaked_lite": "bench_ruff_noqa_tweaked_lite",
        "rebar_curated_05_lexer_veryl_single": "bench_lexer_veryl_single",
        "rebar_curated_05_lexer_veryl_regexset": "bench_lexer_veryl_regexset",
        "rebar_reported_i988_sql_injection_compile": "bench_compile_pattern",
        "rebar_unicode_compile_one_letter": "bench_compile_pattern",
        "rebar_wild_rustsec_cargo_audit_bytes": "bench_rustsec_bytes",
    }
    if bench in mapping:
        return mapping[bench]
    if bench.startswith("rebar_"):
        return "run_rebar_bench"
    return bench


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Windows ETW-free stack sampling and static instruction attribution for differential flamegraphs."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_smp = sub.add_parser("sample", help="Sample a running noise-bench.exe child process via Win32 user-mode APIs")
    p_smp.add_argument("exe", help="Path to compiled noise-bench.exe")
    p_smp.add_argument("--bench", default="find_iter_userid", help="Benchmark name passed to noise-bench.exe")
    p_smp.add_argument("--iters", type=int, default=15000, help="Iterations for profiling run (default: 15000)")
    p_smp.add_argument("--warmup", type=int, default=200, help="Warmup iterations (default: 200)")
    p_smp.add_argument("--freq", type=int, default=1000, help="Sampling frequency in Hz (default: 1000)")
    p_smp.add_argument("--high-priority", action="store_true", help="Run child with HIGH_PRIORITY_CLASS")
    p_smp.add_argument("-o", "--out", required=True, help="Output .folded file path")

    p_ins = sub.add_parser("insn", help="Static instruction + DWARF inline attribution via llvm-tools (no execution)")
    p_ins.add_argument("exe", help="Path to compiled noise-bench.exe")
    p_ins.add_argument("--symbol", default="noise_bench::bench_", help="Symbol substring to analyze")
    p_ins.add_argument("--depth", type=int, default=3, help="Max static call-graph depth (default: 3)")
    p_ins.add_argument("-o", "--out", required=True, help="Output .folded file path")
    p_ins.add_argument("--json", help="Optional JSON output path for per-function instruction/spill counts")

    p_dif = sub.add_parser("diff", help="Profile/analyze base vs cand binaries and write differential flamegraph SVG")
    p_dif.add_argument("base_exe", help="Path to baseline noise-bench.exe")
    p_dif.add_argument("cand_exe", help="Path to candidate noise-bench.exe")
    p_dif.add_argument("--mode", choices=("sample", "insn"), default="sample", help="Attribution mode (default: sample)")
    p_dif.add_argument("--bench", default="find_iter_userid", help="Benchmark name (default: find_iter_userid)")
    p_dif.add_argument("--symbol", help="Symbol substring for insn mode (auto-mapped from --bench if omitted)")
    p_dif.add_argument("--iters", type=int, default=15000, help="Iterations for sample mode (default: 15000)")
    p_dif.add_argument("--warmup", type=int, default=200, help="Warmup iterations for sample mode (default: 200)")
    p_dif.add_argument("--freq", type=int, default=1000, help="Sampling frequency Hz for sample mode (default: 1000)")
    p_dif.add_argument("--depth", type=int, default=3, help="Call-graph depth for insn mode (default: 3)")
    p_dif.add_argument("--high-priority", action="store_true", help="Run sample children at HIGH_PRIORITY_CLASS")
    p_dif.add_argument("--base-folded", required=True, help="Output path for baseline .folded")
    p_dif.add_argument("--cand-folded", required=True, help="Output path for candidate .folded")
    p_dif.add_argument("--out-svg", required=True, help="Output path for differential SVG")
    p_dif.add_argument("--asm-json", help="Optional JSON path for static instruction diff (insn mode)")
    p_dif.add_argument("--title", default="Differential Flamegraph (Windows)", help="Differential SVG title")

    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "sample":
        return _cmd_sample(args)
    if args.cmd == "insn":
        return _cmd_insn(args)
    return _cmd_diff(args)


if __name__ == "__main__":
    sys.exit(main())
