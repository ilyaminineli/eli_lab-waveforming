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

def _resample_at(points, fractions, closed):
 p=np.asarray(points,dtype=np.float64)
 if p.ndim!=2 or len(p)<2 or p.shape[1]!=2:
  return None
 if closed:
  p=np.vstack((p,p[0]))
 lengths=np.sqrt(np.sum(np.diff(p,axis=0)**2,axis=1))
 cumulative=np.r_[0.,np.cumsum(lengths)]
 total=float(cumulative[-1])
 if total<=1e-8:
  return np.repeat(p[:1],len(fractions),axis=0)
 distances=np.clip(np.asarray(fractions,dtype=np.float64),0,1)*total
 return np.column_stack((
  np.interp(distances,cumulative,p[:,0]),
  np.interp(distances,cumulative,p[:,1]),
 ))

def _resample(points,count,closed):
 return _resample_at(points,np.linspace(0,1,count,endpoint=not closed),closed)

def _align(a,b,closed):
 if not closed:
  direct=np.linalg.norm(a[0]-b[0])+np.linalg.norm(a[-1]-b[-1])
  reverse=np.linalg.norm(a[0]-b[-1])+np.linalg.norm(a[-1]-b[0])
  return b if direct<=reverse else b[::-1]
 best,cost=b,float("inf")
 for candidate in (b,b[::-1]):
  offset=int(np.argmin(np.sum((candidate-a[0])**2,axis=1)))
  rolled=np.roll(candidate,-offset,axis=0)
  error=float(np.mean(np.sum((rolled-a)**2,axis=1)))
  if error<cost:
   best,cost=rolled,error
 return best

def _center(path):
 points=np.asarray(path.get("points") or [],dtype=np.float64)
 return np.mean(points,axis=0) if points.ndim==2 and len(points) else np.zeros(2)

def _sample_anchored_pair(source_path,target_path,count,anchors):
 """Sample both paths through paired arc-length landmarks."""
 source_t=np.asarray([item["source_t"] for item in anchors],dtype=np.float64)
 target_t=np.asarray([item["target_t"] for item in anchors],dtype=np.float64)
 mean_segments=(np.diff(source_t)+np.diff(target_t))*0.5
 cumulative=np.r_[0.,np.cumsum(mean_segments)]
 if cumulative[-1]<=1e-9:
  u_knots=np.linspace(0,1,len(anchors))
 else:
  u_knots=cumulative/cumulative[-1]
 u_samples=np.unique(np.r_[np.linspace(0,1,count),u_knots])
 src_samples=np.interp(u_samples,u_knots,source_t)
 tgt_samples=np.interp(u_samples,u_knots,target_t)
 source_points=_resample_at(
  source_path["points"],src_samples,bool(source_path.get("closed"))
 )
 target_points=_resample_at(
  target_path["points"],tgt_samples,bool(target_path.get("closed"))
 )
 return source_points,target_points

def _morph_pair(source,target,progress,anchors=None,
                source_alpha_scale=1.0,target_alpha_scale=1.0,
                path_id=None,mode="pair"):
 closed_source=bool(source.get("closed"))
 closed_target=bool(target.get("closed"))
 if closed_source!=closed_target:
  raise ValueError(
   "Authored path correspondence cannot pair open and closed paths yet."
  )
 count=max(16,min(128,max(
  len(source.get("points") or []),len(target.get("points") or [])
 )))
 if anchors:
  a,b=_sample_anchored_pair(source,target,count,anchors)
 else:
  a=_resample(source.get("points") or [],count,closed_source)
  b=_resample(target.get("points") or [],count,closed_target)
  if a is not None and b is not None:
   b=_align(a,b,closed_source)
 if a is None or b is None:
  return None
 t=float(np.clip(progress,0,1))
 source_color=np.asarray(source.get("color",[238,238,234]),dtype=np.float64)
 target_color=np.asarray(target.get("color",[238,238,234]),dtype=np.float64)
 color=source_color*(1-t)+target_color*t
 source_alpha=float(source.get("alpha",180))*float(source.get("opacity",1))*source_alpha_scale
 target_alpha=float(target.get("alpha",180))*float(target.get("opacity",1))*target_alpha_scale
 return {
  "path_id":path_id or f"morph:{source['path_id']}:{target['path_id']}",
  "group":source.get("group",target.get("group","stroke")),
  "closed":closed_source,
  "points":(a*(1-t)+b*t).tolist(),
  "width":float(source.get("width",1))*(1-t)+float(target.get("width",1))*t,
  "color":np.clip(color,0,255).tolist(),
  "alpha":source_alpha*(1-t)+target_alpha*t,
  "opacity":1.0,
  "correspondence_mode":mode,
 }

def interpolate_vector_paths(source,target,progress,path_correspondence=None):
 """Morph paths using authored pair/split/merge maps, then automatic matching.

 Authored path maps consume their IDs before the deterministic fallback matcher
 sees the remaining paths. Split duplicates one source contour and fans it out;
 merge converges source contours onto a shared target with distributed ink weight.
 """
 t=float(np.clip(progress,0,1))
 source_paths=list(source or [])
 target_paths=list(target or [])
 source_map={str(path["path_id"]):path for path in source_paths}
 target_map={str(path["path_id"]):path for path in target_paths}
 used_source=set()
 used_target=set()
 result=[]

 for mapping_index,mapping in enumerate(path_correspondence or []):
  source_ids=list(mapping["source_path_ids"])
  target_ids=list(mapping["target_path_ids"])
  missing_source=[item for item in source_ids if item not in source_map]
  missing_target=[item for item in target_ids if item not in target_map]
  if missing_source or missing_target:
   raise ValueError(
    "Authored path map references unavailable path IDs: "
    + ", ".join([*missing_source,*missing_target])
   )
  if any(item in used_source for item in source_ids):
   raise ValueError("Authored path maps reuse an outgoing path ID.")
  if any(item in used_target for item in target_ids):
   raise ValueError("Authored path maps reuse an incoming path ID.")
  mode=str(mapping.get("mode","pair")).lower()
  anchors=list(mapping.get("anchors") or [])
  if mode=="pair":
   pairs=[(source_ids[0],target_ids[0],1.0,1.0)]
  elif mode=="split":
   divisor=float(len(target_ids))
   pairs=[(source_ids[0],target_id,1.0/divisor,1.0) for target_id in target_ids]
  elif mode=="merge":
   divisor=float(len(source_ids))
   pairs=[(source_id,target_ids[0],1.0,1.0/divisor) for source_id in source_ids]
  else:
   raise ValueError(f"Unsupported authored path mapping mode: {mode}")
  for pair_index,(source_id,target_id,source_scale,target_scale) in enumerate(pairs):
   item=_morph_pair(
    source_map[source_id],target_map[target_id],t,
    anchors=anchors,
    source_alpha_scale=source_scale,
    target_alpha_scale=target_scale,
    path_id=f"authored:{mapping_index}:{pair_index}:{source_id}:{target_id}",
    mode=mode,
   )
   if item is not None:
    result.append(item)
  used_source.update(source_ids)
  used_target.update(target_ids)

 # Keep the existing stable-ID + compatible-group nearest-centroid matcher
 # for every path that has not been authored explicitly.
 remaining_source=[path for path in source_paths if str(path["path_id"]) not in used_source]
 remaining_target=[path for path in target_paths if str(path["path_id"]) not in used_target]
 source_by_id={str(path["path_id"]):path for path in remaining_source}
 target_by_id={str(path["path_id"]):path for path in remaining_target}
 auto_pairs=[]
 for path_id in sorted(set(source_by_id)&set(target_by_id)):
  a,b=source_by_id[path_id],target_by_id[path_id]
  if a.get("group")==b.get("group") and bool(a.get("closed"))==bool(b.get("closed")):
   auto_pairs.append((path_id,path_id))
   used_source.add(path_id)
   used_target.add(path_id)
 candidates=[]
 for source_id,a in source_by_id.items():
  if source_id in used_source:continue
  for target_id,b in target_by_id.items():
   if target_id in used_target:continue
   if a.get("group")!=b.get("group") or bool(a.get("closed"))!=bool(b.get("closed")):
    continue
   count_penalty=abs(np.log(
    max(1,len(a.get("points") or []))/max(1,len(b.get("points") or []))
   ))*.04
   distance=float(np.linalg.norm(_center(a)-_center(b)))+float(count_penalty)
   candidates.append((distance,source_id,target_id))
 for _,source_id,target_id in sorted(candidates):
  if source_id in used_source or target_id in used_target:continue
  auto_pairs.append((source_id,target_id))
  used_source.add(source_id)
  used_target.add(target_id)
 for source_id,target_id in auto_pairs:
  item=_morph_pair(
   source_by_id[source_id],target_by_id[target_id],t,
   path_id=f"morph:{source_id}:{target_id}",
   mode="automatic",
  )
  if item is not None:
   result.append(item)
 for path in source_paths:
  path_id=str(path["path_id"])
  if path_id not in used_source:
   item=dict(path)
   item["opacity"]=float(item.get("opacity",1.0))*(1.0-t)
   result.append(item)
 for path in target_paths:
  path_id=str(path["path_id"])
  if path_id not in used_target:
   item=dict(path)
   item["opacity"]=float(item.get("opacity",1.0))*t
   result.append(item)
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
