import sys, os, struct, zlib, marshal
exe, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
data = open(exe, 'rb').read()
MAGIC = b'MEI\x0c\x0b\x0a\x0b\x0e'
pos = data.rfind(MAGIC)
# PyInstaller >=2.1 cookie: magic(8) lenpkg(4) toc(4) toclen(4) pyver(4) pylibname(64)
lenpkg, toc, toclen, pyver = struct.unpack('!IIII', data[pos+8:pos+24])
cookie_size = 24 + 64
tail = len(data) - (pos + cookie_size)
overlay = len(data) - lenpkg - tail if False else pos + cookie_size - lenpkg
print('pyver', pyver, 'overlay', overlay)
p = overlay + toc
end = p + toclen
entries = []
while p < end:
    (esz,) = struct.unpack('!I', data[p:p+4])
    epos, clen, ulen, cflag, typ = struct.unpack('!IIIBc', data[p+4:p+18])
    name = data[p+18:p+esz].rstrip(b'\0').decode()
    entries.append((name, epos, clen, ulen, cflag, typ))
    p += esz
for name, epos, clen, ulen, cflag, typ in entries:
    blob = data[overlay+epos: overlay+epos+clen]
    if cflag: blob = zlib.decompress(blob)
    print(typ, name, len(blob))
    if typ in (b's', b'z', b'Z', b'm', b'M'):
        safe = name.replace('/', '_').replace('\\', '_')
        open(os.path.join(out, safe + ('.pyz' if typ in (b'z', b'Z') else '.code')), 'wb').write(blob)
