from __future__ import annotations
"""Generator-aware stable vector paths for scene-pair morphing."""
import math
import numpy as np
from PIL import Image, ImageDraw

VECTOR_GENERATOR_NAMES=frozenset({"PHASE ORBIT","PHASE LATTICE","GEOMETRIC FIELD","GEOMETRIC PLATE","AXONOMETRIC FIELD","POLYHEDRAL FIELD","MOBIUS FIELD"})

def _path(pid,pts,size,group="stroke",closed=False,width=1,alpha=180):
 w,h=max(1,int(size[0])),max(1,int(size[1]))
 return {"path_id":str(pid),"group":group,"closed":bool(closed),"points":[[float(x/(w-1 or 1)),float(y/(h-1 or 1))] for x,y in pts],"width":float(width),"color":[238.,238.,234.],"alpha":float(np.clip(alpha,0,255)),"opacity":1.}

def build_generator_vector_paths(name,metrics,seconds,size,settings):
 name=str(name).upper()
 if name not in VECTOR_GENERATOR_NAMES:return None
 w,h=max(1,int(size[0])),max(1,int(size[1]));u=float(min(w,h));cx,cy=w*.5,h*.5;d,s=float(settings.density),float(settings.speed);out=[]
 energies=metrics.energies if metrics.energies is not None else np.asarray([metrics.rms])
 corr=metrics.correlation if metrics.correlation is not None else np.eye(max(1,len(energies)))
 bands=metrics.bands if metrics.bands is not None else np.zeros(64)
 if name=="PHASE ORBIT":
  theta=np.linspace(0,math.tau*3,int(320+d*2100),dtype=np.float32)
  for i in range(max(2,min(8,2+metrics.source_count))):
   energy=float(energies[i%len(energies)]) if len(energies) else 0;partner=float(corr[i%corr.shape[0],(i+1)%corr.shape[1]]) if corr.size else 0
   a,b=2+i%5,3+((i*2+1)%7);phase=seconds*(.1+s*1.1)*(1+i*.17)+i*.73+partner*1.1+metrics.transient*.8
   radius=u*.36*(.28+.62*np.clip(energy*settings.response*5,0,1));mod=.18+metrics.centroid*.55+metrics.transient*.22
   r=radius*(.72+mod*np.sin(b*theta+phase)+.08*np.sin((a+b)*theta));x=cx+r*np.cos(a*theta+phase*.6);y=cy+r*np.sin(b*theta-phase*.4)
   out.append(_path(f"orbit:{i}",zip(x,y),size,"curve",False,1+i%2,int(np.clip(90+energy*settings.response*320+metrics.transient*35,80,245))))
  return out
 if name=="PHASE LATTICE":
  cols=int(9+d*38);rows=max(6,int(cols*h/w));xg,yg=np.meshgrid(np.linspace(w*.08,w*.92,cols),np.linspace(h*.08,h*.92,rows))
  phase=seconds*(.1+s*1.4);amp=3+metrics.energy*settings.response*45+metrics.transient*60
  pts=np.stack((xg+np.sin(yg/h*math.tau*3+phase+metrics.centroid*4)*amp,yg+np.cos(xg/w*math.tau*4-phase*.8+metrics.cross*2)*amp),axis=-1)
  for r in range(rows):out.append(_path(f"lattice:row:{r}",pts[r],size,"grid",False,1,155))
  for c in range(cols):out.append(_path(f"lattice:col:{c}",pts[:,c],size,"grid",False,1,110))
  interval=max(2,int(8-d*5));rad=1+int(metrics.transient*6*settings.response)
  for r in range(rows):
   for c in range(cols):
    if (r+c)%interval:continue
    x,y=pts[r,c];circ=[(x+math.cos(a)*rad,y+math.sin(a)*rad) for a in np.linspace(0,math.tau,8,endpoint=False)]
    out.append(_path(f"lattice:node:{r}:{c}",circ,size,"node",True,1,170+int(metrics.energy*70)))
  return out
 if name=="GEOMETRIC FIELD":
  theta=np.linspace(0,math.tau,360,endpoint=True,dtype=np.float32);motion=seconds*(.025+s*.12);base=u*(.12+metrics.energy*.11)
  for ring in range(3+int(d*5)):
   m=3+((ring*2+int(metrics.centroid*8))%9);n1=.55+metrics.low*1.1+ring*.07;n2=1.2+metrics.mid*2.2;n3=1.2+metrics.high*2.5
   ang=theta+motion*(1+ring*.13)+ring*.31;radial=(np.abs(np.cos(m*ang/4))**n2+np.abs(np.sin(m*ang/4))**n3)**(-1/max(.35,n1))
   radius=base*(.5+ring*.24)*np.clip(radial,0,2.6);x=cx+radius*np.cos(ang);y=cy+radius*np.sin(ang)*(.78+metrics.width*.22)
   out.append(_path(f"field:ring:{ring}",zip(x,y),size,"curve",True,1+ring%2,min(220,int(72+25*ring+metrics.transient*65))))
  for i in range(10+int(d*22)):
   a=math.tau*i/(10+int(d*22))+motion*.7;ri=base*(.18+metrics.low*.14);ro=base*(1.05+metrics.high*.30)
   out.append(_path(f"field:spoke:{i}",[(cx+math.cos(a)*ri,cy+math.sin(a)*ri),(cx+math.cos(a)*ro,cy+math.sin(a)*ro)],size,"line",False,1,70))
  return out
 if name=="GEOMETRIC PLATE":
  phase=seconds*(.035+s*.12)+metrics.centroid*.7;inset=u*(.10+metrics.low*.035);x0,y0,x1,y1=inset,inset*.72,w-inset,h-inset*.72
  for i in range(3):
   dx=math.sin(phase+i*1.7)*u*(.025+metrics.transient*.025);dy=math.cos(phase*.83+i)*u*.018;p=i*u*.045
   pts=[(x0+p+dx,y0+p+dy),(x1-p+dx,y0+p+dy),(x1-p+dx,y1-p+dy),(x0+p+dx,y1-p+dy)]
   out.append(_path(f"plate:frame:{i}",pts,size,"frame",True,max(1,int(u/480)),205 if i==0 else 125))
  sw,sh=w*(.20+metrics.mid*.10),h*(.18+metrics.high*.10);shift=math.sin(phase)*w*.05
  rects=[[(cx-sw-shift,cy-sh*.42),(cx-shift,cy-sh*.42),(cx-shift,cy+sh*.58),(cx-sw-shift,cy+sh*.58)],[(cx+shift,cy-sh*.60),(cx+sw+shift,cy-sh*.60),(cx+sw+shift,cy+sh*.40),(cx+shift,cy+sh*.40)]]
  for i,pts in enumerate(rects):out.append(_path(f"plate:slab:{i}",pts,size,"frame",True,2,195-i*15))
  for i in range(7+int(d*11)):
   band=float(bands[i%len(bands)]) if len(bands) else 0;x=int(w*.14)+i*int(w*.034);by=int(h*.76);bh=int(h*(.012+band*.085+metrics.transient*.02))
   out.append(_path(f"plate:bar:{i}",[(x,by-bh),(x,by)],size,"line",False,2,125))
  mark=max(3,int(u*.012))
  for i,(x,y) in enumerate(((w*.12,h*.17),(w*.88,h*.17),(w*.12,h*.83),(w*.88,h*.83))):
   out.append(_path(f"plate:cross:{i}:h",[(x-mark,y),(x+mark,y)],size,"line",False,1,205));out.append(_path(f"plate:cross:{i}:v",[(x,y-mark),(x,y+mark)],size,"line",False,1,205))
  return out
 if name=="POLYHEDRAL FIELD":
  motion=seconds*(.025+s*.10);rings=2+int(d*4);verts=[]
  for i in range(12):
   a=math.tau*i/6;verts.append((math.cos(a),math.sin(a),(.62 if i<6 else -.62)))
  edges=[]
  for a in range(12):
   for b in range(a+1,12):
    if (a<6 and b<6 and b-a in (1,5)) or (a>=6 and b>=6 and b-a in (1,5)) or (a<6 and b>=6 and b-6-a in (0,1,5)):edges.append((a,b))
  for ring in range(rings):
   az=motion*(1+ring*.21)+ring*.46+metrics.centroid;el=.48+metrics.high*.36+ring*.035;scale=u*(.10+ring*.075+metrics.energy*.035);proj=[]
   for x,y,z in verts:
    xr=x*math.cos(az)-y*math.sin(az);yr=x*math.sin(az)+y*math.cos(az);yy=yr*math.cos(el)-z*math.sin(el);proj.append((cx+xr*scale,cy+yy*scale))
   alpha=min(220,100+ring*20+int(metrics.transient*45))
   for i,(a,b) in enumerate(edges):out.append(_path(f"poly:{ring}:edge:{i}",[proj[a],proj[b]],size,"line",False,1,alpha))
  return out
 if name=="MOBIUS FIELD":
  uv=np.linspace(0,math.tau,int(60+d*120),dtype=np.float32);vv=np.linspace(-.8,.8,int(12+d*28),dtype=np.float32);U,V=np.meshgrid(uv,vv)
  twist=.5*U+seconds*(.08+s*.5)+metrics.transient*.2;radius=u*(.22+metrics.energy*.13)
  x=(radius+V*radius*.55*np.cos(twist))*np.cos(U);y=(radius+V*radius*.55*np.cos(twist))*np.sin(U);z=V*radius*.55*np.sin(twist)
  tilt=.45+metrics.centroid*.6;xp=cx+x*np.cos(tilt)-z*np.sin(tilt);yp=cy+y+z*np.cos(tilt)*.42
  for r in range(len(vv)):out.append(_path(f"mobius:row:{r}",zip(xp[r],yp[r]),size,"curve",False,1,int(80+metrics.energy*100)))
  stride=max(1,int(5-d*3))
  for j,c in enumerate(range(0,len(uv),stride)):out.append(_path(f"mobius:col:{j}",zip(xp[:,c],yp[:,c]),size,"grid",False,1,90))
  return out
 if name=="AXONOMETRIC FIELD":
  co,si=.8660254,.5;cols,rows=3+int(d*3),2+int(d*2);spacing=u*(.085+d*.018);phase=seconds*(.025+s*.11)
  def project(x,y,z):return (cx+(x-y)*co*spacing,cy+(x+y)*si*spacing-z*u*.12)
  for r in range(rows):
   for c in range(cols):
    idx=r*cols+c;band=float(bands[(idx*7)%len(bands)]) if len(bands) else 0;wave=.5+.5*math.sin(phase+c*.72-r*.51);z=.22+band*1.35+metrics.energy*.75+wave*metrics.transient*.9;x,y=c-(cols-1)/2,r-(rows-1)/2
    base=[project(x,y,0),project(x+.78,y,0),project(x+.78,y+.78,0),project(x,y+.78,0)];top=[project(x,y,z),project(x+.78,y,z),project(x+.78,y+.78,z),project(x,y+.78,z)];alpha=int(100+metrics.energy*70)
    for e in range(4):
     n=(e+1)%4;out.append(_path(f"axon:{r}:{c}:base:{e}",[base[e],base[n]],size,"line",False,1,int(alpha*.22)));out.append(_path(f"axon:{r}:{c}:top:{e}",[top[e],top[n]],size,"line",False,1,min(235,alpha+25)));out.append(_path(f"axon:{r}:{c}:vertical:{e}",[base[e],top[e]],size,"line",False,1,alpha))
  return out
 return None

def _resample(points,count,closed):
 p=np.asarray(points,dtype=np.float64)
 if p.ndim!=2 or len(p)<2 or p.shape[1]!=2:return None
 if closed:p=np.vstack((p,p[0]))
 lengths=np.sqrt(np.sum(np.diff(p,axis=0)**2,axis=1));cum=np.r_[0.,np.cumsum(lengths)];total=float(cum[-1])
 if total<=1e-8:return np.repeat(p[:1],count,axis=0)
 s=np.linspace(0,total,count,endpoint=not closed)
 return np.column_stack((np.interp(s,cum,p[:,0]),np.interp(s,cum,p[:,1])))

def _align(a,b,closed):
 if not closed:return b if np.linalg.norm(a[0]-b[0])+np.linalg.norm(a[-1]-b[-1])<=np.linalg.norm(a[0]-b[-1])+np.linalg.norm(a[-1]-b[0]) else b[::-1]
 best,cost=b,float("inf")
 for q in (b,b[::-1]):
  r=np.roll(q,-int(np.argmin(np.sum((q-a[0])**2,axis=1))),axis=0);v=float(np.mean(np.sum((r-a)**2,axis=1)))
  if v<cost:best,cost=r,v
 return best

def _center(p):
 q=np.asarray(p.get("points") or [],dtype=np.float64)
 return np.mean(q,axis=0) if q.ndim==2 and len(q) else np.zeros(2)

def interpolate_vector_paths(source,target,progress):
 t=float(np.clip(progress,0,1));a=list(source or []);b=list(target or []);amap={str(p["path_id"]):p for p in a};bmap={str(p["path_id"]):p for p in b};pairs=[];used_a=set();used_b=set()
 for key in sorted(set(amap)&set(bmap)):
  pa,pb=amap[key],bmap[key]
  if pa.get("group")==pb.get("group") and bool(pa.get("closed"))==bool(pb.get("closed")):pairs.append((pa,pb));used_a.add(key);used_b.add(key)
 candidates=[]
 for ka,pa in amap.items():
  if ka in used_a:continue
  for kb,pb in bmap.items():
   if kb in used_b or pa.get("group")!=pb.get("group") or bool(pa.get("closed"))!=bool(pb.get("closed")):continue
   candidates.append((float(np.linalg.norm(_center(pa)-_center(pb))),ka,kb))
 for _,ka,kb in sorted(candidates):
  if ka in used_a or kb in used_b:continue
  used_a.add(ka);used_b.add(kb);pairs.append((amap[ka],bmap[kb]))
 result=[]
 for pa,pb in pairs:
  closed=bool(pa.get("closed"));n=max(16,min(128,max(len(pa["points"]),len(pb["points"]))));x,y=_resample(pa["points"],n,closed),_resample(pb["points"],n,closed)
  if x is None or y is None:continue
  y=_align(x,y,closed);col=np.asarray(pa.get("color",[238,238,234]))*(1-t)+np.asarray(pb.get("color",[238,238,234]))*t
  result.append({"path_id":f"morph:{pa['path_id']}:{pb['path_id']}","group":pa.get("group","stroke"),"closed":closed,"points":(x*(1-t)+y*t).tolist(),"width":float(pa.get("width",1))*(1-t)+float(pb.get("width",1))*t,"color":np.clip(col,0,255).tolist(),"alpha":float(pa.get("alpha",180))*float(pa.get("opacity",1))*(1-t)+float(pb.get("alpha",180))*float(pb.get("opacity",1))*t,"opacity":1.})
 for p in a:
  if str(p["path_id"]) not in used_a:q=dict(p);q["opacity"]=float(q.get("opacity",1))*(1-t);result.append(q)
 for p in b:
  if str(p["path_id"]) not in used_b:q=dict(p);q["opacity"]=float(q.get("opacity",1))*t;result.append(q)
 return result

def render_vector_paths(paths,size):
 w,h=max(1,int(size[0])),max(1,int(size[1]));image=Image.new("RGBA",(w,h),(0,0,0,0));draw=ImageDraw.Draw(image);scale=min(w,h)/480.
 for p in paths or []:
  if len(p.get("points") or [])<2:continue
  alpha=int(np.clip(float(p.get("alpha",180))*float(np.clip(p.get("opacity",1),0,1)),0,255))
  if alpha<=0:continue
  color=[int(np.clip(v,0,255)) for v in p.get("color",[238,238,234])]
  xy=[(int(round(float(x)*(w-1))),int(round(float(y)*(h-1)))) for x,y in p["points"]]
  if p.get("closed"):xy.append(xy[0])
  draw.line(xy,fill=(*color[:3],alpha),width=max(1,int(round(float(p.get("width",1))*scale))),joint="curve")
 return image
