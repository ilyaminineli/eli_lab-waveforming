from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .assets import AssetCatalog
from .generators import GeneratorBank, GeneratorSettings
from .layers import VisualLayer

PREVIEW_SIZE = (960, 720)


class VisualCompositor:
    """Layer compositor with frame masks, paper relief, shader-like filters and feedback."""

    def __init__(self, assets: AssetCatalog):
        self.assets = assets
        self.generators = GeneratorBank()
        self._screen_cache: dict[str, Image.Image] = {}
        self._pass_cache: dict[str, Image.Image] = {}
        self._feedback: Image.Image | None = None
        self._last_time: float | None = None

    def generator_names(self) -> list[str]:
        return self.generators.names()

    def pass_names(self) -> list[str]:
        return ["None", *self.assets.pass_names()]

    def reset_feedback(self) -> None:
        self._feedback = None
        self._last_time = None
        # Stateful generators restart from a deterministic initial condition on
        # stop/seek so temporal systems do not retain a stale simulation history.
        self.generators.reset_states()

    def _screen(self, name: str) -> Image.Image | None:
        if name == "No guide":
            return None
        if name not in self._screen_cache:
            image = self.assets.load_screen(name)
            if image is not None:
                self._screen_cache[name] = image.resize(PREVIEW_SIZE, Image.Resampling.LANCZOS)
        return self._screen_cache.get(name)

    def _pass(self, name: str) -> Image.Image | None:
        if name == "None":
            return None
        if name not in self._pass_cache:
            image = self.assets.load_pass(name)
            if image is not None:
                self._pass_cache[name] = image.resize(PREVIEW_SIZE, Image.Resampling.BILINEAR)
        return self._pass_cache.get(name)

    def _frame_box(self, screen: str) -> tuple[int, int, int, int]:
        normalized = self.assets.frame_box(screen)
        w, h = PREVIEW_SIZE
        x0, y0, x1, y1 = normalized
        return (int(round(x0*w)), int(round(y0*h)),
                int(round(x1*w)), int(round(y1*h)))

    def _mask(self, mode: str, frame_box: tuple[int, int, int, int]) -> Image.Image:
        w, h = PREVIEW_SIZE
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        x0, y0, x1, y1 = frame_box
        if mode == "FULL":
            draw.rectangle((0, 0, w-1, h-1), fill=255)
        elif mode == "ELLIPSE":
            draw.ellipse((x0, y0, x1, y1), fill=255)
        elif mode == "INSET":
            pad_x = int((x1-x0)*0.075)
            pad_y = int((y1-y0)*0.075)
            draw.rectangle((x0+pad_x, y0+pad_y, x1-pad_x, y1-pad_y), fill=255)
        else:
            # FRAME is the inner printable/content area, never the outer rulers.
            inset = max(1, int(min(x1-x0, y1-y0)*0.006))
            draw.rectangle((x0+inset, y0+inset, x1-inset, y1-inset), fill=255)
        return mask

    @staticmethod
    def _normalize_height(image: Image.Image) -> np.ndarray:
        gray = np.asarray(image.convert("L").filter(ImageFilter.GaussianBlur(0.45)), dtype=np.float32)
        center = float(np.mean(gray))
        spread = float(np.std(gray))
        low, high = center - 2.2*spread, center + 2.2*spread
        if high <= low + 1e-5:
            return np.zeros_like(gray, dtype=np.float32) + 0.5
        return np.clip((gray-low)/(high-low), 0.0, 1.0)

    @staticmethod
    def _warp_with_height(image: Image.Image, height: np.ndarray, strength: float) -> Image.Image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        h, w = rgba.shape[:2]
        gy, gx = np.gradient(height)
        # Small height-gradient offsets keep the layer tactile, not globally distorted.
        amount = float(np.clip(strength, 0, 1))
        yy, xx = np.indices((h, w), dtype=np.float32)
        sx = np.clip((xx + gx * amount * 7.0).astype(np.int32), 0, w-1)
        sy = np.clip((yy + gy * amount * 7.0).astype(np.int32), 0, h-1)
        return Image.fromarray(rgba[sy, sx], "RGBA")

    @staticmethod
    def _derive_normals(height: np.ndarray, strength: float) -> np.ndarray:
        gy, gx = np.gradient(height)
        amount = 1.0 + float(np.clip(strength, 0, 1))*10.0
        nx = -gx*amount
        ny = -gy*amount
        nz = np.ones_like(nx)
        length = np.sqrt(nx*nx+ny*ny+nz*nz)+1e-8
        return np.stack((nx/length, ny/length, nz/length), axis=-1)

    def _normal_field(self, size: tuple[int, int], height: np.ndarray,
                      strength: float) -> np.ndarray:
        normal_image = self._pass("NORMAL")
        if normal_image is not None:
            normal_image = normal_image.resize(size, Image.Resampling.BILINEAR)
            normal_rgb = np.asarray(normal_image.convert("RGB"), dtype=np.float32)/127.5-1.0
            length = np.linalg.norm(normal_rgb, axis=-1, keepdims=True)
            # If the map is a real tangent-space normal map, preserve its direction.
            if float(np.mean(normal_rgb[..., 2])) > 0.10:
                return normal_rgb/(length+1e-8)
        return self._derive_normals(height, strength)

    def _apply_paper_relief(self, image: Image.Image, strength: float,
                            pass_map: str = "DISPLACEMENT") -> Image.Image:
        size = image.size
        height_image = self._pass(pass_map) or self._pass("DISPLACEMENT") or self._pass("TEXTURE")
        if height_image is None:
            return image
        height_image = height_image.resize(size, Image.Resampling.BILINEAR)
        height = self._normalize_height(height_image)
        displaced = self._warp_with_height(image, height, strength)
        rgba = np.asarray(displaced.convert("RGBA"), dtype=np.uint8).copy()
        normals = self._normal_field(size, height, strength)
        light = np.asarray([-0.42, -0.48, 0.77], dtype=np.float32)
        light /= np.linalg.norm(light)
        diffuse = np.clip(np.sum(normals*light, axis=-1), 0.0, 1.0)
        shading = 0.66 + diffuse*(0.28 + 0.34*float(np.clip(strength, 0, 1)))

        texture = self._pass("TEXTURE")
        if texture is not None:
            texture = texture.resize(size, Image.Resampling.BILINEAR)
            grain = np.asarray(texture.convert("L"), dtype=np.float32)
            grain_center = float(np.mean(grain))
            grain_spread = float(np.std(grain))
            grain_lo = grain_center - 1.8*grain_spread
            grain_hi = grain_center + 1.8*grain_spread
            grain = np.clip((grain-grain_lo)/(grain_hi-grain_lo+1e-6), 0, 1)
            texture_gain = 0.92 + (grain-0.5)*(0.10+0.12*strength)
        else:
            texture_gain = 1.0

        rgb = rgba[..., :3].astype(np.float32)
        rgb *= (shading*texture_gain)[..., None]
        rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")

    def _apply_pass_mode(self, image: Image.Image, mode: str, strength: float,
                         pass_map: str) -> Image.Image:
        amount = float(np.clip(strength, 0.0, 1.0))
        if mode == "PAPER RELIEF":
            return self._apply_paper_relief(image, amount, pass_map)
        if mode == "DISPLACE":
            pass_image = self._pass(pass_map) or self._pass("DISPLACEMENT")
            if pass_image is None:
                return image
            height = self._normalize_height(pass_image.resize(image.size, Image.Resampling.BILINEAR))
            return self._warp_with_height(image, height, amount)
        if mode == "NORMAL LIGHT":
            if self._pass("NORMAL") is not None:
                height_image = self._pass(pass_map) or self._pass("DISPLACEMENT")
                height = self._normalize_height(height_image.resize(image.size, Image.Resampling.BILINEAR))
                normals = self._normal_field(image.size, height, amount)
                rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
                light = np.asarray([-0.45, -0.3, 0.84], dtype=np.float32)
                light /= np.linalg.norm(light)
                shade = np.clip(0.55+0.65*np.sum(normals*light, axis=-1), 0.25, 1.25)
                rgba[..., :3] = np.clip(rgba[..., :3].astype(np.float32)*shade[..., None],0,255).astype(np.uint8)
                return Image.fromarray(rgba, "RGBA")
            return self._apply_paper_relief(image, amount, pass_map)
        if mode == "TEXTURE":
            texture = self._pass("TEXTURE")
            if texture is not None:
                texture = texture.resize(image.size, Image.Resampling.BILINEAR)
                rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
                grain = np.asarray(texture.convert("L"), dtype=np.float32)/255.0
                gain = 0.72 + grain*(0.45+amount*0.35)
                rgba[..., :3] = np.clip(rgba[..., :3].astype(np.float32)*gain[...,None],0,255).astype(np.uint8)
                return Image.fromarray(rgba,"RGBA")
        if mode == "EDGE":
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
            gray = rgba[..., :3].mean(axis=2)
            gy, gx = np.gradient(gray)
            edge = np.sqrt(gx*gx+gy*gy)
            threshold = float(np.mean(edge) + 0.65*np.std(edge))
            alpha = np.clip((edge-threshold)*amount*8, 0, 235).astype(np.uint8)
            rgba[..., :3] = 235
            rgba[..., 3] = np.minimum(rgba[..., 3], alpha)
            return Image.fromarray(rgba,"RGBA")
        return image

    @staticmethod
    def _apply_shader(image: Image.Image, shader: str, amount: float) -> Image.Image:
        if shader == "NONE":
            return image
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        h, w = rgba.shape[:2]
        factor = float(np.clip(amount, 0, 1))
        rgb = rgba[..., :3].astype(np.float32)
        if shader == "POSTERIZE":
            levels = max(2, int(12 - factor*9))
            step = 255.0/(levels-1)
            rgba[..., :3] = (np.round(rgb/step)*step).clip(0,255).astype(np.uint8)
        elif shader == "SCANLINES":
            rows = np.arange(h)[:,None]
            shade = np.where(rows % 4 == 0, 1.0-factor*0.62, 1.0-factor*0.10)
            rgba[..., :3] = np.clip(rgb*shade[...,None],0,255).astype(np.uint8)
        elif shader == "HALFTONE":
            yy, xx = np.indices((h,w), dtype=np.float32)
            pitch = max(3, int(12-factor*7))
            pattern = (np.sin(xx*2*np.pi/pitch)*np.sin(yy*2*np.pi/pitch)+1)*0.5
            lum = rgb.mean(axis=2)/255.0
            keep = lum > (pattern*(0.45+factor*0.5))
            rgba[..., 3] = np.where(keep, rgba[...,3], 0).astype(np.uint8)
        elif shader == "EDGE":
            gray = rgb.mean(axis=2)
            gy,gx=np.gradient(gray)
            edge=np.sqrt(gx*gx+gy*gy)
            threshold=float(np.mean(edge)+0.65*np.std(edge))
            mask=np.clip((edge-threshold)*(2+factor*12),0,255)
            rgba[..., :3]=245
            rgba[..., 3]=np.minimum(rgba[...,3],mask).astype(np.uint8)
        elif shader == "WAVE WARP":
            yy,xx=np.indices((h,w),dtype=np.float32)
            dx=np.sin(yy*(0.025+factor*0.055))*factor*22
            sx=np.clip((xx+dx).astype(np.int32),0,w-1)
            rgba=rgba[np.arange(h)[:,None],sx]
        elif shader == "DITHER":
            gray=rgb.mean(axis=2)
            xx,yy=np.meshgrid(np.arange(w),np.arange(h))
            matrix=np.asarray([[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]],dtype=np.float32)/16.0
            threshold=matrix[yy%4,xx%4]
            keep=gray/255.0 > threshold*(0.45+factor*0.55)
            rgba[...,3]=np.where(keep,rgba[...,3],0).astype(np.uint8)
        return Image.fromarray(rgba,"RGBA")

    @staticmethod
    def _transform(layer: Image.Image, center: tuple[float,float],
                   x_offset: float, y_offset: float, scale: float,
                   rotation: float) -> tuple[Image.Image, tuple[int,int]]:
        sw,sh=layer.size
        scale=max(0.05,min(4.0,float(scale)))
        tw,th=max(1,int(sw*scale)),max(1,int(sh*scale))
        transformed=layer.resize((tw,th),Image.Resampling.BICUBIC)
        if abs(rotation)>0.001:
            transformed=transformed.rotate(float(rotation),resample=Image.Resampling.BICUBIC,expand=True)
        cx=center[0]+x_offset*PREVIEW_SIZE[0]
        cy=center[1]+y_offset*PREVIEW_SIZE[1]
        return transformed,(int(round(cx-transformed.width/2)),int(round(cy-transformed.height/2)))

    @staticmethod
    def _blend_into(destination: Image.Image, source: Image.Image, mode: str,
                    opacity: float = 1.0) -> Image.Image:
        dst = np.asarray(destination.convert("RGBA"), dtype=np.uint8).astype(np.float32)
        src = np.asarray(source.convert("RGBA"), dtype=np.uint8).astype(np.float32)
        da = dst[..., 3:4] / 255.0
        sa = (src[..., 3:4] / 255.0) * float(np.clip(opacity, 0, 1))
        backdrop = dst[..., :3]
        foreground = src[..., :3]

        if mode == "Add":
            blended = np.clip(backdrop + foreground, 0, 255)
        elif mode == "Multiply":
            blended = backdrop * foreground / 255.0
        elif mode == "Screen":
            blended = 255.0 - (255.0-backdrop) * (255.0-foreground) / 255.0
        elif mode == "Difference":
            blended = np.abs(backdrop-foreground)
        elif mode == "Overlay":
            normalized = backdrop / 255.0
            blended = np.where(
                normalized < 0.5,
                2.0*normalized*foreground/255.0,
                1.0-2.0*(1.0-normalized)*(1.0-foreground/255.0),
            )*255.0
        elif mode == "Lighten":
            blended = np.maximum(backdrop, foreground)
        elif mode == "Darken":
            blended = np.minimum(backdrop, foreground)
        else:
            blended = foreground

        # W3C-style alpha compositing in premultiplied space. Unlike a naive
        # opaque RGB blend, this preserves transparent gaps between visual layers.
        out_alpha = sa + da*(1.0-sa)
        out_premult = (
            (1.0-sa)*da*backdrop
            + (1.0-da)*sa*foreground
            + da*sa*blended
        )
        out_rgb = np.where(out_alpha > 1e-8, out_premult/np.maximum(out_alpha,1e-8), 0.0)
        result = np.empty_like(dst, dtype=np.uint8)
        result[..., :3] = np.clip(out_rgb,0,255).astype(np.uint8)
        result[..., 3] = np.clip(out_alpha[...,0]*255.0,0,255).astype(np.uint8)
        return Image.fromarray(result,"RGBA")

    def _render_layer(self, layer: VisualLayer, packet: dict | None, seconds: float,
                      settings: GeneratorSettings, frame_box: tuple[int,int,int,int]) -> Image.Image:
        w,h=PREVIEW_SIZE
        x0,y0,x1,y1=frame_box
        if layer.mask_mode=="FULL":
            target_box=(0,0,w,h)
        else:
            target_box=frame_box
        tx0,ty0,tx1,ty1=target_box
        local_size=(max(1,tx1-tx0),max(1,ty1-ty0))
        visual=self.generators.render(layer.generator,packet,seconds,local_size,settings,state_key=layer.layer_id)
        visual=self._apply_pass_mode(visual,layer.pass_mode,layer.pass_strength,layer.pass_map)
        visual=self._apply_shader(visual,layer.shader,layer.shader_amount)
        center=((tx0+tx1)/2,(ty0+ty1)/2)
        transformed,position=self._transform(
            visual,center,layer.x_offset,layer.y_offset,layer.scale,layer.rotation
        )
        canvas=Image.new("RGBA",PREVIEW_SIZE,(0,0,0,0))
        canvas.alpha_composite(transformed,position)
        if layer.mask_mode=="ELLIPSE":
            clip=self._mask("ELLIPSE",frame_box)
        elif layer.mask_mode=="INSET":
            clip=self._mask("INSET",frame_box)
        elif layer.mask_mode=="FULL":
            clip=self._mask("FULL",frame_box)
        else:
            clip=self._mask("FRAME",frame_box)
        alpha=canvas.getchannel("A")
        alpha=Image.fromarray(
            ((np.asarray(alpha,dtype=np.float32)*np.asarray(clip,dtype=np.float32)/255.0).astype(np.uint8)),
            "L"
        )
        canvas.putalpha(alpha)
        return canvas

    def render(self, packet: dict | None, seconds: float,
               layers: list[VisualLayer] | None = None,
               settings: GeneratorSettings | None = None,
               screen: str = "No guide",
               feedback_enabled: bool = False,
               feedback_amount: float = 0.35,
               feedback_decay: float = 0.90,
               feedback_shift: float = 0.0) -> Image.Image:
        settings=settings or GeneratorSettings()
        layers=layers or []
        base=Image.new("RGBA",PREVIEW_SIZE,(10,10,10,255))
        guide=self._screen(screen)
        if guide is not None:
            base.alpha_composite(guide)
        frame_box=self._frame_box(screen)
        stack=Image.new("RGBA",PREVIEW_SIZE,(0,0,0,0))

        for layer in layers:
            if not layer.visible:
                continue
            visual=self._render_layer(layer,packet,seconds,settings,frame_box)
            stack=self._blend_into(stack,visual,layer.blend_mode,layer.opacity)

        if feedback_enabled:
            if self._last_time is not None and seconds < self._last_time:
                self._feedback=None
            if self._feedback is not None:
                previous=np.asarray(self._feedback,dtype=np.uint8)
                dx=int(round(feedback_shift*PREVIEW_SIZE[0]))
                dy=int(round(feedback_shift*PREVIEW_SIZE[1]*0.62))
                previous=np.roll(previous,(dy,dx),axis=(0,1))
                previous_image=Image.fromarray(previous,"RGBA")
                alpha=previous_image.getchannel("A").point(
                    [int(value*float(np.clip(feedback_decay,0,0.99))) for value in range(256)]
                )
                previous_image.putalpha(alpha)
                stack=self._blend_into(stack,previous_image,"Screen",
                                       float(np.clip(feedback_amount,0,1)))
            self._feedback=stack.copy()
            self._last_time=seconds
        else:
            self._feedback=None
            self._last_time=seconds

        base.alpha_composite(stack)
        return base
