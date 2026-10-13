import sys, os, glob
sys.path.insert(0, os.path.join(sys.argv[1], 'cvlib'))
import cv2, numpy as np
S=sys.argv[1]; every=float(sys.argv[2]); cols=int(sys.argv[3]); out=sys.argv[4]; t0=float(sys.argv[5]); t1=float(sys.argv[6])
c=cv2.VideoCapture(os.path.join(S,'vid','v.mp4')); fps=c.get(5)
imgs=[]; i=0
while True:
    ok,f=c.read()
    if not ok: break
    t=i/fps; i+=1
    if t<t0 or t>t1: continue
    if abs((t-t0)/every-round((t-t0)/every))*every<0.5/fps:
        f=cv2.resize(f,(216,384)); cv2.putText(f,f'{t:.1f}s',(5,22),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,0,255),2); imgs.append(f)
while len(imgs)%cols: imgs.append(np.zeros_like(imgs[0]))
rows=[np.hstack(imgs[r*cols:(r+1)*cols]) for r in range(len(imgs)//cols)]
cv2.imwrite(os.path.join(S,'frames',out),np.vstack(rows)); print(len(imgs))
