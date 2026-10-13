import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], 'cvlib'))
import cv2
S=sys.argv[1]
c=cv2.VideoCapture(os.path.join(S,'vid','v.mp4')); fps=c.get(5); n=int(c.get(7))
print('fps',fps,'frames',n,'dur',n/fps, c.get(3), c.get(4))
step=max(1,int(fps*1.0))
i=0; k=0
while True:
    ok,f=c.read()
    if not ok: break
    if i%step==0:
        h,w=f.shape[:2]; sc=480/max(h,w)
        f=cv2.resize(f,(int(w*sc),int(h*sc)))
        cv2.putText(f,f't={i/fps:.1f}s',(5,20),cv2.FONT_HERSHEY_SIMPLEX,0.6,(0,0,255),2)
        cv2.imwrite(os.path.join(S,'frames',f'f{k:03d}.jpg'),f); k+=1
    i+=1
print('saved',k)
