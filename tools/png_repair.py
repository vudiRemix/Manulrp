import struct, zlib, os, sys, io
from PIL import Image
def chunk(t,data): return struct.pack('>I',len(data))+t+data+struct.pack('>I',zlib.crc32(t+data)&0xffffffff)
def repair(b):
    out=[b[:8]]; i=8; idat=b''; done=False
    while i+8<=len(b):
        ln,=struct.unpack('>I',b[i:i+4]); t=b[i+4:i+8]; data=b[i+8:i+8+ln]
        i+=12+ln
        if t==b'IDAT': idat+=data; continue
        if idat and not done:
            raw=zlib.decompressobj(-15).decompress(idat[2:])
            out.append(chunk(b'IDAT',zlib.compress(raw,9))); done=True
        if t in (b'iaPR',): continue
        out.append(chunk(t,data))
        if t==b'IEND': break
    return b''.join(out)
root=sys.argv[1]; st={'ok':0,'repaired':0,'converted':0,'fail':0}
for dp,dn,fn in os.walk(root):
  for f in fn:
    if not f.endswith('.png'): continue
    p=os.path.join(dp,f); b=open(p,'rb').read()
    try:
        im=Image.open(io.BytesIO(b)); im.load(); good=b
    except Exception:
        try:
            good=repair(b); im=Image.open(io.BytesIO(good)); im.load(); st['repaired']+=1
        except Exception as e:
            st['fail']+=1; print('FAIL',p,e); continue
    if im.mode=='RGBA' and good[24]==8 and good[25]==6 and good is b:
        st['ok']+=1; continue
    buf=io.BytesIO(); im.convert('RGBA').save(buf,'PNG',optimize=True)
    open(p,'wb').write(buf.getvalue()); st['converted']+=1
print(st)
