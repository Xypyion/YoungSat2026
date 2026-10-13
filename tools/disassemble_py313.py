import sys
from xdis.load import load_module
from xdis import iscode
from xdis.op_imports import get_opcode_module
from xdis.bytecode import Bytecode

pyc, out = sys.argv[1], sys.argv[2]
r = load_module(pyc); version, co = r[0], r[3]
opc = get_opcode_module(version, 'CPython')
f = open(out, 'w', encoding='utf-8')

def walk(code, prefix):
    name = prefix + code.co_name
    f.write(f"\n\n######## {name}  (line {code.co_firstlineno})  args={code.co_varnames[:code.co_argcount]}\n")
    try:
        bc = Bytecode(code, opc)
        for ins in bc:
            ln = ins.starts_line if ins.starts_line else ''
            f.write(f"{str(ln):>5} {ins.offset:>5} {ins.opname:<28} {ins.argrepr}\n")
    except Exception as e:
        f.write(f"!! dis error {e}\n")
    for c in code.co_consts:
        if iscode(c):
            walk(c, name + '.')

walk(co, '')
