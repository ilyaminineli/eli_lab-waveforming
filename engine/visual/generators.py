from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


@dataclass(slots=True)
class VisualMetrics:
    rms: float = 0.0
    energy: float = 0.0
    transient: float = 0.0
    flux: float = 0.0
    centroid: float = 0.0
    flatness: float = 0.0
    entropy: float = 0.0
    zcr: float = 0.0
    width: float = 0.0
    rolloff: float = 0.0
    crest: float = 0.0
    cross: float = 0.0
    coherence: float = 1.0
    low: float = 0.0
    mid: float = 0.0
    high: float = 0.0
    bands: np.ndarray | None = None
    energies: np.ndarray | None = None
    correlation: np.ndarray | None = None
    source_count: int = 0

    @classmethod
    def from_packet(cls, packet: dict | None) -> "VisualMetrics":
        packet = packet or {}
        frames = list(packet.get("frames", {}).values())
        if not frames:
            return cls()
        def mean(field: str) -> float:
            return float(np.mean([getattr(frame, field) for frame in frames]))
        bands = np.mean(np.stack([frame.bands for frame in frames]), axis=0).astype(np.float32)
        n = len(bands)
        low = float(np.mean(bands[:max(1, n // 4)]))
        mid = float(np.mean(bands[n // 4:max(n // 4 + 1, 3 * n // 4)]))
        high = float(np.mean(bands[3 * n // 4:])) if n else 0.0
        energies = np.asarray([frame.rms for frame in frames], dtype=np.float32)
        corr = np.asarray(packet.get("correlation", np.eye(len(frames))), dtype=np.float32)
        if corr.ndim != 2 or corr.size == 0 or corr.shape[0] <= 1:
            cross, coherence = 0.0, 1.0
        else:
            offdiag = corr[np.triu_indices(corr.shape[0], 1)]
            cross = float(np.mean(np.abs(offdiag)))
            coherence = float(np.mean(offdiag))
        rms = mean("rms")
        flux = mean("flux")
        return cls(
            rms=rms,
            energy=float(np.tanh(rms * 4.5)),
            transient=float(np.clip(flux * 32.0, 0.0, 1.0)),
            flux=flux,
            centroid=mean("centroid_norm"),
            flatness=mean("flatness"),
            entropy=mean("entropy"),
            zcr=mean("zcr"),
            width=mean("stereo_width"),
            rolloff=mean("rolloff"),
            crest=mean("crest"),
            cross=cross,
            coherence=coherence,
            low=low,
            mid=mid,
            high=high,
            bands=bands,
            energies=energies,
            correlation=corr,
            source_count=len(frames),
        )


@dataclass(slots=True)
class GeneratorSettings:
    complexity: float = 58.0
    motion: float = 42.0
    sensitivity: float = 110.0
    seed: int = 17

    @property
    def density(self) -> float:
        return float(np.clip(self.complexity / 100.0, 0.05, 1.0))

    @property
    def speed(self) -> float:
        return self.motion / 100.0

    @property
    def response(self) -> float:
        return self.sensitivity / 100.0


class VisualGenerator:
    name = "ABSTRACT"

    def render(self, metrics: VisualMetrics, seconds: float, size: tuple[int, int],
               settings: GeneratorSettings) -> Image.Image:
        raise NotImplementedError

    @staticmethod
    def _blank(size: tuple[int, int]) -> Image.Image:
        return Image.new("RGBA", size, (0, 0, 0, 0))


class InterferenceField(VisualGenerator):
    name = "INTERFERENCE FIELD"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        x = np.linspace(-2.4, 2.4, w, dtype=np.float32)[None, :]
        y = np.linspace(-1.8, 1.8, h, dtype=np.float32)[:, None]
        response, density = settings.response, settings.density
        motion = seconds * (0.15 + settings.speed * 1.8)
        bands = metrics.bands if metrics.bands is not None else np.zeros(64, np.float32)
        low = metrics.low
        mid = metrics.mid
        high = metrics.high
        drive = metrics.energy * response
        field_a = np.sin((x * (8 + 22*density) + np.sin(y*(4+10*mid)+motion)*1.8) * (1+metrics.centroid))
        field_b = np.cos((y * (9+25*density) + np.sin(x*(3+12*low)-motion)*1.6) * (1+metrics.cross))
        field_c = np.sin((x+y)*(4+14*metrics.centroid) + motion*1.7 + metrics.transient*2.5)
        field = field_a + field_b*(0.65+metrics.coherence*0.4) + field_c*0.32
        ridge = np.abs(np.sin(field*(3.0+density*13.0) + metrics.entropy*3.0 + drive))
        threshold = 0.035 + (1-density)*0.025 + metrics.transient*0.045
        alpha = np.where(ridge < threshold, np.clip(0.3+(1-ridge/threshold)*0.7, 0, 1), 0)
        lum = np.clip(155+(1-ridge)*95+drive*50+high*35, 0, 255).astype(np.uint8)
        pixels = np.zeros((h,w,4), dtype=np.uint8)
        pixels[..., :3] = lum[...,None]
        pixels[..., 3] = (alpha*235).astype(np.uint8)
        return Image.fromarray(pixels, "RGBA")


class PhaseOrbit(VisualGenerator):
    name = "PHASE ORBIT"

    def render(self, metrics, seconds, size, settings):
        w,h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx,cy = w*0.5,h*0.5
        scale = min(w,h)*0.36
        energies = metrics.energies if metrics.energies is not None else np.array([metrics.rms], np.float32)
        corr = metrics.correlation if metrics.correlation is not None else np.eye(len(energies))
        count = max(2,min(8,2+metrics.source_count))
        theta = np.linspace(0,math.tau*3.0,int(320+settings.density*2100),dtype=np.float32)
        speed = seconds*(0.1+settings.speed*1.1)
        for index in range(count):
            energy = float(energies[index%len(energies)]) if len(energies) else 0.0
            partner = float(corr[index%corr.shape[0],(index+1)%corr.shape[1]]) if corr.size else 0.0
            a,b = 2+(index%5),3+((index*2+1)%7)
            phase = speed*(1+index*0.17)+index*0.73+partner*1.1+metrics.transient*0.8
            radius = scale*(0.28+0.62*np.clip(energy*settings.response*5,0,1))
            modulation = 0.18+metrics.centroid*0.55+metrics.transient*0.22
            r = radius*(0.72+modulation*np.sin(b*theta+phase)+0.08*np.sin((a+b)*theta))
            x = cx+r*np.cos(a*theta+phase*0.6)
            y = cy+r*np.sin(b*theta-phase*0.4)
            pts = [(int(px),int(py)) for px,py in zip(x,y)]
            alpha = int(np.clip(90+energy*settings.response*320+metrics.transient*35,80,245))
            shade = max(145,245-index*10)
            draw.line(pts,fill=(shade,shade,shade,alpha),width=1+(index%2))
        mark = int(min(w,h)*0.035)
        draw.rectangle((cx-mark,cy-mark,cx+mark,cy+mark),outline=(220,220,220,110),width=1)
        return image


class ParticleField(VisualGenerator):
    name = "PARTICLE FIELD"

    def __init__(self):
        self._cache_key = None
        self._points = None

    def _ensure_points(self,size,settings):
        count = int(180+settings.density*2600)
        key=(size,count,settings.seed)
        if key!=self._cache_key:
            rng=np.random.default_rng(settings.seed)
            self._points=rng.random((count,2),dtype=np.float32)
            self._cache_key=key

    def render(self,metrics,seconds,size,settings):
        w,h=size
        self._ensure_points(size,settings)
        x0,y0=self._points[:,0],self._points[:,1]
        drive=metrics.energy*settings.response
        phase=seconds*(0.12+settings.speed*0.9)+x0*math.tau+metrics.centroid*3
        warp=0.012+metrics.transient*0.06+metrics.cross*0.018+drive*0.025
        x=x0+np.sin(y0*math.tau*2+phase)*warp
        y=y0+np.cos(x0*math.tau*3-phase*0.7)*warp
        x=(x+np.sin(phase*0.3+metrics.low)*0.025)%1.0
        y=(y+np.cos(phase*0.27+metrics.high)*0.018)%1.0
        xi=np.clip((x*w).astype(np.int32),0,w-1)
        yi=np.clip((y*h).astype(np.int32),0,h-1)
        pixels=np.zeros((h,w,4),dtype=np.uint8)
        brightness=int(np.clip(120+drive*90+metrics.entropy*55+metrics.transient*65,100,255))
        pixels[yi,xi,:3]=brightness
        pixels[yi,xi,3]=210
        image=Image.fromarray(pixels,"RGBA")
        draw=ImageDraw.Draw(image)
        stride=max(1,len(xi)//420)
        for idx in range(0,len(xi)-stride,stride):
            if abs(xi[idx+stride]-xi[idx])<w*0.25:
                draw.line((int(xi[idx]),int(yi[idx]),int(xi[idx+stride]),int(yi[idx+stride])),
                          fill=(220,220,220,55+int(metrics.transient*60)),width=1)
        return image


class CellularSystem(VisualGenerator):
    name = "CELLULAR SYSTEM"

    def __init__(self):
        self._grid=None
        self._shape=None
        self._rng=None
        self._last_time=None
        self._accumulator=0.0

    def _reset(self,size,settings):
        gw=max(160,int(size[0]//3))
        gh=max(120,int(size[1]//3))
        self._shape=(gh,gw,settings.seed)
        self._rng=np.random.default_rng(settings.seed)
        self._grid=(self._rng.random((gh,gw))>0.91).astype(np.float32)
        self._last_time=None
        self._accumulator=0.0

    def _step(self,metrics,settings,step_index):
        grid=self._grid
        neighbors=sum(np.roll(np.roll(grid,dy,axis=0),dx,axis=1)
                      for dy in (-1,0,1) for dx in (-1,0,1) if dx or dy)
        gh,gw=grid.shape
        yy=np.linspace(0,math.tau*2,gh,dtype=np.float32)[:,None]
        xx=np.linspace(0,math.tau*2,gw,dtype=np.float32)[None,:]
        phase=step_index*0.11+metrics.centroid*math.tau
        # Low, middle and high bands push different spatial axes.
        forcing=(np.sin(yy*(1+metrics.low*5)+phase)*metrics.low+
                 np.cos(xx*(1+metrics.high*7)-phase)*metrics.high)*0.5
        forcing=forcing+metrics.mid*np.sin((xx+yy)*2+phase)
        transient=metrics.transient*settings.response
        # The field is continuous and decays slightly, so use tolerant neighbour
        # bands instead of exact integer comparisons (which would stop births).
        birth_target=2.75 if metrics.centroid>0.58 else 3.0
        birth_tolerance=0.42+metrics.low*0.12
        births=(neighbors>=birth_target-birth_tolerance) & (neighbors<=birth_target+birth_tolerance)
        births |= (neighbors>=2.0) & (neighbors<=2.45) & (forcing>0.55+metrics.mid*0.15)
        survival=(neighbors>=1.55) & (neighbors<=3.75+(1 if metrics.energy>0.45 else 0))
        next_grid=np.where(births,1.0,np.where(survival,grid*0.992,grid*0.015))
        # Transients excite short radial and diagonal fronts, rather than merely
        # changing the output brightness.
        probability=0.0007+min(0.045,transient*0.055)+metrics.energy*0.003
        injection=self._rng.random(grid.shape)<probability
        next_grid[injection]=1.0
        if transient>0.08:
            cx=int((0.5+0.28*math.sin(phase))*gw)
            cy=int((0.5+0.28*math.cos(phase*0.73))*gh)
            radius=max(2,int(2+transient*13))
            yy0,xx0=np.ogrid[:gh,:gw]
            ring=np.abs(np.sqrt((xx0-cx)**2+(yy0-cy)**2)-radius)<1.8
            next_grid[ring]=np.maximum(next_grid[ring],0.85)
        self._grid=np.clip(next_grid,0,1).astype(np.float32)

    def render(self,metrics,seconds,size,settings):
        w,h=size
        shape=(max(120,int(h//3)),max(160,int(w//3)),settings.seed)
        if self._shape!=shape or self._grid is None or (self._last_time is not None and seconds<self._last_time):
            self._reset(size,settings)
        if self._last_time is None:
            self._last_time=seconds
        elapsed=max(0.0,min(0.18,seconds-self._last_time))
        self._last_time=seconds
        step_interval=max(0.018,0.075-settings.speed*0.045)
        self._accumulator+=elapsed
        steps=min(6,int(self._accumulator/step_interval))
        for _ in range(steps):
            self._step(metrics,settings,int(seconds/step_interval)-steps+_)
            self._accumulator-=step_interval
        grid=self._grid
        # Contrast follows energy, while alpha/density follows transients.
        intensity=np.clip(grid*(150+metrics.energy*65+metrics.transient*70),0,255)
        alpha=np.clip(grid*(150+metrics.transient*105),0,245)
        rgba=np.zeros((grid.shape[0],grid.shape[1],4),dtype=np.uint8)
        rgba[...,:3]=intensity[...,None].astype(np.uint8)
        rgba[...,3]=alpha.astype(np.uint8)
        return Image.fromarray(rgba,"RGBA").resize(size,Image.Resampling.NEAREST)


class PhaseLattice(VisualGenerator):
    name = "PHASE LATTICE"

    def render(self,metrics,seconds,size,settings):
        w,h=size
        image=self._blank(size)
        draw=ImageDraw.Draw(image)
        cols=int(9+settings.density*38)
        rows=max(6,int(cols*h/w))
        xs=np.linspace(w*0.08,w*0.92,cols,dtype=np.float32)
        ys=np.linspace(h*0.08,h*0.92,rows,dtype=np.float32)
        xg,yg=np.meshgrid(xs,ys)
        phase=seconds*(0.1+settings.speed*1.4)
        amp=3+metrics.energy*settings.response*45+metrics.transient*60
        xwarp=np.sin(yg/h*math.tau*3+phase+metrics.centroid*4)*amp
        ywarp=np.cos(xg/w*math.tau*4-phase*0.8+metrics.cross*2)*amp
        points=np.stack((xg+xwarp,yg+ywarp),axis=-1)
        for row in points:
            draw.line([(int(x),int(y)) for x,y in row],fill=(230,230,230,155),width=1)
        for col in range(cols):
            draw.line([(int(points[r,col,0]),int(points[r,col,1])) for r in range(rows)],
                      fill=(185,185,185,110),width=1)
        interval=max(2,int(8-settings.density*5))
        for r in range(rows):
            for c in range(cols):
                if (r+c)%interval==0:
                    x,y=points[r,c]
                    rr=1+int(metrics.transient*6*settings.response)
                    draw.ellipse((int(x-rr),int(y-rr),int(x+rr),int(y+rr)),
                                 fill=(255,255,255,170+int(metrics.energy*70)))
        return image


class ReactionDiffusion(VisualGenerator):
    name = "REACTION DIFFUSION"

    def __init__(self):
        self.u=None
        self.v=None
        self._shape=None
        self._last_time=None
        self._accumulator=0.0
        self._rng=np.random.default_rng(31)

    @staticmethod
    def _laplace(field):
        return (
            np.roll(field,1,0)+np.roll(field,-1,0)+np.roll(field,1,1)+np.roll(field,-1,1)
        )*0.2 + (
            np.roll(np.roll(field,1,0),1,1)+np.roll(np.roll(field,1,0),-1,1)+
            np.roll(np.roll(field,-1,0),1,1)+np.roll(np.roll(field,-1,0),-1,1)
        )*0.05 - field

    def _reset(self,size,settings):
        gh=max(112,int(size[1]//3))
        gw=max(160,int(size[0]//3))
        self._shape=(gh,gw,settings.seed)
        self.u=np.ones((gh,gw),dtype=np.float32)
        self.v=np.zeros((gh,gw),dtype=np.float32)
        rng=np.random.default_rng(settings.seed)
        for _ in range(4):
            cx=int(rng.integers(gw//5,4*gw//5))
            cy=int(rng.integers(gh//5,4*gh//5))
            radius=max(4,int(min(gh,gw)*0.025))
            self.v[cy-radius:cy+radius,cx-radius:cx+radius]=0.8
            self.u[cy-radius:cy+radius,cx-radius:cx+radius]=0.15
        self._last_time=None
        self._accumulator=0.0

    def render(self,metrics,seconds,size,settings):
        w,h=size
        shape=(max(112,int(h//3)),max(160,int(w//3)),settings.seed)
        if self._shape!=shape or self.u is None or (self._last_time is not None and seconds<self._last_time):
            self._reset(size,settings)
        if self._last_time is None:
            self._last_time=seconds
        elapsed=max(0.0,min(0.15,seconds-self._last_time))
        self._last_time=seconds
        self._accumulator+=elapsed
        steps=min(4,int(self._accumulator*50))
        self._accumulator-=steps/50.0
        feed=0.034+metrics.low*0.012+metrics.transient*0.012
        kill=0.058+metrics.high*0.010+metrics.cross*0.004
        for _ in range(steps):
            uvv=self.u*self.v*self.v
            du=0.16*self._laplace(self.u)-uvv+feed*(1-self.u)
            dv=0.08*self._laplace(self.v)+uvv-(feed+kill)*self.v
            self.u=np.clip(self.u+du,0,1)
            self.v=np.clip(self.v+dv,0,1)
            if metrics.transient>0.12:
                gh,gw=self.v.shape
                cx=int((0.5+0.30*math.sin(seconds*3+metrics.centroid))*gw)
                cy=int((0.5+0.30*math.cos(seconds*2.1))*gh)
                radius=max(2,int(3+metrics.transient*10))
                self.v[max(0,cy-radius):cy+radius,max(0,cx-radius):cx+radius]=np.maximum(
                    self.v[max(0,cy-radius):cy+radius,max(0,cx-radius):cx+radius],0.75)
        texture=np.clip((self.v*2.5+np.abs(self.u-self.v)*0.8),0,1)
        texture=np.clip((texture-0.22-metrics.energy*0.08)*2.3,0,1)
        rgba=np.zeros((*texture.shape,4),dtype=np.uint8)
        lum=(145+texture*110).astype(np.uint8)
        rgba[...,:3]=lum[...,None]
        rgba[...,3]=(texture*225).astype(np.uint8)
        return Image.fromarray(rgba,"RGBA").resize(size,Image.Resampling.BILINEAR)


class LorenzAttractor(VisualGenerator):
    name = "LORENZ ATTRACTOR"

    def __init__(self):
        self._state=None
        self._points=None
        self._key=None

    def render(self,metrics,seconds,size,settings):
        w,h=size
        key=settings.seed
        if self._key!=key or self._state is None:
            self._state=np.asarray([0.12,0.08,0.04],dtype=np.float64)
            self._points=[]
            self._key=key
        sigma=10.0+metrics.high*3.0
        rho=25.0+metrics.centroid*9.0+metrics.energy*5.0
        beta=2.666+metrics.coherence*0.18
        dt=0.0045+settings.speed*0.001
        steps=180+int(settings.density*180)
        for _ in range(steps):
            x,y,z=self._state
            dx=sigma*(y-x)
            dy=x*(rho-z)-y
            dz=x*y-beta*z
            self._state += np.asarray([dx,dy,dz])*dt
            self._points.append(self._state.copy())
        if len(self._points)>12000:
            self._points=self._points[-12000:]
        points=np.asarray(self._points,dtype=np.float64)
        if len(points)<2:
            return self._blank(size)
        x=points[:,0]; y=points[:,1]; z=points[:,2]
        yaw=seconds*(0.12+settings.speed*0.5)+metrics.transient*0.3
        xr=x*np.cos(yaw)-y*np.sin(yaw)
        yr=x*np.sin(yaw)+y*np.cos(yaw)
        xn=(xr/38.0+0.5)*w
        yn=(0.5-((yr+(z-25)*0.32)/48.0))*h
        image=self._blank(size)
        draw=ImageDraw.Draw(image)
        stride=max(1,len(xn)//4200)
        pts=[(int(np.clip(xn[i],0,w-1)),int(np.clip(yn[i],0,h-1))) for i in range(0,len(xn),stride)]
        if len(pts)>1:
            for i in range(1,len(pts)):
                a=int(80+175*i/len(pts))
                draw.line((pts[i-1],pts[i]),fill=(230,230,230,a),width=1+(i%3==0))
        return image


class SpectralTopography(VisualGenerator):
    name = "SPECTRAL TOPOGRAPHY"

    def render(self,metrics,seconds,size,settings):
        w,h=size
        bands=metrics.bands if metrics.bands is not None else np.zeros(64,dtype=np.float32)
        columns=max(64,int(100+settings.density*240))
        x=np.linspace(0,1,columns,dtype=np.float32)
        spectral=np.interp(x,np.linspace(0,1,len(bands)),bands) if len(bands) else np.zeros(columns)
        y=np.linspace(0,1,h,dtype=np.float32)[:,None]
        phase=seconds*(0.08+settings.speed*0.6)
        base=np.sin(x[None,:]*math.tau*(2+settings.density*5)+phase)*0.08
        ridge=np.sin((y* (8+metrics.low*18)+base*3+metrics.centroid*2)*math.tau)
        spectral_curve=(spectral[None,:]-0.25)*0.38
        harmonic=np.sin((x[None,:]*13+y*5+phase)*math.tau)*0.06
        field=y-0.5-spectral_curve-ridge*0.055-harmonic-metrics.transient*0.035
        contour=np.abs(np.sin(field*(32+settings.density*90)+metrics.entropy*5))
        band_energy=np.clip(spectral[None,:]*0.75+metrics.energy*0.25,0,1)
        alpha=np.where(contour<0.11+metrics.transient*0.12,180+band_energy*70,0)
        pixels=np.zeros((h,columns,4),dtype=np.uint8)
        lum=np.clip(150+band_energy*100,0,255).astype(np.uint8)
        pixels[...,:3]=lum[...,None]
        pixels[...,3]=np.clip(alpha,0,245).astype(np.uint8)
        return Image.fromarray(pixels,"RGBA").resize(size,Image.Resampling.BILINEAR)


class Phyllotaxis(VisualGenerator):
    name = "PHYLLOTAXIS"

    def render(self,metrics,seconds,size,settings):
        w,h=size
        image=self._blank(size)
        draw=ImageDraw.Draw(image)
        count=int(240+settings.density*2600)
        index=np.arange(count,dtype=np.float32)
        golden=math.pi*(3-math.sqrt(5))
        phase=seconds*(0.06+settings.speed*0.6)
        energy=metrics.energy*settings.response
        radius=np.sqrt(index/count)*min(w,h)*0.46
        theta=index*golden+phase+metrics.centroid*1.8
        bands=metrics.bands if metrics.bands is not None else np.zeros(64,np.float32)
        modulation=np.interp(index/count,np.linspace(0,1,len(bands)),bands) if len(bands) else 0
        radius*=0.76+modulation*0.36+metrics.transient*0.12*np.sin(theta*3)
        cx=w*0.5+np.cos(theta*0.5)*energy*w*0.04
        cy=h*0.5+np.sin(theta*0.5)*energy*h*0.04
        x=cx+radius*np.cos(theta)
        y=cy+radius*np.sin(theta)
        stride=max(1,count//1600)
        for i in range(0,count,stride):
            rr=0.6+modulation[i]*2.2+metrics.transient*1.6
            alpha=int(np.clip(95+modulation[i]*115+metrics.energy*60,70,235))
            draw.ellipse((int(x[i]-rr),int(y[i]-rr),int(x[i]+rr),int(y[i]+rr)),
                         fill=(240,240,240,alpha))
            if i>stride and i%max(2,int(15-settings.density*10))==0:
                draw.line((int(x[i-stride]),int(y[i-stride]),int(x[i]),int(y[i])),
                          fill=(190,190,190,75),width=1)
        return image


class MobiusField(VisualGenerator):
    name = "MOBIUS FIELD"

    def render(self,metrics,seconds,size,settings):
        w,h=size
        image=self._blank(size)
        draw=ImageDraw.Draw(image)
        cx,cy=w*0.5,h*0.5
        u=np.linspace(0,math.tau,int(60+settings.density*120),dtype=np.float32)
        v=np.linspace(-0.8,0.8,int(12+settings.density*28),dtype=np.float32)
        U,V=np.meshgrid(u,v)
        twist=0.5*U+seconds*(0.08+settings.speed*0.5)+metrics.transient*0.2
        radius=min(w,h)*(0.22+metrics.energy*0.13)
        x=(radius+V*radius*0.55*np.cos(twist))*np.cos(U)
        y=(radius+V*radius*0.55*np.cos(twist))*np.sin(U)
        z=V*radius*0.55*np.sin(twist)
        tilt=0.45+metrics.centroid*0.6
        xp=cx+x*np.cos(tilt)-z*np.sin(tilt)
        yp=cy+y+z*np.cos(tilt)*0.42
        for row in range(len(v)):
            pts=[(int(a),int(b)) for a,b in zip(xp[row],yp[row])]
            draw.line(pts,fill=(220,220,220,int(80+metrics.energy*100)),width=1)
        for col in range(0,len(u),max(1,int(5-settings.density*3))):
            pts=[(int(xp[row,col]),int(yp[row,col])) for row in range(len(v))]
            draw.line(pts,fill=(180,180,180,90),width=1)
        return image


class GeneratorBank:
    def __init__(self):
        self._generators: dict[str, VisualGenerator] = {}
        self._generator_types: dict[str, type[VisualGenerator]] = {}
        self._instances: dict[tuple[str, str], VisualGenerator] = {}
        for generator in (
            InterferenceField(), PhaseOrbit(), ParticleField(), CellularSystem(),
            PhaseLattice(), ReactionDiffusion(), LorenzAttractor(),
            SpectralTopography(), Phyllotaxis(), MobiusField(),
        ):
            self._generators[generator.name] = generator
            self._generator_types[generator.name] = type(generator)

    def names(self) -> list[str]:
        return list(self._generators)

    def reset_states(self) -> None:
        self._instances.clear()

    def release_state(self, state_key: str) -> None:
        for key in [key for key in self._instances if key[0] == state_key]:
            self._instances.pop(key, None)

    def render(self,name:str,packet:dict|None,seconds:float,size:tuple[int,int],
               settings:GeneratorSettings,state_key:str|None=None)->Image.Image:
        selected=name if name in self._generators else "INTERFERENCE FIELD"
        if state_key is None:
            generator=self._generators[selected]
        else:
            key=(state_key,selected)
            if key not in self._instances:
                self._instances[key]=self._generator_types[selected]()
            generator=self._instances[key]
        metrics=VisualMetrics.from_packet(packet)
        return generator.render(metrics,seconds,size,settings)
